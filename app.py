from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import sys
import uuid
from pathlib import Path
import base64
from datetime import date, datetime, timedelta

import pandas as pd
import requests
import streamlit as st

# Resolve local modules from the entry file even when the server changes cwd.
_app_root = str(Path(__file__).resolve().parent)
if _app_root not in sys.path:
    sys.path.insert(0, _app_root)

from mori.core import (AppError, LEVELS, TAIPEI, conversion_ready, default_settings,
                       rule_window, validate_settings)
from mori.accounts import (account_label, account_dependencies, delete_account, normalized_id, save_account)
from mori.providers import GoogleProvider, provider_for
from mori.runner import check_rules, conversion_label
from mori.storage import GitHubStore
from mori.ui_performance import UIStore, fetch_accounts
from mori.budget_ui import render_budgets, render_budget_heading
from mori.money_display import styled_money_frame
from mori.dashboard import CSS as DASHBOARD_CSS, render_report as render_overview, overview_controls, previous_period
from mori.vault import resolve_credentials
from mori.connection_ui import connection_panel
from mori.field_guidance import (META_ACCOUNT_GUIDANCE, GOOGLE_ACCOUNT_GUIDANCE,
                                 META_ACTION_GUIDANCE, GOOGLE_ACTION_GUIDANCE)

ASSETS = Path(__file__).parent / "assets"
st.set_page_config(page_title="廣告智慧儀表板", page_icon=(ASSETS / "mori-bull-icon.svg").read_text(), layout="wide")
from mori.design_system import stylesheet
st.html(stylesheet())


def secret(key, default=""):
    try:
        return st.secrets.get(key, os.environ.get(key, default))
    except FileNotFoundError:
        return os.environ.get(key, default)


def credentials():
    names = ["META_ACCESS_TOKEN", "META_API_VERSION", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
             "GOOGLE_REFRESH_TOKEN", "GOOGLE_LOGIN_CUSTOMER_ID", "GOOGLE_API_VERSION",
             "GOOGLE_DEVELOPER_TOKEN", "LINE_CHANNEL_ACCESS_TOKEN", "LINE_RECIPIENT_ID", "LINE_RECIPIENTS_JSON", "SOURCE_REPO", "SOURCE_TOKEN", "SOURCE_BRANCH"]
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
                         "spend": spend, "impressions": 20000.0, "clicks": 200.0, "conversions": conv, "conversion_value": 0.0,
                         "campaign_objective": "OUTCOME_SALES" if platform == "meta" else "",
                         "engagements": 300.0 if platform == "meta" else None, "interactions": 200.0 if platform == "google" else None})
        current += timedelta(days=1)
    return [{"rows": [r for r in rows if r["platform"] == p], "currency": "TWD", "timezone": "Asia/Taipei", "conversion_ready": True} for p in ("meta", "google")]


demo = str(secret("DEMO_MODE", "false")).lower() == "true"
if demo:
    st.warning("示範模式｜以下為人工建立的示例，未串接真實廣告帳號、不儲存設定、不發送 LINE。")

logo_svg = base64.b64encode((ASSETS / "mori-logo-white.svg").read_bytes()).decode()
st.sidebar.markdown(f'<div class="mori-brand"><img alt="森森燒肉正式 Logo" src="data:image/svg+xml;base64,{logo_svg}"><span>廣告智慧儀表板</span></div>', unsafe_allow_html=True)

pending_overview_budget = st.session_state.pop('overview_budget_target', None)
if pending_overview_budget:
    st.session_state.navigation_page = '專案預算'
    st.session_state.budget_section = 'overview'
    st.session_state.budget_selected_project = pending_overview_budget
    st.session_state.budget_nav_year = None
    st.session_state.budget_nav_search = ''
    st.session_state.budget_state_filter = '全部'
    st.session_state.budget_category_filter = '全部'
page = st.sidebar.radio("功能", ["數據總覽", "專案預算", "異常規則", "通知排程", "執行紀錄", "帳號與串接", "API 與權杖設定"], key="navigation_page")
# First budget visit loads data. Navigation and filter changes reuse this
# session snapshot; only the manual button requests another read.
if st.session_state.get('last_navigation_page') != page:
    if page == '專案預算' and not st.session_state.get('budget_view'):
        st.session_state.budget_refresh_requested = True
    st.session_state.last_navigation_page = page
