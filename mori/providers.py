from __future__ import annotations

import json
import re
from datetime import date, timedelta

import requests

from mori.core import AppError, conversion_ready, number


def request_json(session, method, url, **kwargs):
    try:
        response = session.request(method, url, timeout=60, **kwargs)
        data = response.json()
    except (requests.RequestException, ValueError):
        raise AppError("廣告平台連線失敗或回傳格式不正確，資料未被當成零值。") from None
    if not response.ok or (isinstance(data, dict) and data.get("error")):
        # 不回傳 request URL、原始錯誤或 response body，避免把 token 印進網頁或紀錄。
        code = data.get("error", {}).get("code", "") if isinstance(data, dict) and isinstance(data.get("error"), dict) else ""
        raise AppError(f"廣告平台拒絕請求（HTTP {response.status_code}，代碼 {code}）；請檢查授權、帳號與 API 存取。")
    return data


def check_dates(start, end):
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    if end < start or (end - start).days > 1095:
        raise AppError("查詢區間不正確，單次最多三年；實際歷史範圍仍受平台限制。")
    return start.isoformat(), end.isoformat()


def google_id(value):
    value = str(value).replace("-", "").strip()
    if not re.fullmatch(r"\d+", value):
        raise AppError("Google Ads 客戶 ID 必須是數字。")
    return value


class MetaProvider:
    def __init__(self, credentials, session=None):
        self.session = session or requests.Session()
        token, version = credentials.get("META_ACCESS_TOKEN"), credentials.get("META_API_VERSION", "")
        if not token:
            raise AppError("尚未設定 META_ACCESS_TOKEN。")
        if not re.fullmatch(r"v\d+\.0", version):
            raise AppError("請在 Secrets 指定仍受支援的 META_API_VERSION，例如 v26.0；不沿用舊程式的 v19.0。")
        self.root = f"https://graph.facebook.com/{version}"
        self.headers = {"Authorization": f"Bearer {token}"}

    def _get(self, path, params):
        return request_json(self.session, "GET", f"{self.root}/{path}", headers=self.headers, params=params)

    def fetch(self, account, start, end):
        start, end = check_dates(start, end)
        account_id = "act_" + str(account["account_id"]).removeprefix("act_")
        if not re.fullmatch(r"act_\d+", account_id):
            raise AppError("Meta 帳號 ID 不正確。")
        info = self._get(account_id, {"fields": "name,currency,timezone_name"})
        currency = info.get("currency")
        if not currency:
            raise AppError("Meta 未回傳帳號幣別，已停止加總。")
        params = {"level": "ad", "fields": "date_start,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,impressions,inline_link_clicks,actions,action_values",
                  "time_range": json.dumps({"since": start, "until": end}), "time_increment": 1,
                  "use_unified_attribution_setting": "true", "action_report_time": "impression", "limit": 500}
        rows, seen_cursors = [], set()
        action = account.get("meta_action_type", "").strip()
        while True:
            data = self._get(f"{account_id}/insights", params)
            for item in data.get("data", []):
                actions = {x["action_type"]: number(x.get("value")) for x in item.get("actions", [])}
                values = {x["action_type"]: number(x.get("value")) for x in item.get("action_values", [])}
                rows.append({"account_key": account["key"], "platform": "meta", "date": item["date_start"],
                             "campaign_id": item.get("campaign_id"), "campaign_name": item.get("campaign_name", ""),
                             "adset_id": item.get("adset_id"), "adset_name": item.get("adset_name", ""),
                             "ad_id": item.get("ad_id"), "ad_name": item.get("ad_name", ""), "channel": "META",
                             "currency": currency, "spend": number(item.get("spend")),
                             "impressions": number(item.get("impressions")), "clicks": number(item.get("inline_link_clicks")),
                             "conversions": actions.get(action, 0.0) if action else None,
                             "conversion_value": values.get(action, 0.0) if action else None,
                             "available_actions": sorted(actions)})
            paging = data.get("paging", {})
            if not paging.get("next"):
                break
            cursor = paging.get("cursors", {}).get("after")
            if not cursor or cursor in seen_cursors:
                raise AppError("Meta 分頁游標異常，未使用不完整數據。")
            seen_cursors.add(cursor)
            # 不跟隨含權杖的 next URL；只在同一官方 endpoint 更新 cursor。
            params["after"] = cursor
        return {"rows": rows, "currency": currency, "timezone": info.get("timezone_name", "未提供"),
                "account_name": info.get("name", account["name"]), "conversion_ready": conversion_ready(account)}


