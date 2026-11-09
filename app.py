from __future__ import annotations

import copy
import hashlib
import hmac
import io
import json
import os
import uuid
from datetime import date, datetime, timedelta

import pandas as pd
import requests
import streamlit as st

from mori.core import (AppError, LEVELS, TAIPEI, conversion_ready, default_settings,
                       validate_settings)
from mori.providers import GoogleProvider, provider_for
from mori.runner import check_rules, conversion_label
from mori.storage import GitHubStore

st.set_page_config(page_title="森森廣告數據與異常提醒", page_icon="🌿", layout="wide")
st.markdown("""<style>
html,body,[class*="css"],h1,h2,h3,p,button{font-family:"Microsoft JhengHei","微軟正黑體",sans-serif;}
[data-testid="stMetric"]{background:#edf4ef;padding:18px;border-radius:12px;border-left:4px solid #174d38;}
</style>""", unsafe_allow_html=True)


def secret(key, default=""):
    try:
        return st.secrets.get(key, os.environ.get(key, default))
    except FileNotFoundError:
        return os.environ.get(key, default)


def credentials():
    names = ["META_ACCESS_TOKEN", "META_API_VERSION", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
             "GOOGLE_REFRESH_TOKEN", "GOOGLE_LOGIN_CUSTOMER_ID", "GOOGLE_API_VERSION",
             "GOOGLE_DEVELOPER_TOKEN", "LINE_CHANNEL_ACCESS_TOKEN", "LINE_RECIPIENT_ID", "LINE_RECIPIENTS_JSON"]
    result = {key: str(secret(key)) for key in names}
    result["META_ACCESS_TOKEN"] = result["META_ACCESS_TOKEN"] or str(secret("meta_access_token"))
    return result


def demo_settings():
    settings = default_settings()
    settings["accounts"] = [{"key": "demo_meta", "name": "示範 Meta 帳號", "platform": "meta", "account_id": "123456", "meta_action_type": "示範訂位事件"},
                            {"key": "demo_google", "name": "示範 Google 帳號", "platform": "google", "account_id": "1234567890", "google_conversion_mode": "selected", "google_action_ids": ["123"]}]
    settings["rules"] = [{"id": "demo-rule", "name": "示範 CPA 提醒", "account_key": "demo_meta", "enabled": True,
                          "level": "campaign", "period_days": 1, "minimum_spend": 1000.0, "cpa_threshold": 200.0,
                          "notify_zero": True, "campaign_filter": "", "adset_filter": "", "ad_filter": "", "channel": "ALL"}]
    return settings


def demo_reports(start, end):
    # 僅用於標示清楚的示範預覽，絕不作為真實 API 失敗的替代資料。
    rows = []
    current = start
    while current <= end:
        for platform, channel, name, spend, conv in [
            ("meta", "META", "示範｜門店訂位", 1200.0, 4.0),
            ("google", "SEARCH", "示範｜品牌搜尋", 600.0, 6.0),
            ("google", "PERFORMANCE_MAX", "示範｜PMax", 900.0, 3.5)]:
            rows.append({"account_key": "demo_" + platform, "platform": platform, "date": str(current),
                         "campaign_id": platform + channel, "campaign_name": name, "adset_id": "set1", "adset_name": "示範組合",
                         "ad_id": "ad1", "ad_name": "示範廣告", "channel": channel, "currency": "TWD",
                         "spend": spend, "impressions": 20000.0, "clicks": 200.0, "conversions": conv, "conversion_value": 0.0})
        current += timedelta(days=1)
    return [{"rows": [r for r in rows if r["platform"] == p], "currency": "TWD", "timezone": "Asia/Taipei", "conversion_ready": True} for p in ("meta", "google")]


demo = str(secret("DEMO_MODE", "false")).lower() == "true"
if demo:
    st.warning("示範模式｜以下為人工建立的示例，未串接真實廣告帳號、不儲存設定、不發送 LINE。")
