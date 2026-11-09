import base64
import copy
import json
from datetime import datetime, timezone

import pytest
import requests

from mori.core import (AppError, TAIPEI, aggregate, default_settings, evaluate,
                       period_until_yesterday, select_slot, validate_settings)
from mori.notifications import LineClient, build_batches
from mori.providers import GoogleProvider, MetaProvider
from mori.runner import execute
from mori.storage import Conflict, GitHubStore


def account(platform="meta"):
    return {"key": platform, "platform": platform, "name": "測試帳號", "account_id": "1234567890",
            "meta_action_type": "offsite_conversion.fb_pixel_custom.booking_success_once_test",
            "google_conversion_mode": "selected", "google_action_ids": ["42"]}


def rule(**kwargs):
    return {"id": "rule1", "name": "測試規則", "account_key": "meta", "enabled": True,
            "level": "campaign", "period_days": 1, "minimum_spend": 1000, "cpa_threshold": 200,
            "notify_zero": True, "campaign_filter": "", "adset_filter": "", "ad_filter": "",
            "channel": "ALL", **kwargs}


def row(**kwargs):
    return {"account_key": "meta", "currency": "TWD", "campaign_id": "c1", "campaign_name": "台南訂位",
            "adset_id": "s1", "adset_name": "新客", "ad_id": "a1", "ad_name": "開幕",
            "spend": 1200.0, "conversions": 0.0, "impressions": 1000, "clicks": 30, "channel": "META", **kwargs}


def settings():
    value = default_settings()
    value["accounts"] = [account()]
    value["rules"] = [rule()]
    value["schedule"] = {"enabled": True, "times": ["09:15", "15:15"], "weekdays": list(range(7))}
    return value


@pytest.mark.parametrize("spend,conv,expected", [(1000, 0, False), (1001, 0, True), (1200, 6, False), (1200, 5, True), (999, 1, False)])
def test_threshold_boundaries(spend, conv, expected):
    assert bool(evaluate([row(spend=spend, conversions=conv)], rule())) == expected


def test_meta_filters_then_rollup_and_fractional_conversions():
    rows = [row(spend=700, conversions=1.25), row(ad_id="a2", spend=600, conversions=1.25),
            row(ad_id="a3", adset_name="再行銷", spend=9999, conversions=0)]
    result = evaluate(rows, rule(campaign_filter="台南", adset_filter="新客"))
    assert result[0]["spend"] == 1300
    assert result[0]["conversions"] == 2.5
    assert result[0]["cpa"] == 520


def test_missing_conversion_is_not_zero():
    with pytest.raises(AppError, match="轉換事件"):
        evaluate([row(conversions=None)], rule())


def test_negative_conversion_adjustment_is_not_a_false_alert():
    with pytest.raises(AppError, match="負轉換"):
        evaluate([row(conversions=-1)], rule())


def test_currency_and_account_never_combined():
    grouped = aggregate([row(), row(currency="USD"), row(account_key="other")], rule())
    assert len(grouped) == 3


def test_zero_notify_disabled():
    assert not evaluate([row()], rule(notify_zero=False))


def test_taipei_period_and_delayed_slot():
    # UTC 01:37 = 台北09:37，昨天為11/8。
    now = datetime(2026, 11, 9, 1, 37, tzinfo=timezone.utc)
    assert tuple(map(str, period_until_yesterday(7, now))) == ("2026-11-02", "2026-11-08")
    slot = select_slot(settings()["schedule"], now, [])
    assert slot == "2026-11-09T09:15+08:00"
    assert select_slot(settings()["schedule"], now, [slot]) is None
    assert select_slot(settings()["schedule"], datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc), []) is None


def test_disabled_schedule_and_weekdays():
    value = settings()["schedule"]
    value["enabled"] = False
    assert select_slot(value, datetime.now(TAIPEI), []) is None
    value["enabled"] = True
    value["weekdays"] = [1]
    assert select_slot(value, datetime(2026, 11, 9, 12, tzinfo=TAIPEI), []) is None


def test_validation_rejects_pmax_ad_group_and_invalid_time():
    value = settings()
    value["accounts"] = [account("google")]
    value["rules"] = [rule(account_key="google", level="adset")]
    with pytest.raises(AppError, match="Google"):
        validate_settings(value)
    value["rules"][0]["level"] = "campaign"
    value["schedule"]["times"] = ["09:07"]
    with pytest.raises(AppError, match="15 分鐘"):
        validate_settings(value)


class Response:
    def __init__(self, data=None, status=200, headers=None):
        self.data = data
        self.status_code = status
        self.ok = 200 <= status < 300
        self.headers = headers or {}
        self.content = json.dumps(data).encode() if data is not None else b""

    def json(self):
        return self.data


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, copy.deepcopy(kwargs)))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


