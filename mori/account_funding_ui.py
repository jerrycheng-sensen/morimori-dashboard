"""Always-visible account totals above the project budget navigation."""
from datetime import datetime
import html

import streamlit as st

from mori.account_funding import default_since, view_key, collect_accounts, summary_totals, project_kpis
from mori.core import TAIPEI
from mori.money_display import money_text, money_html, money_metric, money_note
from mori.budget_visuals import platform_brand, totals_progress


def open_invoices(plan_id=None):
    st.session_state.budget_section = 'invoices'
    if plan_id:
        st.session_state.pending_invoice_plan = plan_id
    st.rerun()


def format_totals(values, compact=False, platform='combined'):
    if not values:
        return '—'
    if compact and len(values) > 1:
        return '分幣別列示'
    return '；'.join((f'{cur} {money_text(amount, platform)}' if not cur.startswith('?') else f'{money_text(amount, platform)}（帳號幣別待確認）')
                    for cur, amount in sorted(values.items()))


def kpi_card(label, values, note, kind):
    deficit = kind == 'remaining' and values is not None and any(v < 0 for v in values.values())
    state = ' deficit' if deficit else ''
    if values is None:
        numbers = '<strong class="mori-kpi-empty">待資料完整</strong>'
    elif not values:
        numbers = '<strong class="mori-kpi-empty">尚未建立</strong>'
    else:
        numbers = ''.join('<div class="mori-kpi-number"><small>' + html.escape(cur if not cur.startswith('?') else '幣別待確認') +
                          '</small><strong>' + money_html(amount) + '</strong></div>' for cur, amount in sorted(values.items()))
    return '<article class="mori-kpi-card ' + kind + state + '"><h3>' + label + '</h3>' + numbers + '<p>' + note + '</p></article>'


