from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import requests

from mori.core import AppError, TAIPEI, conversion_ready, number


def request_json(session, method, url, **kwargs):
    try:
        response = session.request(method, url, timeout=60, **kwargs)
        data = response.json()
    except (requests.RequestException, ValueError):
        raise AppError("廣告平台連線失敗或回傳格式不正確，資料未被當成零值。") from None
    if not response.ok or (isinstance(data, dict) and data.get("error")):
        # 不回傳 request URL、原始錯誤或 response body，避免把 token 印進網頁或紀錄。
        code = data.get("error", {}).get("code", "") if isinstance(data, dict) and isinstance(data.get("error"), dict) else ""
        if 'graph.facebook.com' in url and str(code) in ('4', '17'):
            raise AppError(f"Meta API 請求量已達限制（代碼 {code}）；請稍後再按「重新讀取」。這不是權杖失效訊息。")
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


DEFAULT_META_API_VERSION = "v26.0"


class MetaProvider:
    def __init__(self, credentials, session=None):
        self.session = session or requests.Session()
        token, version = credentials.get("META_ACCESS_TOKEN"), (credentials.get("META_API_VERSION") or DEFAULT_META_API_VERSION)
        if not token:
            raise AppError("尚未設定 META_ACCESS_TOKEN。")
        if not re.fullmatch(r"v\d+\.0", version):
            raise AppError("Meta API 版本格式不正確，請聯繫系統管理員檢查進階設定。")
        self.root = f"https://graph.facebook.com/{version}"
        self.headers = {"Authorization": f"Bearer {token}"}

    def _get(self, path, params):
        return request_json(self.session, "GET", f"{self.root}/{path}", headers=self.headers, params=params)

    def fetch(self, account, start, end):
        return self._fetch(account, start, end, budget=False)

    def fetch_budget(self, account, start, end):
        """Read each ad's whole-period cost, rather than adding daily costs."""
        return self._fetch(account, start, end, budget=True)

    def _fetch(self, account, start, end, budget):
        start, end = check_dates(start, end)
        account_id = "act_" + str(account["account_id"]).removeprefix("act_")
        if not re.fullmatch(r"act_\d+", account_id):
            raise AppError("Meta 帳號 ID 不正確。")
        info = self._get(account_id, {"fields": "name,currency,timezone_name"})
        currency = info.get("currency")
        if not currency:
            raise AppError("Meta 未回傳帳號幣別，已停止加總。")
        params = {"level": "ad", "fields": "date_start,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,impressions,inline_link_clicks,actions,action_values",
                  "time_range": json.dumps({"since": start, "until": end}), "time_increment": "all_days" if budget else 1,
                  "use_unified_attribution_setting": "true", "action_report_time": "impression", "limit": 500}
        if budget:
            params['fields'] = 'date_start,date_stop,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend'
        rows, seen_cursors = [], set()
        seen_ads = set()
        action = account.get("meta_action_type", "").strip()
        while True:
            data = self._get(f"{account_id}/insights", params)
            for item in data.get("data", []):
                if budget:
                    ad_id = item.get('ad_id')
                    if not ad_id or ad_id in seen_ads:
                        raise AppError('Meta 整段花費缺少廣告 ID 或重複回傳，已停止加總。')
                    seen_ads.add(ad_id)
                    if item.get('date_start') != start or item.get('date_stop') != end:
                        raise AppError('Meta 回傳走期與查詢區間不同，已停止加總。')
                    try:
                        cost = Decimal(str(item['spend']))
                    except (KeyError, InvalidOperation, ValueError):
                        raise AppError('Meta 未回傳有效花費，未當成零值。') from None
                    if not cost.is_finite() or cost < 0:
                        raise AppError('Meta 回傳非有效或負數花費，已停止加總。')
                actions = {x["action_type"]: number(x.get("value")) for x in item.get("actions", [])}
                values = {x["action_type"]: number(x.get("value")) for x in item.get("action_values", [])}
                rows.append({"account_key": account["key"], "platform": "meta", "date": item["date_start"],
                             "campaign_id": item.get("campaign_id"), "campaign_name": item.get("campaign_name", ""),
                             "adset_id": item.get("adset_id"), "adset_name": item.get("adset_name", ""),
                             "ad_id": item.get("ad_id"), "ad_name": item.get("ad_name", ""), "channel": "META",
                             "currency": currency, "spend": number(item.get("spend")),
                             "impressions": number(item.get("impressions")), "clicks": number(item.get("inline_link_clicks")),
                             "conversions": actions.get(action, 0.0) if action and not budget else None,
                             "conversion_value": values.get(action, 0.0) if action and not budget else None,
                             "available_actions": sorted(actions)})
                if budget:
                    rows[-1].update(spend_raw=str(item['spend']), date_stop=end,
                                    attribution_unit='每則廣告／整段走期')
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
                "account_name": info.get("name", account["name"]), "conversion_ready": conversion_ready(account) if not budget else False,
                "spend_basis": "meta_ad_whole_period" if budget else "daily"}


DEFAULT_GOOGLE_API_VERSION = "v26"