else:
    password = str(secret("APP_PASSWORD"))
    if len(password) < 10 or password == "CHANGE_TO_A_LONG_RANDOM_PASSWORD":
        st.title("森森廣告數據與異常提醒")
        st.info("請先在 Streamlit Secrets 設定至少 10 個字元的 APP_PASSWORD、STATE_REPO 與 STATE_TOKEN，再開放真實數據。設定方式見 README。")
        st.stop()
    if not st.session_state.get("authenticated"):
        st.title("森森廣告管理登入")
        with st.form("login"):
            entered = st.text_input("管理密碼", type="password")
            login = st.form_submit_button("登入")
        if login:
            if hmac.compare_digest(entered.encode(), password.encode()):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("密碼不正確。")
        st.stop()

store = None
settings_sha = None
if demo:
    settings = st.session_state.get("demo_settings", demo_settings())
    runtime = {"runs": [], "pending": []}
else:
    try:
        store = GitHubStore(str(secret("STATE_REPO")), str(secret("STATE_TOKEN")), str(secret("STATE_BRANCH", "main")))
        settings, settings_sha = store.settings()
        settings = validate_settings(settings)
        runtime, _ = store.runtime()
    except (AppError, ValueError) as exc:
        st.error(str(exc))
        st.stop()


def save_settings(updated):
    try:
        validated = validate_settings(updated)
        if demo:
            st.session_state.demo_settings = validated
        else:
            store.write("settings.json", validated, settings_sha)
        st.session_state.pop("report_view", None)
        st.session_state.save_notice = "設定已儲存。" if not demo else "示範設定已更新，僅保留在這次預覽。"
        st.rerun()
    except (AppError, ValueError, TypeError):
        st.error("儲存失敗：請確認欄位完整、日期與金額正確；若有其他人更新設定，請重新整理頁面後再試。")


st.sidebar.title("🌿 森森廣告管理")
page = st.sidebar.radio("功能", ["數據總覽", "專案預算", "異常規則", "通知排程", "執行紀錄", "帳號與串接"])
st.sidebar.caption("台灣時間 " + datetime.now(TAIPEI).strftime("%Y/%m/%d %H:%M"))
logo = st.sidebar.file_uploader("品牌 Logo（此次瀏覽使用）", type=["png", "jpg", "jpeg"])
if logo:
    st.sidebar.image(logo, width=180)
if not demo and st.sidebar.button("登出"):
    st.session_state.clear()
    st.rerun()
st.title(page)
st.caption("廣告數據、預算與 LINE 異常提醒集中管理")
if st.session_state.get("save_notice"):
    st.success(st.session_state.pop("save_notice"))

account_by_key = {a["key"]: a for a in settings["accounts"]}
names = {a["key"]: a["name"] for a in settings["accounts"]}
creds = credentials() if not demo else {}


def fetch_report(account, start, end):
    return provider_for(account, creds).fetch(account, start, end)


def reports_table(reports):
    rows = [row for report in reports for row in report["rows"]]
    return pd.DataFrame(rows)


