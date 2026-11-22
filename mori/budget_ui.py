"""Project budget cards with independent activity and platform advertising dates."""
from __future__ import annotations

import base64
import html
import json
import uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st

from mori.budgets import (collect_spend, configuration_key, plan_summary, save_group,
                          save_plan, time_progress, group_summary, refresh_due, period_state, advertising_state)
from mori.core import AppError, TAIPEI
from mori.budget_ledger import balance, impacts
from mori.budget_ledger_ui import records, render_ledger


BUDGET_STYLES = """<style>
.mori-project-heading{display:flex;justify-content:space-between;align-items:center;gap:18px;flex-wrap:wrap;margin:0 0 18px;padding:22px 24px;border-radius:13px;border-left:6px solid #b79a65;background:linear-gradient(115deg,#17421E,#0d2914);box-shadow:0 6px 18px #17421e16;}
.mori-project-heading .project-name{font-size:34px!important;margin:0;line-height:1.3;font-weight:800;color:#fff!important;letter-spacing:.015em;overflow-wrap:anywhere;}
.mori-project-kicker{font-size:13px;color:#c6ddbd;font-weight:600;letter-spacing:.1em;margin-bottom:5px;}
.mori-status-pair{display:flex;gap:10px;flex-wrap:wrap;}
.mori-status{display:inline-flex;align-items:center;gap:8px;border-radius:9px;padding:8px 13px;font-size:15px!important;font-weight:700;line-height:1.4;border:1px solid;white-space:nowrap;}
.mori-status.preparing{background:#fff4da;color:#875600;border-color:#e6c978;}
.mori-status.running{background:#e5f3e6;color:#17421E;border-color:#9ec7a4;}
.mori-status.closed{background:#edf0f3;color:#465260;border-color:#bcc6ce;}
.mori-status .status-scope{font-weight:500;opacity:.85;}
.mori-period-dates{font-size:16px!important;color:#4e6252;line-height:1.7;margin:0 0 14px;}
.mori-platform-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:4px 0 8px;}
.mori-platform-heading>span:first-child{font-size:23px!important;font-weight:750;color:#17421E;}
.mori-ad-dates{font-size:15px!important;color:#536958;line-height:1.7;margin-bottom:14px;}
@media(max-width:700px){.mori-project-heading{padding:18px;}.mori-project-heading .project-name{font-size:28px!important;}.mori-status{font-size:14px!important;padding:6px 10px;}}

.mori-budget-hero{position:relative;overflow:hidden;border-radius:20px;padding:30px 34px;margin:0 0 22px;background:radial-gradient(ellipse at 95% 0,#629b4566,transparent 53%),linear-gradient(115deg,#17421E,#0a2411);border:1px solid #36613b;box-shadow:0 12px 32px #17421e1a;}
.mori-budget-hero-inner{display:flex;align-items:center;gap:22px;position:relative;}
.mori-budget-symbol{flex-shrink:0;width:76px;height:76px;border-radius:18px;background:#b79a651a;border:1px solid #b79a6566;display:flex;align-items:center;justify-content:center;color:#d8f3b5;font-size:25px;font-weight:800;}
.mori-budget-hero .hero-category{color:#dfd4bd;font-size:14px;font-weight:700;letter-spacing:.12em;margin-bottom:7px;}
.mori-budget-hero h1{font-size:48px!important;font-weight:850!important;line-height:1.16!important;letter-spacing:.025em!important;margin:0!important;padding:0!important;color:white!important;}
.mori-budget-hero p{font-size:17px!important;line-height:1.6;color:#d3e1d2;margin:12px 0 0;}

.st-key-budget_navigation{margin:4px 0 20px;padding:10px;background:#f0eeea;border:1px solid #d8d5ce;border-radius:15px;}
.st-key-budget_navigation [data-testid="stButton"] button{min-height:62px;width:100%;border:2px solid #afc6b1!important;border-radius:11px!important;background:#fff!important;color:#17421E!important;box-shadow:0 3px 8px #17421e0d;}
.st-key-budget_navigation [data-testid="stButton"] button p{font-size:18px!important;font-weight:700!important;color:inherit!important;}
.st-key-budget_navigation [data-testid="stButton"] button:hover{background:#f8f5ee!important;border-color:#527d53!important;box-shadow:0 5px 12px #17421e16;}
.st-key-budget_navigation [data-testid="stButton"] button[kind="primary"]{background:#17421E!important;color:#fff!important;border-color:#17421E!important;box-shadow:0 5px 14px #17421e30;}
.st-key-budget_navigation [data-testid="stButton"] button:focus-visible{outline:3px solid #b79a65;outline-offset:3px;}
@media(max-width:700px){.mori-budget-hero{padding:24px 20px;}.mori-budget-hero-inner{gap:14px;}.mori-budget-symbol{width:56px;height:56px;}.mori-budget-hero h1{font-size:36px!important;}.mori-budget-hero p{font-size:15px!important;}.st-key-budget_navigation [data-testid="stButton"] button{min-height:52px;}.st-key-budget_navigation [data-testid="stButton"] button p{font-size:16px!important;}}

.st-key-budget_project_rail{background:linear-gradient(160deg,#fff,#f7f5f0);border:1px solid #cbddc9!important;border-radius:16px;padding:18px 14px;box-shadow:0 8px 24px #17421e0a;}
.mori-rail-title{font-size:24px;font-weight:800;color:#17421E;line-height:1.5;}
.mori-rail-subtitle{font-size:14px;color:#5d735e;margin-bottom:16px;}
.mori-rail-status{font-size:14px;font-weight:700;margin-bottom:8px;}
.st-key-budget_project_rail [data-testid="stButton"] button{min-height:46px;text-align:left;justify-content:flex-start;width:100%;border:1px solid #d8d5ce;background:#fff;color:#17421E;}
.st-key-budget_project_rail [data-testid="stButton"] button p{font-size:16px!important;font-weight:650;line-height:1.5;overflow-wrap:anywhere;}
.st-key-budget_project_rail [data-testid="stButton"] button[kind="primary"]{background:#17421E!important;color:#fff!important;border-color:#17421E;box-shadow:inset 4px 0 #b79a65;}
.st-key-budget_project_rail [data-testid="stButton"] button:hover{border-color:#73965d;background:#f5f1e8;}
.st-key-budget_project_rail [data-testid="stButton"] button:focus-visible{outline:3px solid #b79a65;outline-offset:2px;}
.mori-results-heading{font-size:22px;font-weight:750;color:#17421E;margin:0 0 12px;}
.st-key-budget_project_content [data-testid="stMetric"]{padding:16px 14px;}
.st-key-budget_project_content [data-testid="stMetricValue"]{font-size:clamp(22px,2.1vw,32px)!important;}
@media(max-width:700px){.st-key-budget_project_rail{padding:14px;}.st-key-budget_project_list{height:260px!important;max-height:260px;overflow-y:auto;}}

.mori-editor-intro{padding:24px 26px;background:linear-gradient(110deg,#17421E,#284c2c);border-radius:15px;margin:4px 0 28px;}
.mori-editor-intro strong{font-size:26px;color:#fff;line-height:1.5;}.mori-editor-intro p{font-size:16px;color:#d9e8d5;margin:8px 0 0;}
.mori-editor-step{display:flex;align-items:center;gap:16px;margin:32px 0 18px;}.mori-editor-step>span{display:grid;place-items:center;background:#17421E;color:#dfd4bd;border-radius:12px;width:52px;height:52px;font-size:23px;font-weight:800;flex-shrink:0;}
.mori-editor-step h2{font-size:26px!important;margin:0!important;padding:0!important;color:#17421E;}.mori-editor-step p{font-size:16px;color:#526b54;margin:5px 0 0;}
.mori-editor-context{padding:18px 22px;border:1px solid #d0dfcc;border-left:5px solid #b79a65;border-radius:12px;background:#f6f3ed;margin:14px 0;}
.mori-editor-context small{display:block;font-size:14px;color:#526b54;}.mori-editor-context strong{display:block;font-size:23px;color:#17421E;margin:5px 0;overflow-wrap:anywhere;}.mori-editor-context p{font-size:15px;color:#526b54;margin:0;}
.st-key-budget_settings_editor [data-testid="stForm"]{padding:26px!important;border:1px solid #cbdcca!important;background:#ffffffed;border-radius:15px;box-shadow:0 6px 24px #17421e08;}
.st-key-budget_settings_editor [data-testid="stWidgetLabel"] p{font-size:16px!important;font-weight:700;color:#244b2a;}
.st-key-budget_settings_editor [data-testid="stFormSubmitButton"] button{min-height:52px;border-radius:10px;}
.st-key-budget_settings_editor [data-testid="stFormSubmitButton"] button p{font-size:18px!important;font-weight:700;}
.st-key-budget_settings_editor [data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"]{background:#17421E;color:white;border:1px solid #17421E;}
.mori-management-guide{display:flex;gap:12px;margin:8px 0 18px;}.mori-management-guide>div{flex:1;padding:14px;border:1px solid;border-radius:10px;}.mori-management-guide strong{display:block;font-size:17px;margin-bottom:5px;}.mori-management-guide span{font-size:14px;}.mori-management-guide .preparing{background:#fff7e8;border-color:#e4c17b;color:#835414;}.mori-management-guide .running{background:#edf6e9;border-color:#9ac291;color:#17421E;}.mori-management-guide .closed{background:#f0f3f6;border-color:#c3cdd8;color:#526174;}
@media(max-width:700px){.mori-management-guide{flex-direction:column;}.st-key-budget_settings_editor [data-testid="stForm"]{padding:16px!important;}.mori-editor-intro strong{font-size:22px;}}

.mori-account-title{font-size:26px;font-weight:800;color:#17421E;margin:8px 0 10px;}
.mori-account-combined{display:flex;align-items:center;gap:28px;flex-wrap:wrap;background:linear-gradient(110deg,#17421E,#294f2a);padding:22px 26px;border-radius:15px;border:1px solid #355d34;box-shadow:0 7px 24px #17421e16;margin:6px 0 18px;}
.mori-account-combined>strong{color:#dfd4bd;font-size:21px;}.mori-account-combined>div{flex:1;min-width:220px;}.mori-account-combined span{display:block;color:#d9e7d1;font-size:15px;}.mori-account-combined small{display:block;color:#d5e5c7;font-size:14px;margin-top:6px;}.mori-account-combined b{display:block;color:#fff;font-size:30px;line-height:1.5;margin-top:4px;overflow-wrap:anywhere;}
.st-key-budget_account_totals [data-testid="stMetric"]{padding:16px 14px;}.st-key-budget_account_totals [data-testid="stMetricValue"]{font-size:clamp(22px,2vw,30px)!important;}
@media(max-width:700px){.mori-account-combined{gap:16px;padding:18px;}.mori-account-combined b{font-size:26px;}}

/* Budget page: warm neutrals, quiet champagne details, clear section rhythm. */
[data-testid="stAppViewContainer"]:has(.st-key-budget_workspace){background:#f6f5f1!important;background-image:none!important;}
.mori-budget-hero{margin-bottom:36px;padding:34px 36px;}
.mori-budget-divider{height:1px;background:#dcd9d2;margin:24px 0;width:100%;}
.mori-budget-divider.subtle{background:#e8e5de;margin:24px 0;}
.st-key-budget_workspace{gap:12px;}
.st-key-budget_account_totals{padding:8px 0 12px;}
.st-key-budget_navigation{margin:8px 0 6px;padding:14px;background:#f0eeea;border-color:#d8d5ce;box-shadow:none;}
.st-key-budget_navigation [data-testid="stButton"] button{border-color:#d3d0c8!important;box-shadow:0 2px 5px #232a2010;}
.st-key-budget_navigation [data-testid="stButton"] button:hover{background:#f8f5ee!important;border-color:#b79a65!important;}
.st-key-budget_navigation [data-testid="stButton"] button[kind="primary"]:hover{background:#22532b!important;color:#fff!important;}
.st-key-budget_project_rail{background:#fbfaf7;border-color:#d8d5ce!important;box-shadow:0 5px 18px #232a2006;padding:22px 18px;}
.st-key-budget_project_rail [data-testid="stExpander"]{border-color:#dedbd4!important;}
.st-key-budget_workspace [class*="st-key-budget_project_card_"]{margin:12px 0 32px;padding:24px!important;background:#fffefa!important;border-color:#d8d5ce!important;border-radius:18px;box-shadow:0 6px 22px #232a2006;gap:20px;}
.st-key-budget_workspace [class*="st-key-budget_platform_"]{background:#faf9f6!important;padding:20px!important;border-color:#e0ddd6!important;border-radius:14px;gap:18px;}
.st-key-budget_workspace [data-testid="stMetric"]{background:#fffefa!important;border:1px solid #dedbd4!important;box-shadow:0 3px 12px #232a2005!important;padding:20px 18px;}
.st-key-budget_workspace [data-testid="stMetric"]:before{background:#b79a65!important;height:2px;width:30px;}
.st-key-budget_workspace [data-testid="stMetricValue"]{color:#17421E!important;}
.st-key-budget_workspace [data-testid="stMetricLabel"]{color:#5a625c!important;}
.st-key-budget_workspace [data-testid="stExpander"]{border-color:#dedbd4;}
.st-key-budget_workspace [data-testid="stForm"]{background:#fffefa!important;border-color:#d8d5ce!important;}
.mori-project-heading{margin-bottom:24px;padding:26px 28px;box-shadow:0 4px 12px #17421e0d;}
.mori-platform-heading{margin-bottom:16px;}
.mori-account-combined{margin:18px 0 28px;padding:26px 28px;}
.mori-editor-context{border-color:#ded6c7;}
.st-key-budget_settings_editor{gap:24px;}
@media(max-width:700px){.mori-budget-divider{margin:24px 0;}.mori-budget-divider.subtle{margin:18px 0;}.st-key-budget_workspace [class*="st-key-budget_project_card_"]{padding:16px!important;margin-bottom:24px;}.st-key-budget_workspace [class*="st-key-budget_platform_"]{padding:14px!important;}.mori-budget-hero{padding:24px 20px;}.mori-project-heading{padding:20px;}}
</style>"""


