from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
LEVELS = {"campaign": "行銷活動", "adset": "廣告組合", "ad": "廣告"}


class AppError(Exception):
    """可直接向使用者顯示、不包含憑證的錯誤。"""


def default_settings():
    return {"schema_version": 1, "accounts": [], "projects": [], "rules": [],
            "schedule": {"enabled": False, "times": ["09:15"], "weekdays": list(range(7))}}


def number(value, default=0.0):
    result = float(default if value is None else value)
    if not math.isfinite(result):
        raise AppError("數值必須是有限數字。")
    return result


def validate_settings(data):
    data = copy.deepcopy(data)
    if data.get("schema_version") != 1:
        raise AppError("設定格式版本不支援，請先匯出備份。")
    account_ids, rule_ids, project_ids = set(), set(), set()
    for account in data.get("accounts", []):
        key = account.get("key", "")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,50}", key) or key in account_ids:
            raise AppError("帳號代號必須唯一，且只能包含英文、數字、底線或連字號。")
        account_ids.add(key)
        if account.get("platform") not in ("meta", "google"):
            raise AppError("不支援的廣告平台。")
        if not re.fullmatch(r"(?:act_)?[0-9]+", str(account.get("account_id", ""))):
            raise AppError("廣告帳號 ID 格式不正確，Google 請移除連字號。")
        if account.get("google_conversion_mode", "selected") not in ("selected", "primary"):
            raise AppError("Google 轉換口徑不正確。")
        if any(not str(x).isdigit() for x in account.get("google_action_ids", [])):
            raise AppError("Google 轉換動作 ID 必須是數字。")
    for project in data.get("projects", []):
        if not project.get("id") or project["id"] in project_ids or not project.get("name"):
            raise AppError("專案名稱不可空白，專案代號不可重複。")
        project_ids.add(project["id"])
        if project.get("account_key") not in account_ids:
            raise AppError("每個專案必須指定廣告帳號。")
        if number(project.get("budget", 0)) < 0:
            raise AppError("專案預算不可小於零。")
        if project.get("status") not in ("進行中", "已結案"):
            raise AppError("專案狀態不正確。")
        start, end = date.fromisoformat(project["start"]), date.fromisoformat(project["end"])
        if end < start:
            raise AppError("專案結束日不可早於開始日。")
        if not project.get("keyword", "").strip():
            raise AppError("請填專案名稱篩選字，避免把全帳號誤算為單一專案。")
        match_field = project.get("match_field", "campaign_name")
        if match_field not in ("campaign_name", "adset_name", "ad_name"):
            raise AppError("專案名稱歸類欄位不正確。")
        account = next(a for a in data["accounts"] if a["key"] == project["account_key"])
        if account["platform"] == "google" and match_field != "campaign_name":
            raise AppError("Google 專案首版請用行銷活動名稱歸類，才能完整涵蓋 PMax。")
    for rule in data.get("rules", []):
        if not rule.get("id") or rule["id"] in rule_ids or not rule.get("name"):
            raise AppError("規則名稱不可空白，規則代號不可重複。")
        rule_ids.add(rule["id"])
        if rule.get("account_key") not in account_ids:
            raise AppError("規則指定的廣告帳號不存在。")
        if rule.get("level") not in LEVELS:
            raise AppError("異常判斷層級不正確。")
        account = next(a for a in data["accounts"] if a["key"] == rule["account_key"])
        if account["platform"] == "google" and rule["level"] != "campaign":
            raise AppError("Google 第一版以行銷活動判斷，完整涵蓋搜尋與 PMax。")
        if account["platform"] == "google" and (rule.get("adset_filter") or rule.get("ad_filter")):
            raise AppError("Google 第一版僅支援行銷活動名稱篩選。")
        if not 1 <= int(rule.get("period_days", 1)) <= 30:
            raise AppError("異常判斷期間必須在 1 至 30 天。")
        if min(number(rule.get("minimum_spend")), number(rule.get("cpa_threshold"))) < 0:
            raise AppError("花費與 CPA 門檻不可小於零。")
        if rule.get("starts_on"):
            date.fromisoformat(rule["starts_on"])
        if rule.get("ends_on"):
            date.fromisoformat(rule["ends_on"])
        if rule.get("starts_on") and rule.get("ends_on") and rule["ends_on"] < rule["starts_on"]:
            raise AppError("規則結束日不可早於開始日。")
    schedule = data.get("schedule", {})
    times = schedule.get("times", [])
    if not times or len(times) > 4 or len(set(times)) != len(times):
        raise AppError("每天可安排 1 至 4 個不同的通知時段。")
    for value in times:
        if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):(?:00|15|30|45)", value):
            raise AppError("通知時間請使用 15 分鐘間隔，例如 09:15。")
    weekdays = schedule.get("weekdays", [])
    if not weekdays or any(type(d) is not int or d not in range(7) for d in weekdays):
        raise AppError("至少選擇一個有效的星期。")
    return data