def test_meta_pagination_uses_safe_cursor_and_one_conversion_action():
    item = {"date_start": "2026-11-08", "campaign_id": "c1", "ad_id": "a1", "spend": "1200",
            "actions": [{"action_type": "booking", "value": "2"}, {"action_type": "purchase", "value": "99"}]}
    session = Session([Response({"currency": "TWD", "timezone_name": "Asia/Taipei"}),
                       Response({"data": [item], "paging": {"next": "https://evil.example/?access_token=secret", "cursors": {"after": "cursor1"}}}),
                       Response({"data": [{**item, "ad_id": "a2"}]})])
    result = MetaProvider({"META_ACCESS_TOKEN": "secret", "META_API_VERSION": "v26.0"}, session).fetch(
        {**account(), "meta_action_type": "booking"}, "2026-11-08", "2026-11-08")
    assert len(result["rows"]) == 2
    assert sum(r["conversions"] for r in result["rows"]) == 4
    assert session.calls[-1][2]["params"]["after"] == "cursor1"
    assert all("evil.example" not in call[1] for call in session.calls)
    assert all("access_token" not in call[2].get("params", {}) for call in session.calls)


def test_meta_bad_pagination_fails_instead_of_using_partial_data():
    session = Session([Response({"currency": "TWD"}), Response({"data": [], "paging": {"next": "next"}})])
    with pytest.raises(AppError, match="分頁"):
        MetaProvider({"META_ACCESS_TOKEN": "x", "META_API_VERSION": "v26.0"}, session).fetch(account(), "2026-11-08", "2026-11-08")


def test_api_errors_are_not_zero_or_secret_leaks():
    session = Session([requests.RequestException("https://example?access_token=SECRET")])
    with pytest.raises(AppError) as error:
        MetaProvider({"META_ACCESS_TOKEN": "SECRET", "META_API_VERSION": "v26.0"}, session).fetch(account(), "2026-11-08", "2026-11-08")
    assert "SECRET" not in str(error.value)


def google_session():
    return Session([
        Response({"access_token": "access", "expires_in": 3600}),
        Response([{"results": [{"customer": {"currencyCode": "TWD", "timeZone": "Asia/Taipei"}}]}]),
        Response([{"results": [
            {"campaign": {"id": "c1", "name": "搜尋", "advertisingChannelType": "SEARCH"}, "segments": {"date": "2026-11-08"}, "metrics": {"costMicros": "1200000000", "conversions": 100}},
            {"campaign": {"id": "c2", "name": "PMax", "advertisingChannelType": "PERFORMANCE_MAX"}, "segments": {"date": "2026-11-08"}, "metrics": {"costMicros": "500000000"}}]}]),
        Response([{"results": [
            {"campaign": {"id": "c1"}, "segments": {"date": "2026-11-08", "conversionAction": "customers/123/conversionActions/42"}, "metrics": {"allConversions": 2.5, "allConversionsValue": 750}},
            {"campaign": {"id": "c1"}, "segments": {"date": "2026-11-08", "conversionAction": "customers/123/conversionActions/99"}, "metrics": {"allConversions": 99}}]}])])