def render_budget_heading():
    st.markdown(BUDGET_STYLES, unsafe_allow_html=True)
    icon = ('<svg width="52" height="52" viewBox="0 0 56 56" fill="none" xmlns="http://www.w3.org/2000/svg">'
            '<defs><linearGradient id="ledger" x1="10" y1="6" x2="46" y2="50" gradientUnits="userSpaceOnUse">'
            '<stop stop-color="#f0f2d5"/><stop offset="1" stop-color="#b79a65"/></linearGradient></defs>'
            '<path d="M14 7h27a5 5 0 0 1 5 5v32a5 5 0 0 1-5 5H14a5 5 0 0 1-5-5V12a5 5 0 0 1 5-5Z" fill="#d8e8bc" fill-opacity=".07" stroke="url(#ledger)" stroke-width="2"/>'
            '<path d="M17 7v42M7 17h5M7 29h5M7 41h5M23 38h16" stroke="url(#ledger)" stroke-width="2" stroke-linecap="round"/>'
            '<path d="M32 17a9 9 0 1 0 9 9h-9v-9Z" stroke="url(#ledger)" stroke-width="2" stroke-linejoin="round"/>'
            '<path d="M36 13v9h9a9 9 0 0 0-9-9Z" fill="#d1bc94" fill-opacity=".75"/>'
            '<path d="M24 44h3M31 44h8" stroke="#b79a65" stroke-width="1.7" stroke-linecap="round"/></svg>')
    src = base64.b64encode(icon.encode()).decode()
    st.markdown('<header class="mori-budget-hero"><div class="mori-budget-hero-inner">'
                f'<div class="mori-budget-symbol" aria-hidden="true"><img src="data:image/svg+xml;base64,{src}" width="52" height="52" alt=""></div><div>'
                '<div class="hero-category">廣告智慧儀表板・專案管理</div>'
                '<h1>專案預算</h1><p>掌握每個專案的預算、花費與結餘</p>'
                '</div></div></header>', unsafe_allow_html=True)