if page == "數據總覽":
    if not settings["accounts"]:
        st.info("先到「帳號與串接」新增 Meta 或 Google Ads 帳號。")
    else:
        keys = st.multiselect("廣告帳號", list(names), default=list(names), format_func=names.get)
        today = datetime.now(TAIPEI).date()
        period = st.date_input("查詢區間（依各廣告帳號時區）", (today - timedelta(days=7), today - timedelta(days=1)), max_value=today)
        if st.button("讀取數據", type="primary"):
            if len(period) != 2 or not keys:
                st.error("請選擇完整日期與至少一個帳號。")
            else:
                reports, errors = [], []
                with st.spinner("讀取廣告數據…"):
                    if demo:
                        reports = [r for r in demo_reports(*period) if r["rows"][0]["account_key"] in keys]
                    else:
                        for key in keys:
                            try:
                                report = fetch_report(account_by_key[key], *period)
                                reports.append(report)
                            except AppError as exc:
                                errors.append(f"{names[key]}：{exc}")
                st.session_state.report_view = {"reports": reports, "errors": errors, "keys": keys, "period": tuple(map(str, period)), "at": datetime.now(TAIPEI).isoformat()}
        view = st.session_state.get("report_view")
        if view:
            if tuple(map(str, period)) != view["period"] or keys != view["keys"]:
                st.info("篩選已變更，按「讀取數據」更新；下方仍是上次查詢結果。")
            st.caption(f"資料區間：{' ～ '.join(view['period'])}｜讀取時間：{view['at']}")
            for error in view["errors"]:
                st.error(error)
            for report in view["reports"]:
                st.caption(f"帳號時區：{report.get('timezone')}｜幣別：{report['currency']}")
            df = reports_table(view["reports"])
            if df.empty:
                st.info("成功回傳的帳號在此期間沒有資料；讀取失敗的帳號不列入零值。")
            else:
                channels = st.multiselect("廣告類型", sorted(df.channel.unique()), default=sorted(df.channel.unique()))
                shown = df[df.channel.isin(channels)].copy()
                for currency in shown.currency.unique():
                    part = shown[shown.currency == currency]
                    st.subheader(currency)
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("廣告後台花費", f"{part.spend.sum():,.2f}")
                    c2.metric("曝光", f"{part.impressions.sum():,.0f}")
                    c3.metric("點擊／Meta 連結點擊", f"{part.clicks.sum():,.0f}")
                    # 平台歸因、轉換定義不同，不把雙平台轉換數當作去重的實際訂位。
                    c4.metric("回傳資料列", f"{len(part):,}")
                    trend = part.groupby(["date", "platform"])["spend"].sum().unstack(fill_value=0)
                    st.line_chart(trend)
                summary_rows = []
                for (key, campaign_id, campaign, currency), part in shown.groupby(["account_key", "campaign_id", "campaign_name", "currency"], dropna=False):
                    complete = part.conversions.notna().all()
                    conversions = part.conversions.sum() if complete else None
                    summary_rows.append({"帳號": names.get(key, key), "活動 ID": campaign_id, "活動": campaign, "幣別": currency,
                                         "花費": part.spend.sum(), "轉換": conversions,
                                         "CPA": part.spend.sum() / conversions if conversions else None,
                                         "曝光": part.impressions.sum(), "點擊": part.clicks.sum(),
                                         "CTR %": 100 * part.clicks.sum() / part.impressions.sum() if part.impressions.sum() else None,
                                         "CPC": part.spend.sum() / part.clicks.sum() if part.clicks.sum() else None})
                summary_df = pd.DataFrame(summary_rows)
                st.dataframe(summary_df, hide_index=True, use_container_width=True)
                for key in view["keys"]:
                    if key in account_by_key:
                        st.caption(f"{names[key]} 轉換口徑：{conversion_label(account_by_key[key])}")
                st.caption("花費為平台回傳的帳號幣別金額，未另外加計代理商服務費與稅；不等於儲值餘額。平台歸因轉換不等於實際到店，跨平台轉換不去重。")
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    summary_df.to_excel(writer, index=False, sheet_name="活動總覽")
                    shown.drop(columns=["available_actions"], errors="ignore").to_excel(writer, index=False, sheet_name="每日明細")
                st.download_button("下載 Excel 報表", buffer.getvalue(), "mori-ad-report.xlsx")

