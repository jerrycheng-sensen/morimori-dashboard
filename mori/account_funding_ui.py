"""Always-visible account totals above the project budget navigation."""
from datetime import datetime
import html

import streamlit as st

from mori.account_funding import default_since, view_key, collect_accounts, summary_totals, project_kpis
from mori.core import TAIPEI
from mori.budget_visuals import platform_brand, totals_progress


def open_invoices(plan_id=None):
    st.session_state.budget_section = 'invoices'
    if plan_id:
        st.session_state.pending_invoice_plan = plan_id
    st.rerun()


def format_totals(values, compact=False):
    if not values:
        return '—'
    if compact and len(values) > 1:
        return '分幣別列示'
    return '；'.join((f'{cur} {amount:,.2f}' if not cur.startswith('?') else f'{amount:,.2f}（帳號幣別待確認）')
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
                          '</small><strong>' + f'{amount:,.2f}' + '</strong></div>' for cur, amount in sorted(values.items()))
    return '<article class="mori-kpi-card ' + kind + state + '"><h3>' + label + '</h3>' + numbers + '<p>' + note + '</p></article>'


@st.fragment
def render_account_totals(settings, fetch, project_fetch=None):
    today = datetime.now(TAIPEI).date()
    suggested = default_since(settings, today)
    st.markdown('<div class="mori-account-title">雙平台預算總覽</div>', unsafe_allow_html=True)
    with st.expander('帳號對帳期間與計算說明'):
        custom = st.checkbox('自行指定統計起日', key='account_totals_custom_since')
        since = st.date_input('帳號總覽統計起日', suggested, max_value=today, key='account_totals_since') if custom else suggested
        st.caption('預設從最早的平台計畫開始日或發票儲值登錄日（含作廢歷史）起算，至今日；不是帳號成立以來的歷史總額。')
        st.caption('累計預算＝所有已建立平台計畫的調整後預算，含準備中與已結案，不受本區花費起日篩選。內部轉移只改分配，雙平台合計不會重複增加。')
        st.caption('主區三項指標採同一批專案：累計花費按各專案廣告走期認列；剩餘預算＝累計預算－累計花費。完整帳號花費另列於下方對帳明細，才使用這裡的統計起日；不混入專案剩餘預算。')
    manual = st.button('重新讀取全部預算', key='account_totals_reload', disabled=not bool(settings['accounts']),
                       help='更新上方帳號總花費；預算總覽也會更新各專案。平常切換專案不重抓資料。')
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
                    a.metric('累計預算', format_totals(planning['totals'], compact=True) if planning['plans'] else '尚未建立預算')
                    b.metric('累計花費', format_totals(project['spent'], compact=True) if project['spent'] is not None else '—')
                    st.metric('剩餘預算', format_totals(project['remaining'], compact=True) if project['remaining'] is not None else '—')
                    st.markdown(totals_progress(project['budget'], project['spent'], project['remaining']), unsafe_allow_html=True)
                    a.caption(f"待補發票：{pending_count} 個專案・{len(planning['pending'])} 個平台計畫")
                    b.caption('專案認列花費・含今日已回報數據')
                    if len(planning['totals']) != 1:
                        st.caption('預算：' + format_totals(planning['totals']))
                    if len(project['spent'] or {}) > 1:
                        st.caption('專案花費：' + format_totals(project['spent']))
                    with st.expander('完整帳號花費（供對帳）'):
                        st.write('帳號花費：' + (format_totals(value['spent']) if value['spent'] is not None else '尚未完整取得'))
                        st.caption(f'{since} ～ {today}｜帳號資料讀取 {stamp}（台灣時間）；包含未建立為專案的廣告，不計入上方專案剩餘預算。')
                    if not value['accounts']:
                        st.caption('尚未新增此平台的廣告帳號。')
                    for error in value['errors']:
                        st.warning(error)
    st.caption('主區預算、花費與剩餘採同一批已建立專案，不受下方年度、狀態、搜尋影響；剩餘預算不等於平台錢包餘額。資料未完整、預算未設定或認列重疊時，暫不顯示剩餘金額。')
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