def status_badge(scope, state):
    kind = {'準備中': 'preparing', '進行中': 'running', '已結案': 'closed'}[state]
    return f'<span class="mori-status {kind}"><span class="status-scope">{html.escape(scope)}</span>{state}</span>'


def project_header(name, phase, ads_phase):
    return (f'<div class="mori-project-heading"><div><div class="mori-project-kicker">廣告專案</div><h2 class="project-name">{html.escape(name)}</h2></div>'
            f'<div class="mori-status-pair">{status_badge("檔期", phase)}{status_badge("廣告", ads_phase)}</div></div>')


def select_budget_section(section):
    st.session_state.budget_section = section


def editor_step(number, title, subtitle):
    st.markdown(f'<div class="mori-editor-step"><span>{number}</span><div><h2>{title}</h2><p>{subtitle}</p></div></div>', unsafe_allow_html=True)


def editor_context(mode, name, note):
    st.markdown(f'<div class="mori-editor-context"><small>{html.escape(mode)}</small><strong>{html.escape(name)}</strong><p>{html.escape(note)}</p></div>', unsafe_allow_html=True)


def management_guide():
    st.markdown('<div class="mori-management-guide"><div class="preparing"><strong>準備中</strong><span>規劃設定・暫不檢查</span></div><div class="running"><strong>進行中</strong><span>依規則及廣告走期檢查</span></div><div class="closed"><strong>已結案</strong><span>停止檢查・保留紀錄</span></div></div>', unsafe_allow_html=True)