elif page == "帳號與串接":
    st.write("先儲存帳號，再查詢平台實際回傳的轉換事件。所有權杖只放 Secrets。")
    if names:
        st.dataframe(pd.DataFrame([{"名稱": a["name"], "平台": a["platform"], "帳號": a["account_id"], "轉換口徑": conversion_label(a)} for a in settings["accounts"]]), hide_index=True)
    choice = st.selectbox("新增或修改帳號", ["新增帳號"] + list(names), format_func=lambda k: names.get(k, k))
    existing = account_by_key.get(choice, {})
    with st.form("account"):
        name = st.text_input("帳號名稱", existing.get("name", ""))
        platform = st.selectbox("平台", ["meta", "google"], index=1 if existing.get("platform") == "google" else 0)
        aid = st.text_input("廣告帳號 ID", existing.get("account_id", ""))
        action = st.text_input("Meta 轉換 action_type（尚未確認可先留空）", existing.get("meta_action_type", ""))
        mode = st.selectbox("Google 轉換口徑", ["selected", "primary"], index=1 if existing.get("google_conversion_mode") == "primary" else 0,
                            format_func=lambda m: "指定事件（包含該事件的次要轉換）" if m == "selected" else "帳號主要轉換總和（可能含非訂位事件）")
        action_ids = st.text_input("Google 指定轉換動作 ID（逗號分隔；不是事件名稱）", ",".join(existing.get("google_action_ids", [])))
        st.caption("Meta 每帳號只選一個 action_type，避免把不同購買彙總事件重複加總。")
        if st.form_submit_button("儲存帳號"):
            if not name.strip():
                st.error("請填寫帳號名稱。")
            elif existing and platform != existing["platform"]:
                st.error("現有帳號不可更換平台，請新增另一個帳號。")
            else:
                account = {"key": existing.get("key", uuid.uuid4().hex[:12]), "name": name.strip(), "platform": platform,
                           "account_id": aid.replace("-", "").strip(), "meta_action_type": action.strip(),
                           "google_conversion_mode": mode, "google_action_ids": [x.strip() for x in action_ids.split(",") if x.strip()]}
                updated = copy.deepcopy(settings)
                updated["accounts"] = [a for a in updated["accounts"] if a["key"] != account["key"]] + [account]
                save_settings(updated)
    if names:
        key = st.selectbox("檢查串接／列出轉換事件的帳號", list(names), format_func=names.get)
        if st.button("檢查串接與轉換事件"):
            if demo:
                st.info("示範模式不連接 API。")
            else:
                try:
                    account = account_by_key[key]
                    if account["platform"] == "google":
                        actions = GoogleProvider(creds).conversion_actions(account)
                        st.dataframe(pd.DataFrame(actions), hide_index=True)
                    else:
                        end = datetime.now(TAIPEI).date() - timedelta(days=1)
                        report = fetch_report(account, end - timedelta(days=6), end)
                        actions = sorted({a for r in report["rows"] for a in r.get("available_actions", [])})
                        st.write("最近 7 天回傳的 action_type：", actions)
                        st.caption("沒有出現在清單，不代表事件不存在；可能此區間沒有該事件。請以廣告後台口徑確認。")
                    st.success("API 請求成功；請選擇與後台一致的轉換事件。")
                except AppError as exc:
                    st.error(str(exc))
    with st.expander("部署狀態（只顯示是否設定，不顯示金鑰）"):
        for key in ["STATE_REPO", "STATE_TOKEN", "SOURCE_REPO", "SOURCE_TOKEN", "META_ACCESS_TOKEN", "META_API_VERSION", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN", "LINE_CHANNEL_ACCESS_TOKEN", "LINE_RECIPIENT_ID"]:
            present = bool(creds.get(key) or secret(key))
            st.write(f"{'✅' if present else '○'} {key}：{'已設定' if present else '未設定'}")

elif page == "專案預算":
    st.caption("以專案完整起訖日的花費計算預算結餘；不以局部查詢區間取代累計花費。不把帳號花費上限當成代理商儲值餘額。")
    if not names:
        st.info("請先新增廣告帳號。")
    else:
        project_names = {p["id"]: p["name"] for p in settings["projects"]}
        choice = st.selectbox("專案", ["新增專案"] + list(project_names), format_func=lambda k: project_names.get(k, k))
        project = next((p for p in settings["projects"] if p["id"] == choice), {})
        with st.form("project"):
            name = st.text_input("專案名稱", project.get("name", ""))
            account_key = st.selectbox("廣告帳號", list(names), index=list(names).index(project["account_key"]) if project else 0, format_func=names.get)
            field_options = ["campaign_name", "adset_name", "ad_name"]
            match_field = st.selectbox("名稱歸類欄位", field_options, index=field_options.index(project.get("match_field", "campaign_name")),
                                       format_func=lambda value: {"campaign_name": "行銷活動名稱", "adset_name": "廣告組合名稱（Meta）", "ad_name": "廣告名稱（Meta，沿用舊版分類方式）"}[value])
            keyword = st.text_input("名稱包含", project.get("keyword", ""))
            start = st.date_input("開始日", date.fromisoformat(project["start"]) if project else datetime.now(TAIPEI).date())
            end = st.date_input("結束日", date.fromisoformat(project["end"]) if project else datetime.now(TAIPEI).date())
            budget = st.number_input("平台投放預算（與 API 花費相同幣別；不含另計服務費／稅）", min_value=0.0, value=float(project.get("budget", 0)), step=1000.0)
            status = st.selectbox("狀態", ["進行中", "已結案"], index=1 if project.get("status") == "已結案" else 0)
            if st.form_submit_button("儲存專案"):
                item = {"id": project.get("id", uuid.uuid4().hex), "name": name.strip(), "account_key": account_key,
                        "keyword": keyword.strip(), "match_field": match_field, "start": str(start), "end": str(end), "budget": budget, "status": status}
                updated = copy.deepcopy(settings)
                updated["projects"] = [p for p in updated["projects"] if p["id"] != item["id"]] + [item]
                save_settings(updated)
        if st.button("更新各專案完整期間花費"):
            results = []
            for project in settings["projects"]:
                try:
                    account = account_by_key[project["account_key"]]
                    effective_end = min(date.fromisoformat(project["end"]), datetime.now(TAIPEI).date())
                    if effective_end < date.fromisoformat(project["start"]):
                        results.append({"專案": project["name"], "狀態": "尚未開始"})
                        continue
                    report = (demo_reports(date.fromisoformat(project["start"]), effective_end)[0] if demo else fetch_report(account, project["start"], effective_end))
                    rows = [r for r in report["rows"] if project["keyword"].casefold() in r.get(project.get("match_field", "campaign_name"), "").casefold()]
                    spent = sum(r["spend"] for r in rows)
                    results.append({"專案": project["name"], "狀態": project["status"], "起日": project["start"], "迄日": str(effective_end),
                                    "幣別": report["currency"], "預算": project["budget"], "花費": spent, "結餘／透支": project["budget"] - spent,
                                    "執行率 %": 100 * spent / project["budget"] if project["budget"] else None})
                except AppError as exc:
                    results.append({"專案": project["name"], "狀態": str(exc)})
            st.dataframe(pd.DataFrame(results), hide_index=True, use_container_width=True)
            st.caption("專案名稱篩選可能重疊，故此處不將專案花費相加作為全帳號總花費。")
        st.download_button("匯出設定備份（不含權杖）", json.dumps(settings, ensure_ascii=False, indent=2), "mori-settings.json")

elif page == "異常規則":
    st.write("判斷條件：花費 > 門檻，而且（零轉換，或 CPA > 門檻）。資料截至昨天，避開今天尚未完整的數據。")
    if not names:
        st.info("請先新增廣告帳號。")
    else:
        rule_names = {r["id"]: r["name"] for r in settings["rules"]}
        choice = st.selectbox("規則", ["新增規則"] + list(rule_names), format_func=lambda k: rule_names.get(k, k))
        rule = next((r for r in settings["rules"] if r["id"] == choice), {})
        # 帳號在 form 外，切換平台後層級選項立即更新。
        account_key = st.selectbox("規則指定帳號", list(names), index=list(names).index(rule["account_key"]) if rule else 0, format_func=names.get)
        google = account_by_key[account_key]["platform"] == "google"
        if not conversion_ready(account_by_key[account_key]):
            st.warning("此帳號還沒有轉換口徑，請先到「帳號與串接」設定；排程不會把它當成零轉換。")
        with st.form("rule"):
            name = st.text_input("規則名稱", rule.get("name", ""))
            enabled = st.checkbox("啟用規則", rule.get("enabled", False))
            available_levels = ["campaign"] if google else list(LEVELS)
            level = st.selectbox("判斷層級", available_levels, index=available_levels.index(rule.get("level", "campaign")) if rule.get("level", "campaign") in available_levels else 0, format_func=LEVELS.get)
            days = st.number_input("累計幾天（截至昨天）", 1, 30, int(rule.get("period_days", 1)))
            spend = st.number_input("花費必須超過", min_value=0.0, value=float(rule.get("minimum_spend", 1000)), step=100.0)
            cpa = st.number_input("CPA 必須超過", min_value=0.0, value=float(rule.get("cpa_threshold", 200)), step=10.0)
            zero = st.checkbox("花費過門檻且零轉換時也提醒", rule.get("notify_zero", True))
            recipient_key = st.text_input("LINE 通知對象代號", rule.get("recipient_key", "default"), help="default 使用 LINE_RECIPIENT_ID；其他代號從 Secrets 的 LINE_RECIPIENTS_JSON 對照，不在此填權杖。")
            campaign_filter = st.text_input("活動名稱包含（留空為全部）", rule.get("campaign_filter", ""))
            adset_filter = "" if google else st.text_input("廣告組合名稱包含", rule.get("adset_filter", ""))
            ad_filter = "" if google else st.text_input("廣告名稱包含", rule.get("ad_filter", ""))
            channel_options = ["ALL", "SEARCH", "PERFORMANCE_MAX", "DISPLAY", "VIDEO", "DEMAND_GEN", "SHOPPING"]
            channel = st.selectbox("Google 活動類型", channel_options, index=channel_options.index(rule.get("channel", "ALL")) if rule.get("channel", "ALL") in channel_options else 0) if google else "ALL"
            starts_on = st.text_input("規則啟用起日（選填 YYYY-MM-DD）", rule.get("starts_on", ""))
            ends_on = st.text_input("規則結束日（選填 YYYY-MM-DD）", rule.get("ends_on", ""))
            st.caption("門檻使用此帳號幣別。Meta 先套用三層名稱篩選，再彙總到指定層級；Google 首版以活動層級涵蓋搜尋與 PMax。")
            if st.form_submit_button("儲存規則"):
                item = {"id": rule.get("id", uuid.uuid4().hex), "name": name.strip(), "enabled": enabled, "account_key": account_key,
                        "level": level, "period_days": days, "minimum_spend": spend, "cpa_threshold": cpa, "notify_zero": zero,
                        "campaign_filter": campaign_filter.strip(), "adset_filter": adset_filter.strip(), "ad_filter": ad_filter.strip(),
                        "channel": channel, "starts_on": starts_on.strip(), "ends_on": ends_on.strip()}
                item["recipient_key"] = recipient_key.strip() or "default"
                updated = copy.deepcopy(settings)
                updated["rules"] = [r for r in updated["rules"] if r["id"] != item["id"]] + [item]
                save_settings(updated)
        if rule:
            with st.expander("刪除此規則"):
                confirmed = st.checkbox("確認刪除這筆已儲存規則")
                if st.button("刪除", disabled=not confirmed):
                    updated = copy.deepcopy(settings)
                    updated["rules"] = [r for r in updated["rules"] if r["id"] != rule["id"]]
                    save_settings(updated)
        if st.button("預覽已儲存且啟用的規則（不發 LINE）"):
            if demo:
                st.info("此預覽只展示操作介面；真實規則須接上私人設定與廣告 API 後驗證。")
            else:
                with st.spinner("檢查規則…"):
                    candidates, errors = check_rules(settings, creds)
                for item in candidates:
                    item.pop("_rule", None)
                st.dataframe(pd.DataFrame(candidates), hide_index=True)
                for error in errors:
                    st.error(f"{error['rule']}：{error['error']}")
                if not candidates and not errors:
                    st.info("沒有規則觸發；請確認至少一筆規則已啟用。")

elif page == "通知排程":
    st.write("網頁儲存通知時段；GitHub Actions 每 30 分鐘巡檢，到期後執行。關閉網頁不影響巡檢。")
    st.caption("所有時段均為 Asia/Taipei。實際時間可能因下一次巡檢與 GitHub 排程延遲而較晚；不是準點即時警報。")
    schedule = settings["schedule"]
    with st.form("schedule"):
        enabled = st.checkbox("啟用自動提醒", schedule["enabled"])
        time_text = st.text_input("每天通知時段（1 至 4 個，逗號分隔；分鐘用 00／15／30／45）", ",".join(schedule["times"]))
        weekdays = st.multiselect("執行星期", list(range(7)), default=schedule["weekdays"], format_func=lambda n: ["一", "二", "三", "四", "五", "六", "日"][n])
        st.caption("同規則、同實體、同資料日只提醒一次；新增第二個時段不會重複發相同異常。")
        if st.form_submit_button("儲存通知排程"):
            updated = copy.deepcopy(settings)
            updated["schedule"] = {"enabled": enabled, "times": sorted(x.strip() for x in time_text.split(",") if x.strip()), "weekdays": weekdays}
            save_settings(updated)
    st.subheader("手動檢查")
    st.write("可由此網頁啟動 GitHub Actions，先選預覽驗證，再於 Secrets 開放正式 LINE 通知。")
    mode = st.radio("執行方式", ["preview", "send"], format_func=lambda m: "只預覽，不發 LINE" if m == "preview" else "正式通知（需 GitHub Secrets 已啟用）")
    confirm_send = st.checkbox("確認這次會向已設定的 LINE 對象發送真實異常通知") if mode == "send" else True
    if st.button("啟動一次檢查", disabled=not confirm_send):
        if demo:
            st.info("示範模式不啟動排程。")
        elif not secret("SOURCE_REPO") or not secret("SOURCE_TOKEN"):
            st.error("請先在 Streamlit Secrets 設定 SOURCE_REPO 和有 Actions 寫入權限的 SOURCE_TOKEN。")
        else:
            # repo 僅來自管理者 Secrets；固定官方 API 與固定工作流程。
            import re
            repo = str(secret("SOURCE_REPO"))
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
                st.error("SOURCE_REPO 格式不正確。")
            else:
                try:
                    response = requests.post(f"https://api.github.com/repos/{repo}/actions/workflows/monitor.yml/dispatches",
                        headers={"Authorization": f"Bearer {secret('SOURCE_TOKEN')}", "Accept": "application/vnd.github+json"},
                        json={"ref": str(secret("SOURCE_BRANCH", "main")), "inputs": {"mode": mode}}, timeout=30)
                    if response.status_code == 204:
                        st.success("已送出檢查請求；請稍後到「執行紀錄」重新整理。這不代表 LINE 已成功發送。")
                    else:
                        st.error(f"啟動失敗（HTTP {response.status_code}）；請確認 workflow 已合併至主分支與 Actions 權限。")
                except requests.RequestException:
                    st.error("啟動請求連線失敗，請到 GitHub Actions 確認是否已啟動，避免連續重按。")
    st.info("若沒有設定 SOURCE_TOKEN，仍可直接在 GitHub 的 Actions 頁手動執行；自動巡檢不受影響。正式發送另需在 GitHub Secrets 設定 LIVE_NOTIFICATIONS_ENABLED=true；未開放時只會預覽。")

elif page == "執行紀錄":
    if st.button("重新整理紀錄"):
        st.rerun()
    runs = runtime.get("runs", [])
    if runs:
        st.dataframe(pd.DataFrame([{k: r.get(k) for k in ["at", "slot", "mode", "status", "anomaly_count", "accepted_batches"]} for r in runs]), hide_index=True, use_container_width=True)
        index = st.selectbox("查看某次詳細結果", list(range(len(runs))), format_func=lambda i: str(runs[i]["at"]))
        st.json(runs[index])
    else:
        st.info("尚無執行紀錄；先儲存規則，再從通知排程啟動一次預覽。")
    pending = runtime.get("pending", [])
    if pending:
        st.warning(f"有 {len(pending)} 批發送結果未確認的通知。系統會使用相同重試碼重試；超過 23 小時須人工確認。")
        st.caption("人工解除代表把待發訊息標記為已處理，之後不再重送；請先確認 LINE 實際收件。")
        acknowledged = st.checkbox("我已核對 LINE，將所有待確認訊息標記為已處理")
        if st.button("解除待確認狀態", disabled=not acknowledged):
            try:
                owner = uuid.uuid4().hex
                store.acquire_lock(owner)
                try:
                    latest, sha = store.runtime()
                    for batch in latest.get("pending", []):
                        for fp in batch["fingerprints"]:
                            latest["receipts"][fp] = datetime.now(TAIPEI).isoformat()
                    latest["pending"] = []
                    store.write("runtime.json", latest, sha)
                finally:
                    store.release_lock(owner)
                st.rerun()
            except AppError as exc:
                st.error(str(exc))