st.sidebar.caption("台灣時間 " + datetime.now(TAIPEI).strftime("%Y/%m/%d %H:%M"))
with st.sidebar.expander("系統資訊與外觀"):
    st.caption("系統版本：2026.11.28.61")
    logo = st.file_uploader("品牌 Logo（此次瀏覽使用）", type=["png", "jpg", "jpeg"])
    if logo:
        st.image(logo, width=180)
if page == '專案預算':
    render_budget_heading()
elif page != '數據總覽':
    from mori.design_system import page_header
    descriptions={'異常規則':('把需要注意的廣告，交給規則追蹤。','rules'),'通知排程':('在對的時間，收到需要處理的提醒。','clock'),'執行紀錄':('每一次檢查與通知，都有跡可循。','clock'),'帳號與串接':('管理廣告帳號，確認資料連線狀態。','account'),'API 與權杖設定':('集中管理連線憑證與平台授權。','key')}
    description,icon=descriptions[page]
    st.markdown(page_header(page,description,icon=icon),unsafe_allow_html=True)
if st.session_state.get("save_notice"):
    st.success(st.session_state.pop("save_notice"))


store = None
settings_sha = None
if demo:
    settings = st.session_state.get("demo_settings", demo_settings())
    runtime = {"runs": [], "pending": []}
else:
    try:
        identity = hashlib.sha256(json.dumps([str(secret("STATE_REPO")), str(secret("STATE_TOKEN")), str(secret("STATE_BRANCH", "main"))]).encode()).hexdigest()
        if st.session_state.get("ui_store_identity") != identity:
            st.session_state.ui_store = UIStore(GitHubStore(str(secret("STATE_REPO")), str(secret("STATE_TOKEN")), str(secret("STATE_BRANCH", "main"))))
            st.session_state.ui_store_identity = identity
        store = st.session_state.ui_store
        if st.sidebar.button("重新載入設定", help="立即讀取其他視窗的設定變更；一般操作使用此瀏覽連線的短期快取。"):
            store.clear()
            if page == '專案預算':
                st.session_state.budget_refresh_requested = True
        settings, settings_sha = store.settings()
        settings = validate_settings(settings)
    except (AppError, ValueError) as exc:
        st.error(str(exc))
        st.stop()


def save_settings(updated, notice=None, rule_id=None, keep_budget_view=False):
    try:
        from mori.budget_ledger import protect_history
        protect_history(settings, updated)
        validated = validate_settings(updated)
        if demo:
            st.session_state.demo_settings = validated
        else:
            store.write("settings.json", validated, settings_sha)
        st.session_state.pop("report_view", None)
        if not keep_budget_view:
            st.session_state.pop("budget_view", None)
        st.session_state.save_notice = (notice or "設定已儲存。") if not demo else "示範設定已更新，僅保留在這次預覽。"
        if rule_id:
            st.session_state.pending_rule_selection = rule_id
        st.rerun()
    except AppError as exc:
        st.error("儲存失敗：" + str(exc))
    except (ValueError, TypeError):
        st.error("儲存失敗：請確認欄位完整、日期與金額正確；若有其他人更新設定，請重新整理頁面後再試。")



account_by_key = {a["key"]: a for a in settings["accounts"]}
names = {a["key"]: a["name"] for a in settings["accounts"]}
try:
    creds = resolve_credentials(credentials(), store, str(secret("CREDENTIALS_KEY"))) if not demo else {}
except AppError as exc:
    st.error(str(exc))
    st.stop()


def fetch_report(account, start, end):
    return provider_for(account, creds).fetch(account, start, end)


def reports_table(reports):
    rows = [row for report in reports for row in report["rows"]]
    return pd.DataFrame(rows)