def render_budgets(settings, fetch, persist, documents=None, account_fetch=None):
    st.markdown(BUDGET_STYLES, unsafe_allow_html=True)
    with st.container(key='budget_workspace'):
        today = datetime.now(TAIPEI).date()
        groups = {g['id']: g for g in settings.get('project_groups', [])}
        accounts = {a['key']: a for a in settings['accounts']}
        plans = settings['projects']
        from mori.account_funding_ui import render_account_totals
        with st.container(key='budget_account_totals'):
            render_account_totals(settings, account_fetch)
        st.markdown('<div class="mori-budget-divider" role="separator"></div>', unsafe_allow_html=True)
        selected = st.session_state.setdefault('budget_section', 'overview')
        choices = [('overview', '預算總覽', ':material/dashboard:'),
                   ('edit', '新增／編輯設定', ':material/edit_square:'),
                   ('ledger', '預算調動與紀錄', ':material/swap_horiz:'),
                   ('invoices', '儲值與發票', ':material/receipt_long:')]
        with st.container(key='budget_navigation'):
            for column, (section, label, icon) in zip(st.columns(len(choices)), choices):
                column.button(label, icon=icon, key='budget_nav_' + section,
                              type='primary' if selected == section else 'secondary', width='stretch',
                              on_click=select_budget_section, args=(section,))
        st.markdown('<div class="mori-budget-divider" role="separator"></div>', unsafe_allow_html=True)
        if selected == 'overview':
            render_budget_overview(settings, fetch)
        elif selected == 'edit':
            if not accounts:
                st.info('請先到「帳號與串接」新增廣告帳號。')
                return
            with st.container(key='budget_settings_editor'):
                st.markdown('<div class="mori-editor-intro"><strong>設定專案，讓預算有清楚的歸屬</strong><p>先儲存專案檔期，再加入 Meta／Google 投放計畫。兩個區塊分別儲存。</p></div>', unsafe_allow_html=True)
                editor_step('01', '專案資料', '設定案名、完整檔期與管理狀態')
                pending_group = st.session_state.pop('pending_budget_group', None)
                if pending_group in groups:
                    st.session_state.budget_group_editor = pending_group
                group_id = st.selectbox('選擇專案', ['new'] + list(groups),
                                       format_func=lambda k: '＋新增專案' if k == 'new' else groups[k]['name'], key='budget_group_editor')
                group = groups.get(group_id, {})
                editor_context('正在編輯專案' if group else '新增專案', group.get('name', '建立新的廣告專案'),
                               f"已設定 {sum(p.get('group_id') == group_id for p in plans)} 個平台計畫" if group else '完成後，再往下新增平台投放計畫')
                with st.form('budget_group_' + group_id):
                    name = st.text_input('專案名稱', group.get('name', ''), placeholder='例如：感謝祭')
                    a, b = st.columns(2)
                    start = a.date_input('專案開始日', date.fromisoformat(group['start']) if group else today)
                    end = b.date_input('專案結束日', date.fromisoformat(group['end']) if group else today)
                    statuses = ['準備中', '進行中', '已結案']
                    status = st.selectbox('專案管理狀態（影響異常檢查）', statuses, index=statuses.index(group.get('status', '準備中')))
                    management_guide()
                    st.info('專案檔期＝活動的完整期間；廣告預熱與實際投放日期，填在下方平台計畫。')
                    st.caption('總覽的檔期狀態依日期判斷；這裡的管理狀態控制異常檢查。只結束廣告時，請結案下方平台計畫，保留仍在進行的專案檔期。')
                    if st.form_submit_button('儲存專案資料', type='primary', width='stretch'):
                        try:
                            updated = save_group(settings, {'id': group.get('id', uuid.uuid4().hex), 'name': name.strip(),
                                                            'start': str(start), 'end': str(end), 'status': status})
                            st.session_state.pending_budget_group = next(g['id'] for g in updated['project_groups'] if g['id'] not in groups) if not group else group['id']
                            persist(updated, notice='專案資料已儲存。接著在下方新增各平台投放計畫。')
                        except (AppError, ValueError) as exc:
                            st.error(str(exc))
                editor_step('02', '平台投放計畫', '每個廣告帳號各一筆：預算、廣告走期與認列條件')
                pending_plan = st.session_state.pop('pending_budget_plan', None)
                if pending_plan and any(p['id'] == pending_plan for p in plans):
                    st.session_state.budget_plan_editor = pending_plan
                if st.button('＋新增平台計畫'):
                    st.session_state.budget_plan_editor = 'new'
                def label(k):
                    p = next(x for x in plans if x['id'] == k)
                    parent = groups.get(p.get('group_id'), {}).get('name', '尚未歸入專案')
                    account = accounts[p['account_key']]
                    return f"{parent}｜{'Meta' if account['platform'] == 'meta' else 'Google Ads'}｜{account['name']}"
                plan_id = st.selectbox('選擇平台投放計畫', ['new'] + [p['id'] for p in plans],
                                      format_func=lambda k: '＋新增平台計畫' if k == 'new' else label(k), key='budget_plan_editor')
                plan = next((p for p in plans if p['id'] == plan_id), {})
                # Keep existing ungrouped records editable without silently reassigning them.
                group_options = [''] + list(groups)
                account_key = st.selectbox('廣告帳號', list(accounts),
                                  index=list(accounts).index(plan['account_key']) if plan else 0,
                                  format_func=lambda k: accounts[k]['name'], key='budget_plan_account_' + plan_id)
                google_plan = accounts[account_key]['platform'] == 'google'
                editor_context('正在編輯投放計畫' if plan else '新增投放計畫',
                               ('Google Ads' if google_plan else 'Meta') + '｜' + groups.get(plan.get('group_id'), {}).get('name', '請選擇所屬專案'),
                               accounts[account_key]['name'])
                with st.form('budget_plan_' + plan_id):
                    owner = st.selectbox('所屬專案', group_options,
                                         index=group_options.index(plan.get('group_id', '')),
                                         format_func=lambda k: groups[k]['name'] if k else '尚未歸入專案（保留既有設定）', key='budget_plan_owner_' + plan_id)
                    name = st.text_input('平台計畫名稱', plan.get('name', ''), placeholder='例如：含預熱（可留白）', help='專案名稱由上方專案資料管理；這裡只作為設定與紀錄識別，總覽不會重複顯示。留白時自動使用平台名稱。')
                    st.markdown('### 投放期間與預算')
                    a, b = st.columns(2)
                    ad_start = a.date_input('廣告開始日（可含預熱）', date.fromisoformat(plan['start']) if plan else today)
                    ad_end = b.date_input('廣告結束日', date.fromisoformat(plan['end']) if plan else today)
                    locked_budget = any(plan.get('id') in impacts(t) for t in settings.get('budget_transactions', []))
                    budget = st.number_input('平台投放預算（與廣告帳號同幣別，不另加稅／服務費）', min_value=0., value=float(plan.get('budget', 0)), step=1000., disabled=locked_budget)
                    if locked_budget:
                        st.caption('已有異動紀錄，原始預算已保留；請到「預算調動與紀錄」辦理追加／減列。')
                    st.caption('0 代表預算尚未設定，總覽會顯示「未設定」，不會計算花費百分比。')
                    st.markdown('### 哪些廣告要算進這個專案？')
                    st.caption('使用廣告名稱或文字條件辨識歸屬，避免把其他專案的花費一起算入。')
                    from mori.project_matching import FIELDS, conditions
                    if google_plan:
                        st.markdown('**Google 廣告認列條件**')
                        st.caption('一般 Google 廣告：廣告活動 → 廣告群組 → 廣告；PMax：廣告活動 → 素材群組。標題、說明、路徑依各格式提供的內容比對。')
                        st.caption('廣告 ID 是 API 回傳的數字編號；選擇廣告條件時，須填完整 ID 並完全相符。可先用文案預覽，在明細查看 ID；不必先找 ID 才能設定。')
                        st.caption('只計入上述廣告走期；同一廣告符合多個條件只算一次。廣告以 ID 辨識，不需要廣告名稱。')
                        mode = st.selectbox('條件組合', ['all', 'any'], index=int(plan.get('match_mode', 'all') == 'any'),
                                            format_func=lambda x: '全部條件都符合（AND）' if x == 'all' else '符合任一條件（OR）')
                        existing = conditions(plan)
                        options = [k for k in FIELDS if k != 'ad_name']
                        matching = []
                        for i in range(6):
                            condition = existing[i] if i < len(existing) else {}
                            left, right = st.columns([1, 2])
                            selected = condition.get('field', 'campaign_name')
                            field_i = left.selectbox(f'認列欄位 {i+1}', options, index=options.index(selected) if selected in options else 0,
                                                    format_func=lambda k: FIELDS[k], key=f'budget_field_{plan_id}_{i}')
                            text_i = right.text_input(f'包含文字／廣告 ID {i+1}', condition.get('text', ''),
                                                      placeholder='例如：感謝祭；多個文字擇一可填 桃園|新竹', key=f'budget_text_{plan_id}_{i}')
                            if text_i.strip():
                                matching.append({'field': field_i, 'text': text_i.strip()})
                        st.caption('空白條件不使用。標題含短標題與長標題；未提供的欄位不會虛構。PMax 命中素材群組文案時，認列的是該素材群組整筆花費，請勿將不同專案素材混放同一群組。')
                        st.caption('文案依 API 目前設定比對，無法還原歷史文案；若曾改稿，請核對廣告 ID 與走期。')
                        field, keyword = (matching[0]['field'], matching[0]['text']) if matching else ('campaign_name', '')
                    else:
                        options = ['campaign_name', 'adset_name', 'ad_name']
                        field = st.selectbox('名稱歸類欄位', options, index=options.index(plan.get('match_field', 'campaign_name')) if plan.get('match_field', 'campaign_name') in options else 0,
                                             format_func=lambda k: {'campaign_name': '行銷活動名稱（Meta）', 'adset_name': '廣告組合名稱（僅 Meta）', 'ad_name': '廣告名稱（僅 Meta）'}[k])
                        keyword = st.text_input('名稱包含（必填）', plan.get('keyword', ''), placeholder='例如：感謝祭')
                        matching, mode = [], 'all'
                    st.markdown('### 檢查狀態與儲存')
                    statuses = ['準備中', '進行中', '已結案']
                    status = st.selectbox('平台計畫狀態', statuses, index=statuses.index(plan.get('status', '準備中')))
                    st.caption('準備中：暫不執行異常檢查；進行中：依規則及廣告走期檢查；已結案：立即停止檢查。上層專案也必須為進行中，異常檢查才會啟用。')
                    st.caption('廣告結束日期會停止之後資料日的異常檢查，隔天仍會檢查最後一天；手動結案則立即停止檢查。')
                    if google_plan and st.form_submit_button('預覽認列廣告（不儲存）'):
                        try:
                            from mori.project_matching import validate_matching
                            draft = {**plan, 'id': plan.get('id', '_preview'), 'name': name.strip(),
                                     'account_key': account_key, 'start': str(ad_start), 'end': str(ad_end),
                                     'match_field': field, 'keyword': keyword.strip(), 'match_conditions': matching, 'match_mode': mode}
                            validate_matching(draft, 'google')
                            if ad_end < ad_start:
                                raise AppError('廣告結束日不可早於開始日。')
                            with st.spinner('讀取 Google 廣告並核對認列條件…'):
                                preview = collect_spend([p for p in plans if p['id'] != draft['id']] + [draft], accounts, fetch, today)[draft['id']]
                            if preview.get('error'):
                                raise AppError(preview['error'])
                            if preview.get('not_started'):
                                st.info('廣告尚未開始，尚無可預覽的資料。')
                            else:
                                st.success(f"預覽花費 {preview['currency']} {preview['spend']:,.2f}；尚未儲存設定。")
                                for warning in preview.get('warnings', []):
                                    st.warning(warning)
                                if preview['rows']:
                                    st.dataframe(pd.DataFrame(preview['rows']), hide_index=True, width='stretch')
                                else:
                                    st.info('沒有符合條件的廣告，請檢查走期與文字。')
                        except (AppError, ValueError) as exc:
                            st.error(str(exc))
                    if st.form_submit_button('儲存平台計畫', type='primary', width='stretch'):
                        try:
                            if not owner and not plan:
                                raise AppError('請先建立並選擇所屬專案，再新增平台計畫。')
                            updated = save_plan(settings, {'id': plan.get('id', uuid.uuid4().hex), 'name': name.strip() or ('Google Ads' if google_plan else 'Meta'),
                                                          'account_key': account_key, 'group_id': owner, 'start': str(ad_start),
                                                          'end': str(ad_end), 'budget': budget, 'match_field': field,
                                                          'keyword': keyword.strip(), 'status': status,
                                                          'match_conditions': matching, 'match_mode': mode})
                            st.session_state.pending_budget_plan = next(p['id'] for p in updated['projects'] if p['id'] not in {x['id'] for x in plans}) if not plan else plan['id']
                            persist(updated, notice='平台計畫已儲存。預算總覽會自動讀取最新花費。')
                        except (AppError, ValueError) as exc:
                            st.error(str(exc))
                st.download_button('匯出設定備份（不含權杖）', json.dumps(settings, ensure_ascii=False, indent=2),
                                   'mori-settings.json', on_click='ignore')

        elif selected == 'ledger':
            render_ledger(settings, fetch, persist)
        elif selected == 'invoices':
            from mori.invoice_ui import render_invoices
            render_invoices(settings, documents, persist)