def conversion_ready(account):
    if account["platform"] == "meta":
        return bool(account.get("meta_action_type", "").strip())
    return (account.get("google_conversion_mode") == "primary"
            or bool(account.get("google_action_ids")))


def period_until_yesterday(days, now=None):
    now = now or datetime.now(TAIPEI)
    end = now.astimezone(TAIPEI).date() - timedelta(days=1)
    return end - timedelta(days=days - 1), end


def select_slot(schedule, now, completed):
    """每 15 分鐘喚醒；同日補跑最近一個到期時段，避免網頁休眠和排程延遲漏掉。"""
    local = now.astimezone(TAIPEI)
    if not schedule.get("enabled") or local.weekday() not in schedule["weekdays"]:
        return None
    due = [t for t in schedule["times"] if t <= local.strftime("%H:%M")]
    if not due:
        return None
    slot = f"{local.date().isoformat()}T{max(due)}+08:00"
    return None if slot in completed else slot


def contains(text, value):
    return not value.strip() or value.strip().casefold() in str(text).casefold()


def aggregate(rows, rule):
    groups = {}
    level = rule["level"]
    for row in rows:
        if not all(contains(row.get(field, ""), rule.get(filt, "")) for field, filt in
                   [("campaign_name", "campaign_filter"), ("adset_name", "adset_filter"),
                    ("ad_name", "ad_filter")]):
            continue
        if rule.get("channel", "ALL") != "ALL" and row.get("channel") != rule["channel"]:
            continue
        entity_id = row.get(f"{level}_id")
        if not entity_id:
            raise AppError("資料缺少判斷層級 ID，已停止該規則以免誤判。")
        key = (row["account_key"], str(entity_id), row["currency"])
        if key not in groups:
            groups[key] = {"entity_id": str(entity_id),
                           "entity_name": row.get(f"{level}_name", str(entity_id)),
                           "currency": row["currency"], "spend": 0.0,
                           "conversions": 0.0, "impressions": 0.0, "clicks": 0.0}
        item = groups[key]
        for metric in ("spend", "impressions", "clicks"):
            item[metric] += number(row.get(metric))
        if row.get("conversions") is None:
            item["conversions"] = None
        elif item["conversions"] is not None:
            item["conversions"] += number(row["conversions"])
    for item in groups.values():
        item["cpa"] = item["spend"] / item["conversions"] if item["conversions"] else None
    return list(groups.values())


def evaluate(rows, rule):
    anomalies = []
    for item in aggregate(rows, rule):
        if item["conversions"] is None:
            raise AppError("尚未設定轉換事件，不能判斷零轉換或 CPA。")
        if item["conversions"] < 0:
            raise AppError("出現負轉換調整，請人工確認，暫不進行 CPA 警報。")
        if item["spend"] <= number(rule["minimum_spend"]):
            continue
        if item["conversions"] == 0 and rule.get("notify_zero", True):
            anomalies.append({**item, "reason": "花費超過門檻且零轉換"})
        elif item["cpa"] is not None and item["cpa"] > number(rule["cpa_threshold"]):
            anomalies.append({**item, "reason": "花費與 CPA 均超過門檻"})
    return anomalies


def fingerprint(rule, entity_id, until, recipient):
    # 相同規則/轉換口徑在同一資料日只提醒一次；改名不重發。
    payload = [rule["id"], rule["account_key"], rule["level"], entity_id, str(until), recipient]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