class GoogleProvider:
    def __init__(self, credentials, session=None):
        self.credentials = credentials
        self.session = session or requests.Session()
        for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
            if not credentials.get(key):
                raise AppError(f"尚未設定 {key}。")
        version = credentials.get("GOOGLE_API_VERSION") or "v26"
        if not re.fullmatch(r"v\d+", version):
            raise AppError("GOOGLE_API_VERSION 格式不正確。")
        self.root = f"https://googleads.googleapis.com/{version}"
        self._access_token = None

    def headers(self):
        if self._access_token is None:
            data = request_json(self.session, "POST", "https://oauth2.googleapis.com/token", data={
                "grant_type": "refresh_token", "client_id": self.credentials["GOOGLE_CLIENT_ID"],
                "client_secret": self.credentials["GOOGLE_CLIENT_SECRET"], "refresh_token": self.credentials["GOOGLE_REFRESH_TOKEN"]})
            self._access_token = data.get("access_token")
            if not self._access_token:
                raise AppError("Google 未回傳 access token，請重新授權。")
        headers = {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}
        if self.credentials.get("GOOGLE_LOGIN_CUSTOMER_ID"):
            headers["login-customer-id"] = google_id(self.credentials["GOOGLE_LOGIN_CUSTOMER_ID"])
        # 2026-09 後存取由 Google Cloud 專案管理；舊 token 可選，不作必要條件。
        if self.credentials.get("GOOGLE_DEVELOPER_TOKEN"):
            headers["developer-token"] = self.credentials["GOOGLE_DEVELOPER_TOKEN"]
        return headers

    def query(self, account, query):
        customer_id = google_id(account["account_id"])
        data = request_json(self.session, "POST", f"{self.root}/customers/{customer_id}/googleAds:searchStream",
                            headers=self.headers(), json={"query": query})
        if isinstance(data, dict):
            data = [data]
        return [row for batch in data for row in batch.get("results", [])]

    def conversion_actions(self, account):
        rows = self.query(account, "SELECT conversion_action.id, conversion_action.name, conversion_action.status, conversion_action.primary_for_goal FROM conversion_action WHERE conversion_action.status != 'REMOVED'")
        return [{"id": str(x["conversionAction"]["id"]), "name": x["conversionAction"].get("name", ""),
                 "primary": x["conversionAction"].get("primaryForGoal", False)} for x in rows]

    def fetch(self, account, start, end):
        start, end = check_dates(start, end)
        infos = self.query(account, "SELECT customer.currency_code, customer.time_zone, customer.descriptive_name FROM customer LIMIT 1")
        if not infos or not infos[0].get("customer", {}).get("currencyCode"):
            raise AppError("Google 未回傳帳號幣別，已停止加總。")
        info = infos[0]["customer"]
        selected = account.get("google_conversion_mode", "selected") == "selected"
        where = f"segments.date BETWEEN '{start}' AND '{end}'"
        # 先查成本，不能將 cost 跟 conversion_action 分段查詢混在一起，避免漏成本或重複加總。
        raw = self.query(account, "SELECT campaign.id, campaign.name, campaign.advertising_channel_type, segments.date, metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions, metrics.conversions_value FROM campaign WHERE " + where)
        conversion_map = {}
        ids = account.get("google_action_ids", [])
        if selected and ids:
            if any(not str(x).isdigit() for x in ids):
                raise AppError("Google 轉換動作 ID 不正確。")
            conversions = self.query(account, "SELECT campaign.id, segments.date, segments.conversion_action, metrics.all_conversions, metrics.all_conversions_value FROM campaign WHERE " + where)
            for row in conversions:
                if row["segments"]["conversionAction"].split("/")[-1] not in ids:
                    continue
                key = (str(row["campaign"]["id"]), row["segments"]["date"])
                total, value = conversion_map.get(key, (0.0, 0.0))
                conversion_map[key] = (total + number(row.get("metrics", {}).get("allConversions")),
                                       value + number(row.get("metrics", {}).get("allConversionsValue")))
        rows = []
        for row in raw:
            campaign, metrics = row["campaign"], row.get("metrics", {})
            key = (str(campaign["id"]), row["segments"]["date"])
            if selected:
                total, value = conversion_map.get(key, (0.0, 0.0)) if ids else (None, None)
            else:
                total, value = number(metrics.get("conversions")), number(metrics.get("conversionsValue"))
            rows.append({"account_key": account["key"], "platform": "google", "date": key[1],
                         "campaign_id": key[0], "campaign_name": campaign.get("name", ""),
                         "adset_id": "", "adset_name": "", "ad_id": "", "ad_name": "",
                         "channel": campaign.get("advertisingChannelType", "UNKNOWN"), "currency": info["currencyCode"],
                         "spend": number(metrics.get("costMicros")) / 1_000_000,
                         "impressions": number(metrics.get("impressions")), "clicks": number(metrics.get("clicks")),
                         "conversions": total, "conversion_value": value})
        return {"rows": rows, "currency": info["currencyCode"], "timezone": info.get("timeZone", "未提供"),
                "account_name": info.get("descriptiveName", account["name"]), "conversion_ready": conversion_ready(account)}


def provider_for(account, credentials, session=None):
    if account["platform"] == "meta":
        return MetaProvider(credentials, session)
    if account["platform"] == "google":
        return GoogleProvider(credentials, session)
    raise AppError("不支援的廣告平台。")