def select_budget_project(nav_id):
    st.session_state.budget_selected_project = nav_id


def render_project_rail(settings, today):
    from mori.project_navigation import STATES, project_entries, project_years, filter_entries
    entries = project_entries(settings, today)
    years = project_years(entries)
    with st.container(key='budget_project_rail', border=True):
        st.markdown('<div class="mori-rail-title">專案導覽</div><div class="mori-rail-subtitle">選年度，快速掌握每個案子</div>', unsafe_allow_html=True)
        year_options = [None] + years
        if st.session_state.get('budget_nav_year') not in year_options:
            st.session_state.budget_nav_year = today.year if today.year in years else (years[0] if years else None)
        elif 'budget_nav_year' not in st.session_state:
            st.session_state.budget_nav_year = today.year if today.year in years else (years[0] if years else None)
        year = st.selectbox('專案年度', year_options, format_func=lambda y: f'{y} 年' if y else '所有年度', key='budget_nav_year')
        query = st.text_input('搜尋專案', placeholder='輸入名稱，例如：感謝祭', key='budget_nav_search')
        state = st.selectbox('檔期狀態', ['全部', *STATES], key='budget_state_filter')
        visible = filter_entries(entries, year, query, state)
        valid_ids = {e['nav_id'] for e in visible}
        selected = st.session_state.get('budget_selected_project', 'all')
        if selected != 'all' and selected not in valid_ids:
            selected = 'all'
        st.session_state.budget_selected_project = selected
        st.button(f'查看全部符合專案（{len(visible)}）', key='budget_project_all', width='stretch',
                  type='primary' if selected == 'all' else 'secondary',
                  on_click=select_budget_project, args=('all',))
        if not visible:
            st.info('找不到符合的專案，請調整年度、狀態或搜尋文字。')
        colors = {'進行中': '#2d7637', '準備中': '#9a6418', '已結案': '#64748b'}
        with st.container(height=480, border=False, key='budget_project_list'):
            for phase in STATES:
                members = [e for e in visible if e['phase'] == phase]
                if not members:
                    continue
                with st.expander(f'{phase} · {len(members)}', expanded=phase != '已結案' or any(e['nav_id'] == selected for e in members)):
                    st.markdown(f'<div class="mori-rail-status" style="color:{colors[phase]}">{phase}專案</div>', unsafe_allow_html=True)
                    for e in members:
                        st.button(e['name'] + ('（未歸類）' if e['plan_id'] else ''),
                                  key='budget_project_' + e['nav_id'], width='stretch',
                                  type='primary' if selected == e['nav_id'] else 'secondary',
                                  help=f"檔期 {e['start']} ～ {e['end']}",
                                  on_click=select_budget_project, args=(e['nav_id'],))
        st.caption('以專案檔期分類；廣告投放狀態另列。跨年專案可在兩個年度找到，金額仍依完整廣告走期呈現。')
    chosen = visible if selected == 'all' else [e for e in visible if e['nav_id'] == selected]
    return chosen, year