if page == "數據總覽":
    if not settings["accounts"]:
        st.info("先到「帳號與串接」新增 Meta 或 Google Ads 帳號。")
    else:
        with st.container(key='overview_mode_bar'):
            mode=st.radio('數據總覽模式',['廣告成效','檔期投資模型'],horizontal=True,key='overview_mode',label_visibility='collapsed')
        if mode=='檔期投資模型':
            from mori.festival_ui import render_festival_model
            model_store=store
            if demo:
                from mori.invoices import DemoInvoiceStore
                if 'demo_festival_store' not in st.session_state:
                    st.session_state.demo_festival_store=DemoInvoiceStore()
                model_store=st.session_state.demo_festival_store
            render_festival_model(settings,model_store,lambda a:provider_for(a,creds),save_settings)
        else:
            keys, period, compare, read = overview_controls(names)
            if read:
                if len(period) != 2 or not keys:
                    st.error('請選擇完整日期與至少一個帳號。')
                else:
                    def load_period(start, end):
                        if demo:
                            reports = []
                            for account in [account_by_key[k] for k in keys]:
                                result = next(r for r in demo_reports(start, end) if r['rows'][0]['platform'] == account['platform'])
                                result['account_key'] = account['key']
                                for row in result['rows']:
                                    row['account_key'] = account['key']
                                reports.append(result)
                            return reports, []
                        return fetch_accounts([account_by_key[k] for k in keys],
                                              lambda account: {**provider_for(account, creds).fetch_overview(account, start, end), 'account_key': account['key']})
                    with st.spinner('讀取廣告數據與比較期間…' if compare else '讀取廣告數據…'):
                        reports, errors = load_period(*period)
                        earlier = previous_period(period)
                        previous_reports, previous_errors = load_period(*earlier) if compare else ([], [])
                    st.session_state.report_view = {'reports': reports, 'errors': errors, 'keys': keys,
                        'loaded_keys': [r['account_key'] for r in reports], 'period': tuple(map(str, period)),
                        'at': datetime.now(TAIPEI).isoformat(), 'comparison': compare,
                        'previous_reports': previous_reports, 'previous_errors': previous_errors,
                        'previous_period': tuple(map(str, earlier))}
            @st.fragment
            def overview_fragment(view):
                render_overview(view, keys, period, settings, names, account_by_key)
            overview_fragment(st.session_state.get("report_view"))