def test_google_cost_conversion_join_pmax_fractional_and_auth():
    session = google_session()
    provider = GoogleProvider({"GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "secret", "GOOGLE_REFRESH_TOKEN": "refresh", "GOOGLE_LOGIN_CUSTOMER_ID": "123-456-7890"}, session)
    report = provider.fetch(account("google"), "2026-11-08", "2026-11-08")
    assert sum(r["spend"] for r in report["rows"]) == 1700
    assert report["rows"][0]["conversions"] == 2.5
    assert report["rows"][1]["conversions"] == 0
    assert report["rows"][1]["channel"] == "PERFORMANCE_MAX"
    assert "cost_micros" not in session.calls[-1][2]["json"]["query"]
    assert session.calls[-1][2]["headers"]["login-customer-id"] == "1234567890"
    assert "developer-token" not in session.calls[-1][2]["headers"]


def test_google_missing_conversion_not_zero():
    session = google_session()
    provider = GoogleProvider({"GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "s", "GOOGLE_REFRESH_TOKEN": "r"}, session)
    report = provider.fetch({**account("google"), "google_action_ids": []}, "2026-11-08", "2026-11-08")
    assert all(r["conversions"] is None for r in report["rows"])
    assert not report["conversion_ready"]


def test_public_repo_is_refused_before_read_or_write():
    session = Session([Response({"private": False})])
    with pytest.raises(AppError, match="私人"):
        GitHubStore("owner/public", "TOKEN", session=session).write("settings.json", {}, None)
    assert len(session.calls) == 1


def test_state_compare_and_swap_preserves_other_updates():
    session = Session([Response({"private": True}), Response(status=409)])
    with pytest.raises(Conflict):
        GitHubStore("owner/private", "TOKEN", session=session).write("settings.json", {"schedule": {}}, "old-sha")
    assert session.calls[1][2]["json"]["sha"] == "old-sha"


class MemoryStore:
    def __init__(self, value=None):
        self.config = value or settings()
        self.state = {"completed_slots": [], "receipts": {}, "runs": []}
        self.version = 0
        self.lock = None

    def settings(self):
        return copy.deepcopy(self.config), "settings-sha"

    def runtime(self):
        return copy.deepcopy(self.state), str(self.version)

    def write(self, path, value, sha):
        assert path == "runtime.json"
        if sha != str(self.version):
            raise Conflict("conflict")
        self.state = copy.deepcopy(value)
        self.version += 1
        return str(self.version)

    def acquire_lock(self, owner, now=None):
        if self.lock:
            raise AppError("locked")
        self.lock = owner

    def release_lock(self, owner):
        assert self.lock == owner
        self.lock = None


class Provider:
    def fetch(self, *args):
        return {"rows": [row()]}


class Line:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def quota(self):
        return {"limit": 200, "used": 0}

    def push(self, recipient, text, retry_key):
        self.sent.append((recipient, text, retry_key))
        if self.fail:
            raise AppError("結果尚未確認")


CREDS = {"LINE_RECIPIENT_ID": "Utest", "LINE_CHANNEL_ACCESS_TOKEN": "test"}
NOW = datetime(2026, 11, 9, 1, 37, tzinfo=timezone.utc)


def run(store, line, **kwargs):
    return execute(store, CREDS, now=NOW, provider_factory=lambda *args: Provider(), line_factory=lambda token: line, **kwargs)


def test_preview_never_sends_or_completes_live_slot():
    store, line = MemoryStore(), Line()
    result = run(store, line, send=False)
    assert result["status"] == "preview"
    assert not line.sent
    assert not store.state["completed_slots"]


def test_success_slot_and_daily_dedup_across_manual_rechecks():
    store, line = MemoryStore(), Line()
    run(store, line, send=True)
    assert len(line.sent) == 1
    assert len(store.state["completed_slots"]) == 1
    assert run(store, line, send=True)["status"] == "not-due"
    run(store, line, force=True, send=True)
    assert len(line.sent) == 1
    assert not store.lock


def test_unknown_delivery_retry_uses_identical_body_and_key():
    store, line = MemoryStore(), Line(fail=True)
    with pytest.raises(AppError):
        run(store, line, send=True)
    first = line.sent[0]
    assert len(store.state["pending"]) == 1
    assert store.state["runs"][0]["status"] == "failed"
    assert not store.state["receipts"]
    line.fail = False
    run(store, line, send=True)
    assert line.sent[1] == first
    assert len(store.state["receipts"]) == 1
    assert not store.state["pending"]


def test_one_failed_account_does_not_become_zero_or_block_other_rules():
    value = settings()
    value["accounts"].append({**account("google"), "google_action_ids": []})
    value["rules"].append(rule(id="google-rule", account_key="google"))
    store, line = MemoryStore(value), Line()
    result = run(store, line, send=True)
    assert result["status"] == "partial-error"
    assert len(line.sent) == 1
    assert not store.state["completed_slots"]
    run(store, line, send=True)
    assert len(line.sent) == 1


def test_multiple_recipient_routes_are_kept_separate():
    store, line = MemoryStore(), Line()
    store.config["rules"].append(rule(id="rule2", recipient_key="team"))
    execute(store, {**CREDS, "LINE_RECIPIENTS_JSON": '{"team":"Cteam"}'}, now=NOW, send=True,
            provider_factory=lambda *args: Provider(), line_factory=lambda token: line)
    assert {x[0] for x in line.sent} == {"Utest", "Cteam"}


def test_line_409_requires_accepted_request_header():
    line = LineClient("t", Session([Response(status=409, headers={"x-line-accepted-request-id": "accepted"})]))
    assert line.push("Utest", "text", "key") == "already-accepted"
    line = LineClient("t", Session([Response(status=409)]))
    with pytest.raises(AppError):
        line.push("Utest", "text", "key")


def test_batches_respect_line_message_limit():
    candidates = [{"account_name": "a", "rule_name": "r", "entity_name": "很長的活動名稱" * 300,
                   "since": "2026-11-08", "until": "2026-11-08", "spend": 1200, "currency": "TWD",
                   "conversions": 0, "cpa": None, "conversion_label": "booking", "reason": "zero",
                   "fingerprint": str(i)} for i in range(10)]
    batches = build_batches(candidates, "Utest", "slot")
    assert all(len(b["text"]) <= 4500 for b in batches)
    assert sum(len(b["fingerprints"]) for b in batches) == 10