@st.fragment
def render_budget_overview(settings, fetch):
    rail, content = st.columns([1, 3.7], gap='large')
    with rail:
        entries, year = render_project_rail(settings, datetime.now(TAIPEI).date())
    with content:
        with st.container(key='budget_project_content'):
            st.markdown('<div class="mori-results-heading">' + (f'{year} 年' if year else '所有年度') +
                        f' · {len(entries)} 個專案</div>', unsafe_allow_html=True)
            render_budget_results(settings, fetch, entries)


def render_budget_results(settings, fetch, entries):
    today = datetime.now(TAIPEI).date()
    groups = {g['id']: g for g in settings.get('project_groups', [])}
    accounts = {a['key']: a for a in settings['accounts']}
    plans = settings['projects']
    manual = st.button('重新讀取', disabled=not bool(plans), help='首次開啟自動載入；之後按此按鈕取得平台最新花費。')
    entered = st.session_state.pop('budget_refresh_requested', False)
    view = st.session_state.get('budget_view')
    now = datetime.now(TAIPEI)
    if refresh_due(settings, view, now, force=manual or entered):
        started = now.isoformat()
        with st.spinner('自動讀取各平台最新花費（含今日）…'):
            results = collect_spend(plans, accounts, fetch, today)
        completed = datetime.now(TAIPEI)
        view = {'key': configuration_key(settings), 'results': results,
                'requested_at': started, 'at': completed.isoformat(), 'date': str(today)}
        st.session_state.budget_view = view
    fresh = view and view.get('key') == configuration_key(settings) and view.get('date') == str(today)
    results = view['results'] if fresh else {}
    if fresh:
        stamp = datetime.fromisoformat(view['at']).astimezone(TAIPEI).strftime('%Y/%m/%d %H:%M:%S')
        errors = sum(bool(r.get('error')) for r in results.values())
        if errors:
            st.warning(f'{errors} 個平台計畫讀取失敗，未列為零花費；請稍後按「重新讀取」。')
        st.caption(f'資料讀取時間 {stamp}（台灣時間）・含今日未完整花費・首次自動載入，後續按「重新讀取」更新')
    st.caption('數據依廣告平台最新回報，可能延遲或事後回補，非逐秒最終帳單；請留意剩餘預算。異常通知仍檢查昨天完整資料。')
    money_filter = st.selectbox('預算狀況', ['全部', '已超支', '廣告結束有結餘'], key='budget_money_filter')
    def visible(plan):
        if money_filter == '全部':
            return True
        summary = plan_summary(plan, results.get(plan['id']), today, settings)
        if summary['remaining'] is None:
            return False
        return summary['remaining'] < 0 if money_filter == '已超支' else (summary['budget'] > 0 and summary['remaining'] > 0 and today > date.fromisoformat(plan['end']))
    if not groups and not plans:
        st.info('先到「新增／編輯設定」建立專案，再分別加入 Meta、Google 投放計畫。')
    visible_plans = {e['plan_id'] for e in entries if e['plan_id']}
    shown = 0
    for entry in entries:
        gid = entry['group_id']
        if not gid:
            continue
        group = groups[gid]
        children = [p for p in plans if p.get('group_id') == gid]
        if money_filter != '全部' and not any(visible(p) for p in children):
            continue
        shown += 1
        with st.container(border=True, key='budget_project_card_' + gid):
            phase = period_state(group['start'], group['end'], today)
            ads_phase = advertising_state(children, today)
            st.markdown(project_header(group['name'], phase, ads_phase), unsafe_allow_html=True)
            from mori.invoice_ui import funding_badge
            if children:
                st.markdown('<div class="mori-status-pair">' + ''.join(funding_badge(settings, p['id'], 'Meta' if accounts[p['account_key']]['platform'] == 'meta' else 'Google Ads') for p in children) + '</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="mori-period-dates">檔期走期　{html.escape(group["start"])} ～ {html.escape(group["end"])}</div>', unsafe_allow_html=True)
            elapsed = time_progress(group['start'], group['end'], today)
            st.progress(elapsed, text=f'專案時間進度 {elapsed:.0%}（含今天，與花費分開計算）')
            if children and all(today > date.fromisoformat(p['end']) for p in children):
                st.caption('各平台投放已結束，保留實際花費與結餘。')
            if not children:
                st.caption('尚未加入平台投放計畫。請到設定頁加入 Meta 或 Google。')
            if children:
                st.markdown('<div class="mori-budget-divider subtle" role="separator"></div>', unsafe_allow_html=True)
                render_group_totals(children, results, today, settings)
                st.markdown('<div class="mori-budget-divider subtle" role="separator"></div>', unsafe_allow_html=True)
                if money_filter != '全部':
                    st.caption('以下保留本專案所有平台，方便比較；預算狀況篩選用來挑出專案。')
                ordered = sorted(children, key=lambda p: (accounts[p['account_key']]['platform'] != 'meta', p['account_key']))
                # One envelope and one project title. Native columns stack on mobile.
                for offset in range(0, len(ordered), 2):
                    columns = st.columns(min(2, len(ordered) - offset), gap='medium')
                    for col, plan in zip(columns, ordered[offset:offset+2]):
                        with col:
                            with st.container(border=True, key='budget_platform_' + plan['id']):
                                render_plan(plan, accounts, results.get(plan['id']), today, settings, compact=True)
    ungrouped = [p for p in plans if p['id'] in visible_plans and visible(p)]
    if ungrouped:
        st.subheader('既有平台計畫｜尚未歸入專案')
        st.caption('既有資料及異常規則連結均保留。可在設定頁編輯此計畫，指定所屬專案。')
        for plan in ungrouped:
            with st.container(border=True):
                render_plan(plan, accounts, results.get(plan['id']), today, settings)
    if entries and not shown and not ungrouped:
        st.info('目前選取的專案沒有符合此預算狀況；可將「預算狀況」切回全部。')
    st.caption('進度＝實際花費 ÷ 調整後可用預算。金額不另加稅與服務費，不等於儲值餘額。不同專案篩選可能重疊，因此不加總為全帳號花費。走期狀態依設定日期判斷，不代表平台即時開關狀態。')