class GoogleProvider:
    def __init__(self, credentials, session=None):
        self.credentials = credentials
        self.session = session or requests.Session()
        for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
            if not credentials.get(key):
                raise AppError(f"尚未設定 {key}。")
        version = credentials.get("GOOGLE_API_VERSION") or DEFAULT_GOOGLE_API_VERSION
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
        # API access is managed by the OAuth client's Google Cloud project.
        # Developer tokens were sunset; do not send legacy credentials.
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

    def fetch_budget(self, account, start, end):
        """Non-PMax ad/day and PMax asset-group/day cost, joined to current copy."""
        from mori.google_creatives import normalize, query_fields, reconcile
        start, end = check_dates(start, end)
        report = self.fetch(account, start, end)
        campaign_rows = report['rows']
        rows = []
        where = f"segments.date BETWEEN '{start}' AND '{end}'"
        common = ['campaign.id', 'campaign.name', 'campaign.advertising_channel_type',
                  'segments.date', 'metrics.cost_micros', 'metrics.impressions', 'metrics.clicks']

        def cost_row(item):
            campaign, metrics = item['campaign'], item.get('metrics', {})
            return {'account_key': account['key'], 'platform': 'google',
                    'date': item['segments']['date'], 'campaign_id': str(campaign['id']),
                    'campaign_name': campaign.get('name', ''),
                    'channel': campaign.get('advertisingChannelType', 'UNKNOWN'),
                    'currency': report['currency'], 'spend': number(metrics.get('costMicros')) / 1_000_000,
                    'impressions': number(metrics.get('impressions')), 'clicks': number(metrics.get('clicks')),
                    'conversions': None, 'conversion_value': None}

        if any(r['channel'] != 'PERFORMANCE_MAX' for r in campaign_rows):
            fields = common + ['ad_group.id', 'ad_group.name', 'ad_group_ad.ad.id', 'ad_group_ad.ad.type'] + query_fields()
            query = ('SELECT ' + ', '.join(fields) + ' FROM ad_group_ad WHERE ' + where +
                     " AND campaign.advertising_channel_type != 'PERFORMANCE_MAX'")
            for item in self.query(account, query):
                group, ad = item.get('adGroup', {}), item['adGroupAd']['ad']
                rows.append({**cost_row(item), **normalize(ad),
                             'adset_id': str(group.get('id', '')), 'adset_name': group.get('name', ''),
                             'ad_id': str(ad['id']), 'ad_name': 'ID ' + str(ad['id']),
                             'ad_type': ad.get('type', 'UNKNOWN'), 'attribution_unit': '廣告',
                             'asset_group_id': '', 'asset_group_name': ''})

        if any(r['channel'] == 'PERFORMANCE_MAX' for r in campaign_rows):
            # Read text independently of metrics. Multiple matching assets must never
            # multiply the daily cost of an asset group.
            assets = self.query(account,
                "SELECT asset_group.id, asset_group_asset.field_type, asset.text_asset.text "
                "FROM asset_group_asset WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX' "
                "AND asset_group_asset.status != 'REMOVED' "
                "AND asset_group_asset.field_type IN ('HEADLINE', 'LONG_HEADLINE', 'DESCRIPTION', 'LONG_DESCRIPTION')")
            copy = {}
            for item in assets:
                group_id = str(item['assetGroup']['id'])
                text = item.get('asset', {}).get('textAsset', {}).get('text')
                if not text:
                    continue
                role = item['assetGroupAsset'].get('fieldType')
                key = 'headlines' if role in ('HEADLINE', 'LONG_HEADLINE') else 'descriptions'
                copy.setdefault(group_id, {'headlines': [], 'descriptions': []})[key].append(text)
            fields = common + ['asset_group.id', 'asset_group.name', 'asset_group.path1', 'asset_group.path2']
            query = ('SELECT ' + ', '.join(fields) + ' FROM asset_group WHERE ' + where +
                     " AND campaign.advertising_channel_type = 'PERFORMANCE_MAX'")
            for item in self.query(account, query):
                group = item['assetGroup']
                group_id = str(group['id'])
                texts = copy.get(group_id, {'headlines': [], 'descriptions': []})
                rows.append({**cost_row(item),
                             'adset_id': '', 'adset_name': '', 'ad_id': '', 'ad_name': '',
                             'asset_group_id': group_id, 'asset_group_name': group.get('name', ''),
                             'ad_type': 'PERFORMANCE_MAX', 'attribution_unit': '素材群組',
                             'headlines': sorted(set(texts['headlines'])),
                             'descriptions': sorted(set(texts['descriptions'])),
                             'paths': [p for p in [group.get('path1'), group.get('path2')] if p],
                             'available_fields': ['headlines', 'descriptions', 'paths']})
        report['warnings'] = reconcile(campaign_rows, rows, live_date=datetime.now(TAIPEI).date())
        report['rows'] = rows
        report['attribution_detail'] = True
        return report


def provider_for(account, credentials, session=None):
    if account["platform"] == "meta":
        return MetaProvider(credentials, session)
    if account["platform"] == "google":
        return GoogleProvider(credentials, session)
    raise AppError("不支援的廣告平台。")