elif page == "帳號與串接":
    st.info("平台權杖請到左側「API 與權杖設定」集中填寫；本頁只管理廣告帳號與訂位事件。")
    st.subheader("廣告帳號設定")
    st.write("選擇「編輯既有帳號」更新訂位事件；只有接入另一個廣告帳號時才選「新增帳號」。")
    if names:
        st.dataframe(pd.DataFrame([{"名稱": a["name"], "平台": a["platform"], "帳號": a["account_id"], "轉換口徑": conversion_label(a)} for a in settings["accounts"]]), hide_index=True)
    operation = st.radio("帳號操作", ["編輯既有帳號", "新增帳號"] if names else ["新增帳號"], horizontal=True)
    choice = st.selectbox("選擇要編輯的帳號", list(names),
                          format_func=lambda k: account_label(account_by_key[k])) if operation == "編輯既有帳號" else "new"
    existing = account_by_key.get(choice, {})
    if existing:
        st.caption("正在編輯：" + account_label(existing))
    platform = st.selectbox("廣告平台", ["meta", "google"], index=1 if existing.get("platform") == "google" else 0,
                            format_func=lambda x: "Meta 廣告" if x == "meta" else "Google Ads 廣告",
                            key="account_platform_" + choice, disabled=bool(existing))
    with st.form("account_" + choice):
        name = st.text_input("帳號名稱（自訂，例如：森森燒肉－Meta）", existing.get("name", ""), key="account_name_" + choice)
        st.caption("自行命名，方便你在儀表板辨識；不用向平台申請，也不會更改廣告後台的名稱。")
        aid = st.text_input("廣告帳號 ID", existing.get("account_id", ""), key="account_id_" + choice)
        st.caption(META_ACCOUNT_GUIDANCE if platform == "meta" else GOOGLE_ACCOUNT_GUIDANCE)
        action = existing.get("meta_action_type", "")
        mode = existing.get("google_conversion_mode", "selected")
        action_ids = ",".join(existing.get("google_action_ids", []))
        if platform == "meta":
            action = st.text_input("訂位事件代碼（Meta 購買；尚未查詢可先留空）", action, key="account_action_" + choice)
            st.caption(META_ACTION_GUIDANCE)
        else:
            mode = "selected"
            st.caption("轉換口徑：只統計指定的訂位事件。請勿同時選入重複追蹤同一筆訂位的事件。")
            action_ids = st.text_input("訂位轉換動作 ID（數字；多個用逗號分隔）", action_ids, key="account_conversions_" + choice)
            st.caption(GOOGLE_ACTION_GUIDANCE)
        if st.form_submit_button("更新此帳號" if existing else "新增帳號"):
            if not name.strip():
                st.error("請填寫帳號名稱。")
            elif existing and platform != existing["platform"]:
                st.error("現有帳號不可更換平台，請新增另一個帳號。")
            else:
                account = {"key": existing.get("key", uuid.uuid4().hex[:12]), "name": name.strip(), "platform": platform,
                           "account_id": aid.replace("-", "").strip(), "meta_action_type": action.strip(),
                           "google_conversion_mode": mode, "google_action_ids": [x.strip() for x in action_ids.split(",") if x.strip()]}
                try:
                    updated = save_account(settings, account)
                except AppError as exc:
                    st.error(str(exc))
                else:
                    save_settings(updated)
    if existing:
        with st.expander("刪除此帳號設定"):
            st.write("將刪除：" + account_label(existing))
            st.caption("只刪除儀表板內這筆設定，不會刪除平台廣告帳號，也不會移除共用權杖。")
            dependencies = account_dependencies(settings, choice)
            replacement_key = None
            can_delete = True
            if dependencies:
                st.warning("這筆設定仍有專案或異常規則使用，刪除前必須先移轉。")
                for group, item in dependencies:
                    st.write(("專案：" if group == "projects" else "規則：") + item["name"])
                candidates = [a["key"] for a in settings["accounts"] if a["key"] != choice
                              and a["platform"] == existing["platform"]
                              and normalized_id(a["account_id"]) == normalized_id(existing["account_id"])]
                if candidates:
                    replacement_key = st.selectbox("將上述專案與規則移轉至保留的同帳號紀錄", [None] + candidates,
                        format_func=lambda k: "請選擇保留紀錄" if k is None else account_label(account_by_key[k]), key="account_replacement_" + choice)
                    can_delete = replacement_key is not None
                else:
                    st.info("沒有可接收的同帳號紀錄，請先到專案預算或異常規則調整關聯。")
                    can_delete = False
            confirmed = st.checkbox("確認刪除上述帳號設定", key="account_delete_confirm_" + choice)
            if st.button("刪除此帳號設定", disabled=not (confirmed and can_delete), key="account_delete_" + choice):
                try:
                    updated = delete_account(settings, choice, replacement_key)
                except AppError as exc:
                    st.error(str(exc))
                else:
                    save_settings(updated)
    if names:
        key = st.selectbox("檢查串接／列出轉換事件的帳號", list(names), format_func=lambda k: account_label(account_by_key[k]))
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
elif page == "API 與權杖設定":
    connection_panel(store, creds, secret, settings["accounts"], demo)

elif page == "專案預算":
    def budget_fetch(account, start, end):
        if demo:
            return next(r for r in demo_reports(start, end) if r['rows'][0]['account_key'] == account['key'])
        provider = provider_for(account, creds)
        return provider.fetch_budget(account, start, end)
    from mori.invoices import InvoiceDocuments, DemoInvoiceStore
    invoice_documents = None
    try:
        if demo:
            from cryptography.fernet import Fernet
            if 'demo_invoice_store' not in st.session_state:
                st.session_state.demo_invoice_store = DemoInvoiceStore()
                st.session_state.demo_invoice_key = Fernet.generate_key().decode()
            invoice_documents = InvoiceDocuments(st.session_state.demo_invoice_store, st.session_state.demo_invoice_key)
        else:
            invoice_documents = InvoiceDocuments(store, str(secret('CREDENTIALS_KEY')))
    except AppError:
        pass  # Existing reports remain usable; the invoice page explains setup.
    def account_spend_fetch(account, start, end):
        if demo:
            from decimal import Decimal
            report = next(r for r in demo_reports(start, end) if r['rows'][0]['platform'] == account['platform'])
            return {'spend_raw': str(sum((Decimal(str(r['spend'])) for r in report['rows']), Decimal(0))),
                    'currency': report['currency'], 'timezone': report['timezone'], 'since': str(start), 'until': str(end)}
        return provider_for(account, creds).fetch_account_spend(account, start, end)
    render_budgets(settings, budget_fetch, save_settings, invoice_documents, account_spend_fetch)