def render_group_totals(plans, results, today, settings):
    data = group_summary(plans, results, today, settings)
    a, b, c, d = st.columns(4)
    money = lambda v: f'{v:,.2f}' if v is not None else '—'
    a.metric('累積預算', money(data['budget']))
    b.metric('累計總花費', money(data['spend']))
    c.metric('專案超支' if data['remaining'] is not None and data['remaining'] < 0 else '專案結餘',
             money(abs(data['remaining'])) if data['remaining'] is not None else '—')
    d.metric('整體花費進度', f"{data['ratio']:.1%}" if data['ratio'] is not None else '—')
    if data['reason']:
        st.caption(data['reason'])
    else:
        st.caption(f"{data['currency']}｜以下平台金額的專案合計，已包含預算轉入／轉出。")


def render_plan(plan, accounts, result, today, settings, compact=False):
    account = accounts[plan['account_key']]
    platform = 'Meta' if account['platform'] == 'meta' else 'Google Ads'
    data = plan_summary(plan, result, today, settings)
    from mori.invoice_ui import funding_badge, proof_caption
    # Project title belongs to the outer envelope; plan name stays in the details.
    phase = period_state(plan['start'], plan['end'], today, plan.get('status') == '已結案')
    st.markdown(f'<div class="mori-platform-heading"><span>{platform}</span>{status_badge("投放", phase)}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="mori-ad-dates">廣告走期　{html.escape(plan["start"])} ～ {html.escape(plan["end"])}</div>', unsafe_allow_html=True)
    if (result or {}).get('includes_today'):
        st.caption('即時數據・含今日未完整花費，平台可能延遲回報或回補。')
    st.markdown(funding_badge(settings, plan['id']), unsafe_allow_html=True)
    proof_caption(settings, plan['id'])
    from mori.invoices import invoice_summary
    proof = invoice_summary(settings, plan['id'])
    if data['currency'] and proof['totals']:
        if set(proof['totals']) != {data['currency']}:
            st.warning('發票登錄幣別與平台回報不一致，請至「儲值與發票」核對；不同幣別不相加。')
        elif data['budget'] > 0:
            registered = proof['totals'][data['currency']]
            st.caption(f"發票認列／可用預算：{data['currency']} {registered:,.2f}／{data['budget']:,.2f}；有發票不代表全額到位。")
    if not plan.get('group_id'):
        st.caption('平台計畫：' + plan['name'])
    warnings = (result or {}).get('warnings', [])
    if any('今日活動與明細' in w for w in warnings):
        st.warning('今日活動與明細回報尚未同步，目前依明細認列；後續更新可能回補。')
    if any('未提供全部' in w for w in warnings):
        st.warning('部分廣告缺少選定的文案欄位；請展開下方明細核對未納入的花費。')
    if result and result.get('error'):
        st.error(account['name'] + '：' + result['error'])
    funds = balance(settings, plan['id'], today)
    if compact:
        a, b = st.columns(2)
        c, d = st.columns(2)
    else:
        a, b, c, d = st.columns(4)
    initialized = funds['original'] > 0 or any(plan['id'] in impacts(t) for t in settings.get('budget_transactions', []))
    a.metric('可用預算', f"{data['budget']:,.2f}" if initialized else '未設定')
    b.metric('累計花費', f"{data['spend']:,.2f}" if data['spend'] is not None else '—')
    c.metric('超支金額' if data['remaining'] is not None and data['remaining'] < 0 else '剩餘預算',
             f"{abs(data['remaining']):,.2f}" if data['remaining'] is not None and initialized else '—')
    d.metric('花費進度', f"{data['ratio']:.1%}" if data['ratio'] is not None else '—')
    if data['ratio'] is not None:
        ratio = data['ratio']
        color = '#c34236' if ratio > 1 else '#17421E'
        st.markdown(f'<div style="height:8px;background:#e2e9df;border-radius:10px;margin:12px 0 8px" role="img" aria-label="花費進度 {ratio:.1%}">'
                    f'<div style="width:{max(0,min(100,ratio*100)):.3f}%;height:100%;background:{color};border-radius:10px"></div></div>', unsafe_allow_html=True)
        st.caption(f'花費 {ratio:.1%}・廣告走期進度 {data["time_ratio"]:.0%}（含資料日）')
        if ratio > 1:
            st.warning('已超過此平台預算。')
    history = records(settings, plan['id'])
    st.markdown('<div class="mori-budget-divider subtle" role="separator"></div>', unsafe_allow_html=True)
    with st.expander('預算組成與調動紀錄'):
        st.caption(f"原始 {funds['original']:,.2f} ＋ 轉入 {funds['incoming']:,.2f} － 轉出 {funds['outgoing']:,.2f} ＋ 追加／減列 {funds['adjustment']:,.2f} ＝ 可用 {funds['adjusted']:,.2f}")
        if not history.empty:
            st.dataframe(history, hide_index=True, width='stretch')
        else:
            st.caption('尚無預算異動。')
    detail_title = '認列說明與廣告明細' + (f'（{len(warnings)} 項提醒）' if warnings else '')
    with st.expander(detail_title):
        st.caption(f"廣告帳號：{account['name']}｜原平台計畫名稱：{plan['name']}")
        for warning in warnings:
            st.warning(warning)
        if result and result.get('until'):
            st.caption(f"{data['currency'] or '帳號幣別'}｜資料 {result['since']} ～ {result['until']}｜時區 {result.get('timezone') or '未回傳'}")
            rows = result['rows']
            if result.get('spend_basis') == 'meta_ad_whole_period':
                st.caption(f"核對口徑：每則廣告的整段走期花費｜{len(rows)} 則廣告｜加總 {result['currency']} {result['spend_raw']}。未先將每日金額取整。")
            if rows:
                df = pd.DataFrame(rows)
                columns = [k for k in ['date', 'date_stop', 'channel', 'ad_type', 'attribution_unit', 'campaign_id', 'campaign_name', 'adset_id', 'adset_name', 'ad_id', 'ad_name', 'asset_group_name', 'asset_group_id', 'headlines', 'descriptions', 'paths', 'spend_raw', 'spend', 'currency'] if k in df]
                detail = df[columns].rename(columns={'date': '資料開始日' if result.get('spend_basis') == 'meta_ad_whole_period' else '日期', 'date_stop': '資料結束日', 'campaign_id': '活動 ID', 'adset_id': '群組 ID', 'campaign_name': '廣告活動' if account['platform'] == 'google' else '行銷活動', 'adset_name': '廣告群組' if account['platform'] == 'google' else '廣告組合',
                                                        'ad_name': '廣告', 'asset_group_name': '素材群組', 'asset_group_id': '素材群組 ID', 'ad_type': '廣告格式', 'attribution_unit': '花費認列單位', 'channel': '類型', 'ad_id': '廣告 ID', 'headlines': '目前標題', 'descriptions': '目前說明', 'paths': '目前路徑', 'spend_raw': 'API 原始花費', 'spend': '花費', 'currency': '幣別'})
                st.dataframe(detail, hide_index=True, width='stretch')
                # Neutralize formula-leading text before opening an exported CSV in Excel.
                export = detail.map(lambda v: "'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v)
                st.download_button('下載花費核對明細 CSV', export.to_csv(index=False).encode('utf-8-sig'),
                                   file_name=f"spend-{plan['id']}-{result['since']}-{result['until']}.csv",
                                   mime='text/csv', key='budget_spend_export_' + plan['id'])
            else:
                st.info('此走期與條件沒有符合的廣告。請核對篩選條件。')
        elif result and result.get('not_started'):
            st.caption('廣告尚未開始，尚未查詢花費。')
        else:
            st.caption('尚未取得實際花費；進度與結餘暫不計算。')