@st.fragment
def render_account_totals(settings, fetch, project_fetch=None, persist=None):
    today = datetime.now(TAIPEI).date()
    suggested = default_since(settings, today)
    st.markdown('<div class="mori-account-title">雙平台預算總覽</div>', unsafe_allow_html=True)
    with st.expander('檢查是否有廣告花費漏列專案'):
        st.caption('找出有花費、卻還沒加入專案的廣告，再選擇所屬專案歸案。')
        custom = st.checkbox('改選查詢開始日', key='account_totals_custom_since')
        since = st.date_input('查詢開始日', suggested, max_value=today, key='account_totals_since') if custom else suggested
        st.caption(f'查詢期間：{since} ～ {today}。與廣告後台核對時，請選相同日期。')
        st.caption('預設從系統最早的廣告計畫或發票紀錄查到今天。這裡的日期只影響帳號查詢，不會改變專案的預算、花費與剩餘金額。')
        from mori.unassigned_ui import render_unassigned
        render_unassigned(settings, project_fetch, persist, since, today)
    from mori.unassigned_ui import audit_key, pending_units
    audit = st.session_state.get('unassigned_view', {})
    if audit.get('key') == audit_key(settings, since, today):
        count = len(pending_units(audit['result']['pending']))
        if count:
            st.warning(f'有 {count} 則廣告／素材群組的花費尚未歸案，請展開上方檢查區處理。')
    manual = st.button('重新讀取全部預算', key='account_totals_reload', disabled=not bool(settings['accounts']),
                       help='取得各專案與廣告帳號最新回報的花費，包含今天。')
    if manual:
        st.session_state.pop('unassigned_view', None)
    key = view_key(settings, since, today)
    view = st.session_state.get('budget_account_view', {})
    if fetch is not None and (manual or view.get('key') != key):
        with st.spinner('讀取雙平台帳號總花費（含今日）…'):
            reports = collect_accounts(settings, fetch, since, today)
        view = {'key': key, 'results': reports, 'at': datetime.now(TAIPEI).isoformat()}
        st.session_state.budget_account_view = view
    reports = view.get('results', {}) if view.get('key') == key else {}
    platforms, _ = summary_totals(settings, reports, since, today)
    from mori.budget_ui import load_budget_view
    project_view = load_budget_view(settings, project_fetch, force=manual) if project_fetch is not None else {}
    kpis = project_kpis(settings, (project_view or {}).get('results', {}), reports, today)
    budget = kpis['planning']
    stamp = datetime.fromisoformat(view['at']).strftime('%Y/%m/%d %H:%M') if view.get('at') and view.get('key') == key else '尚未讀取'
    total = kpis['combined']
    counts = len({p.get('group_id') or 'plan:' + p['id'] for p in settings['projects']})
    project_stamp = datetime.fromisoformat(project_view['at']).strftime('%Y/%m/%d %H:%M') if project_view and project_view.get('at') else '尚未讀取'
    cards = kpi_card('累計預算', total['budget'], '已建立專案的調整後預算', 'budget')
    cards += kpi_card('累計花費', total['spent'], '依同一批專案的廣告走期認列', 'spend')
    cards += kpi_card('剩餘預算', total['remaining'], '累計預算 − 累計花費；負數表示超支', 'remaining')
    with st.container(border=True, key='budget_summary_panel'):
        st.markdown('<section class="mori-kpi-panel" aria-label="雙平台專案合計"><header><div><span class="mori-kpi-eyebrow">PROJECT BUDGET</span>'
                    '<h2>雙平台專案合計</h2></div><span class="mori-kpi-count">' + f'{counts} 個專案・{budget["plans"]} 個平台計畫' +
                    '</span></header><div class="mori-kpi-grid">' + cards + '</div><footer>' +
                    f'專案資料讀取 {project_stamp}（台灣時間）｜待補發票：{budget["missing_projects"]} 個專案・{len(budget["pending"])} 個平台計畫' +
                    '</footer></section>', unsafe_allow_html=True)
        for value in kpis['platforms'].values():
            for error in value['errors']:
                st.warning(error)
        if budget['unset']:
            st.caption(f"另有 {budget['unset']} 個平台計畫尚未設定預算，請到新增／編輯設定補齊。")
        st.markdown(totals_progress(total['budget'], total['spent'], total['remaining']), unsafe_allow_html=True)
        st.markdown('<div class="mori-summary-platform-label">依平台檢視</div>', unsafe_allow_html=True)
        for column, platform in zip(st.columns(2), ('meta', 'google')):
            value = platforms[platform]
            planning = budget['platforms'][platform]
            with column:
                with st.container(border=True, key='budget_summary_' + platform):
                    st.markdown('<div class="mori-platform-heading">' + platform_brand(platform) + '</div>', unsafe_allow_html=True)
                    pending_count = len({r['project_key'] for r in planning['pending']})
                    st.caption(f"{value['accounts']} 個廣告帳號｜{planning['plans']} 個平台計畫")
                    project = kpis['platforms'][platform]
                    a, b = st.columns(2)
                    def metric(target, label, values, empty='—'):
                        if values:
                            for cur, amount in sorted(values.items()):
                                money_metric(target, label, amount, platform, prefix=(cur + ' ') if not cur.startswith('?') else '')
                        else:
                            money_metric(target, label, None, platform, empty=empty)
                    metric(a, '累計預算', planning['totals'], '尚未建立預算')
                    metric(b, '累計花費', project['spent'])
                    metric(st, '剩餘預算', project['remaining'])
                    st.markdown(totals_progress(project['budget'], project['spent'], project['remaining']), unsafe_allow_html=True)
                    a.caption(f"待補發票：{pending_count} 個專案・{len(planning['pending'])} 個平台計畫")
                    b.caption('專案認列花費・含今日已回報數據')
                    if len(planning['totals']) != 1:
                        money_note(st, '預算：' + format_totals(planning['totals'], platform=platform))
                    if len(project['spent'] or {}) > 1:
                        money_note(st, '專案花費：' + format_totals(project['spent'], platform=platform))
                    with st.expander('查看帳號全部花費'):
                        money_note(st, '帳號全部花費：' + (format_totals(value['spent'], platform=platform) if value['spent'] is not None else '尚未完整取得'))
                        st.caption(f'{since} ～ {today}｜帳號資料讀取 {stamp}（台灣時間）；包含還沒加入專案的廣告；只供核對，不影響上方剩餘預算。')
                    if not value['accounts']:
                        st.caption('尚未新增此平台的廣告帳號。')
                    for error in value['errors']:
                        st.warning(error)
    st.caption('主區預算、花費與剩餘採同一批已建立專案，不受專案年度、狀態或搜尋影響；剩餘預算不等於平台錢包餘額。資料未完整、預算未設定或認列重疊時，暫不顯示剩餘金額。')
    if st.button('登錄／管理發票', key='account_totals_invoices', icon=':material/receipt_long:', type='primary'):
        open_invoices()
    with st.expander(f"查看待補發票清單（{budget['missing_projects']} 個專案）"):
        if not budget['pending']:
            st.success('目前所有平台計畫都已登錄至少一筆有效發票。' if budget['plans'] else '尚未建立平台計畫。')
        for row in budget['pending']:
            label = f"{row['name']}｜{'Meta' if row['platform'] == 'meta' else 'Google Ads'}｜{row['account_name']}"
            left, right = st.columns([4, 1])
            left.write(label)
            if right.button('補發票', key='pending_invoice_' + row['plan_id'], width='stretch'):
                open_invoices(row['plan_id'])
        st.caption('待補＝此平台計畫尚無有效發票；作廢的發票不算。已登錄部分金額的計畫仍維持既有已儲值判定，可至發票頁查看認列明細。')
    if manual:
        st.rerun()