elif page == "異常規則":
    st.write("判斷條件：花費 > 門檻，而且（零轉換，或 CPA > 門檻）。資料截至昨天，避開今天尚未完整的數據。")
    if not names:
        st.info("請先新增廣告帳號。")
    else:
        st.subheader("已儲存規則")
        if settings["rules"]:
            st.dataframe(styled_money_frame(pd.DataFrame([{
                "規則名稱": r["name"], "狀態": rule_window(r, settings)[2],
                "關聯專案": next((p["name"] for p in settings["projects"] if p["id"] == r.get("project_id")), "獨立規則"),
                "帳號": names.get(r["account_key"], r["account_key"]), "層級": LEVELS[r["level"]],
                "累計天數": r.get("period_days", 1), "花費門檻 >": r["minimum_spend"], "CPA 門檻 >": r["cpa_threshold"],
                "活動包含": r.get("campaign_filter", ""), "廣告組合包含": r.get("adset_filter", ""),
                "廣告包含": r.get("ad_filter", ""), "資料起日": r.get("starts_on") or next((p["start"] for p in settings["projects"] if p["id"] == r.get("project_id")), "不限"),
                "資料迄日": r.get("ends_on") or next((p["end"] for p in settings["projects"] if p["id"] == r.get("project_id")), "不限"), "通知對象": r.get("recipient_key", "default")
            } for r in settings["rules"]]), {"花費門檻 >", "CPA 門檻 >"}), hide_index=True)
        else:
            st.info("尚未儲存任何規則。請填寫下方表單並按「儲存規則」。")
        enabled_count = sum(bool(r.get("enabled")) for r in settings["rules"])
        st.caption(f"已儲存 {len(settings['rules'])} 筆，已啟用 {enabled_count} 筆。預覽只檢查已儲存且啟用的規則。")
        st.caption("自動提醒排程：" + ("已啟用" if settings["schedule"].get("enabled") else "尚未啟用；儲存規則不會自動開啟排程。"))
        if st.button("＋新增規則"):
            st.session_state.rule_editor_choice = "新增規則"
        st.caption("選擇下方既有規則可編輯；選取後可在表單下方刪除。到期規則保留紀錄，但不再參與檢查。")
        rule_names = {r["id"]: r["name"] for r in settings["rules"]}
        pending_rule = st.session_state.pop("pending_rule_selection", None)
        if pending_rule in rule_names:
            st.session_state.rule_editor_choice = pending_rule
        choice = st.selectbox("規則", ["新增規則"] + list(rule_names), format_func=lambda k: rule_names.get(k, k), key="rule_editor_choice")
        rule = next((r for r in settings["rules"] if r["id"] == choice), {})
        # 帳號在 form 外，切換平台後層級選項立即更新。
        account_key = st.selectbox("規則指定帳號", list(names), index=list(names).index(rule["account_key"]) if rule else 0, format_func=names.get, key="rule_account_" + choice)
        available_projects = {p["id"]: p for p in settings["projects"] if p["account_key"] == account_key}
        project_options = [""] + list(available_projects)
        project_id = st.selectbox("連結平台投放計畫（選填）", project_options,
            index=project_options.index(rule.get("project_id", "")) if rule.get("project_id", "") in project_options else 0,
            format_func=lambda k: "不連結，使用規則自己的起訖日" if not k else available_projects[k]["name"],
            key="rule_project_" + choice + "_" + account_key)
        linked_project = available_projects.get(project_id)
        if linked_project:
            st.info(f"跟隨此平台廣告走期：{linked_project['start']} ～ {linked_project['end']}；狀態：{linked_project['status']}。專案日期或結案狀態更新時，規則會同步套用。")
        google = account_by_key[account_key]["platform"] == "google"
        if not conversion_ready(account_by_key[account_key]):
            st.warning("此帳號還沒有轉換口徑，請先到「帳號與串接」設定；排程不會把它當成零轉換。")
        with st.form("rule_" + choice):
            name = st.text_input("規則名稱", rule.get("name", ""))
            enabled = st.checkbox("啟用規則", rule.get("enabled", False))
            available_levels = ["campaign"] if google else list(LEVELS)
            level = st.selectbox("判斷層級", available_levels, index=available_levels.index(rule.get("level", "campaign")) if rule.get("level", "campaign") in available_levels else 0, format_func=lambda k: "廣告活動" if google and k == "campaign" else LEVELS[k])
            days = st.number_input("累計幾天（截至昨天）", 1, 30, int(rule.get("period_days", 1)))
            spend = st.number_input("花費必須超過", min_value=0.0, value=float(rule.get("minimum_spend", 1000)), step=100.0, icon=":material/attach_money:", format="%.2f")
            cpa = st.number_input("CPA 必須超過", min_value=0.0, value=float(rule.get("cpa_threshold", 200)), step=10.0, icon=":material/attach_money:", format="%.2f")
            zero = st.checkbox("花費過門檻且零轉換時也提醒", rule.get("notify_zero", True))
            recipient_key = st.text_input("LINE 通知對象代號", rule.get("recipient_key", "default"), help="default 使用 LINE_RECIPIENT_ID；其他代號從 Secrets 的 LINE_RECIPIENTS_JSON 對照，不在此填權杖。")
            campaign_filter = st.text_input("活動名稱包含（留空為全部）", rule.get("campaign_filter", ""))
            adset_filter = "" if google else st.text_input("廣告組合名稱包含", rule.get("adset_filter", ""))
            ad_filter = "" if google else st.text_input("廣告名稱包含", rule.get("ad_filter", ""))
            channel_options = ["ALL", "SEARCH", "PERFORMANCE_MAX", "DISPLAY", "VIDEO", "DEMAND_GEN", "SHOPPING"]
            channel = st.selectbox("Google 活動類型", channel_options, index=channel_options.index(rule.get("channel", "ALL")) if rule.get("channel", "ALL") in channel_options else 0) if google else "ALL"
            if linked_project:
                starts_on, ends_on = "", ""
            else:
                starts_on = st.text_input("規則啟用起日（選填 YYYY-MM-DD）", rule.get("starts_on", ""))
                ends_on = st.text_input("規則結束日（選填 YYYY-MM-DD）", rule.get("ends_on", ""))
            st.caption("起訖日指被檢查的廣告資料日期。例如結束日 11/19，11/20 早上完成最後一次檢查，11/21 起自動失效；專案手動結案則立即停止後續檢查。")
            st.caption("門檻使用此帳號幣別。Meta 先套用三層名稱篩選，再彙總到指定層級；Google 異常規則目前以廣告活動層級涵蓋搜尋與 PMax。")
            if st.form_submit_button("儲存規則"):
                item = {"id": rule.get("id", uuid.uuid4().hex), "name": name.strip(), "enabled": enabled, "account_key": account_key,
                        "level": level, "period_days": days, "minimum_spend": spend, "cpa_threshold": cpa, "notify_zero": zero,
                        "campaign_filter": campaign_filter.strip(), "adset_filter": adset_filter.strip(), "ad_filter": ad_filter.strip(),
                        "channel": channel, "starts_on": starts_on.strip(), "ends_on": ends_on.strip()}
                item["project_id"] = project_id
                item["recipient_key"] = recipient_key.strip() or "default"
                updated = copy.deepcopy(settings)
                updated["rules"] = [r for r in updated["rules"] if r["id"] != item["id"]] + [item]
                save_settings(updated, notice=f"規則「{item['name']}」已儲存，狀態：{'已啟用' if enabled else '未啟用'}。", rule_id=item["id"])
        if rule:
            with st.expander("刪除此規則", expanded=True):
                st.write("將刪除規則：" + rule["name"])
                confirmed = st.checkbox("確認刪除這筆已儲存規則")
                if st.button("刪除此規則", disabled=not confirmed):
                    updated = copy.deepcopy(settings)
                    updated["rules"] = [r for r in updated["rules"] if r["id"] != rule["id"]]
                    save_settings(updated)
        if st.button("預覽已儲存且啟用的規則（不發 LINE）"):
            if not settings["rules"]:
                st.warning("尚未儲存規則，請先按「儲存規則」。")
            elif not enabled_count:
                st.warning("規則已儲存，但全部未啟用。請選擇規則，勾選「啟用規則」後再儲存。")
            elif demo:
                st.info("此預覽只展示操作介面；真實規則須接上私人設定與廣告 API 後驗證。")
            else:
                diagnostics = []
                with st.spinner("檢查規則…"):
                    candidates, errors = check_rules(settings, creds, diagnostics=diagnostics)
                st.subheader("各規則檢查結果")
                st.dataframe(pd.DataFrame(diagnostics), hide_index=True)
                for item in candidates:
                    item.pop("_rule", None)
                if candidates:
                    st.subheader("符合異常條件的項目")
                    st.dataframe(styled_money_frame(pd.DataFrame(candidates), {"spend", "cpa"}), hide_index=True)
                    st.success(f"找到 {len(candidates)} 個異常項目。這是預覽，尚未發送 LINE。")
                for error in errors:
                    st.error(f"{error['rule']}：{error['error']}")
                if not candidates and not errors:
                    st.info("檢查完成，目前沒有符合異常條件的項目。請看上表確認是日期、名稱篩選或門檻造成；這不代表規則未儲存。")

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
        elif not creds.get("SOURCE_REPO") or not creds.get("SOURCE_TOKEN"):
            st.error("請先到「API 與權杖設定」填入程式儲存庫及 GitHub 排程啟動權杖（需 Actions 寫入權限）。")
        else:
            # repo 僅來自管理員串接設定；固定官方 API 與固定工作流程。
            import re
            repo = str(creds.get("SOURCE_REPO", ""))
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
                st.error("SOURCE_REPO 格式不正確。")
            else:
                try:
                    response = requests.post(f"https://api.github.com/repos/{repo}/actions/workflows/monitor.yml/dispatches",
                        headers={"Authorization": f"Bearer {creds.get('SOURCE_TOKEN', '')}", "Accept": "application/vnd.github+json"},
                        json={"ref": str(creds.get("SOURCE_BRANCH") or "main"), "inputs": {"mode": mode}}, timeout=30)
                    if response.status_code == 204:
                        st.success("已送出檢查請求；請稍後到「執行紀錄」重新整理。這不代表 LINE 已成功發送。")
                    else:
                        st.error(f"啟動失敗（HTTP {response.status_code}）；請確認 workflow 已合併至主分支與 Actions 權限。")
                except requests.RequestException:
                    st.error("啟動請求連線失敗，請到 GitHub Actions 確認是否已啟動，避免連續重按。")
    st.info("若沒有設定 SOURCE_TOKEN，仍可直接在 GitHub 的 Actions 頁手動執行；自動巡檢不受影響。正式發送另需在 GitHub Secrets 設定 LIVE_NOTIFICATIONS_ENABLED=true；未開放時只會預覽。")

elif page == "執行紀錄":
    st.button("重新整理紀錄")
    try:
        runtime = {"runs": [], "pending": []} if demo else store.runtime()[0]
    except AppError as exc:
        st.error(str(exc))
        st.stop()
    runs = runtime.get("runs", [])
    if runs:
        st.dataframe(pd.DataFrame([{k: r.get(k) for k in ["at", "slot", "mode", "status", "anomaly_count", "accepted_batches"]} for r in runs]), hide_index=True, use_container_width=True)
        @st.fragment
        def render_run_detail():
            index = st.selectbox("查看某次詳細結果", list(range(len(runs))), format_func=lambda i: str(runs[i]["at"]))
            st.json(runs[index])
        render_run_detail()
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
