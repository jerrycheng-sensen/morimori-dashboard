"""Always-visible account totals above the project budget navigation."""
from datetime import datetime
import html

import streamlit as st

from mori.account_funding import default_since, view_key, collect_accounts, summary_totals, project_budget_totals
from mori.core import TAIPEI


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


@st.fragment
def render_account_totals(settings, fetch):
    today = datetime.now(TAIPEI).date()
    suggested = default_since(settings, today)
    st.markdown('<div class="mori-account-title">雙平台預算總覽</div>', unsafe_allow_html=True)
    with st.expander('統計期間與計算說明'):
        custom = st.checkbox('自行指定統計起日', key='account_totals_custom_since')
        since = st.date_input('帳號總覽統計起日', suggested, max_value=today, key='account_totals_since') if custom else suggested
        st.caption('預設從最早的平台計畫開始日或發票儲值登錄日（含作廢歷史）起算，至今日；不是帳號成立以來的歷史總額。')
        st.caption('累積預算＝所有已建立平台計畫的調整後預算，含準備中與已結案，不受本區花費起日篩選。內部轉移只改分配，雙平台合計不會重複增加。')
        st.caption('累計花費＝上述期間的完整帳號花費，可能包含未建立專案的廣告；與累積預算的範圍不同，不直接相減作為餘額。發票驗收獨立追蹤，不影響預算金額，也不代表平台錢包餘額。')
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
    budget = project_budget_totals(settings, reports, today)
    stamp = datetime.fromisoformat(view['at']).strftime('%Y/%m/%d %H:%M') if view.get('at') and view.get('key') == key else '尚未讀取'
    st.caption(f'帳號統計期間 {since} ～ {today}｜資料讀取時間 {stamp}（台灣時間）｜依帳號時區、含今日已回報花費；平台可能延遲或回補')
    budget_text = format_totals(budget['totals']) if budget['plans'] else '尚未建立預算'
    if budget['plans'] and budget['unset'] == budget['plans']:
        budget_text = '尚未設定預算'
    existing = [p for p in platforms.values() if p['accounts']]
    spent = {}
    known = bool(existing) and all(p['spent'] is not None for p in existing)
    if known:
        for value in existing:
            for cur, amount in value['spent'].items():
                spent[cur] = spent.get(cur, 0) + amount
    cost_text = format_totals(spent) if known else '尚未取得完整花費'
    st.markdown('<div class="mori-account-combined"><strong>雙平台合計</strong><div><span>累積預算</span><b>' + html.escape(budget_text) +
                '</b><small>' + f"待補發票：{budget['missing_projects']} 個專案・{len(budget['pending'])} 個平台計畫" +
                '</small></div><div><span>累計花費</span><b>' + html.escape(cost_text) + '</b><small>完整廣告帳號・依上方統計期間</small></div></div>', unsafe_allow_html=True)
    if budget['unset']:
        st.caption(f"另有 {budget['unset']} 個平台計畫尚未設定預算，請到新增／編輯設定補齊。")
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
    for column, platform in zip(st.columns(2), ('meta', 'google')):
        value = platforms[platform]
        planning = budget['platforms'][platform]
        with column:
            with st.container(border=True):
                st.subheader('Meta' if platform == 'meta' else 'Google Ads')
                pending_count = len({r['project_key'] for r in planning['pending']})
                st.caption(f"{value['accounts']} 個廣告帳號｜{planning['plans']} 個平台計畫")
                a, b = st.columns(2)
                a.metric('累積預算', format_totals(planning['totals'], compact=True) if planning['plans'] else '尚未建立預算')
                b.metric('累計花費', format_totals(value['spent'], compact=True) if value['spent'] is not None else '—')
                a.caption(f"待補發票：{pending_count} 個專案・{len(planning['pending'])} 個平台計畫")
                b.caption('完整帳號 API 花費・含今日已回報數據')
                if len(planning['totals']) != 1:
                    st.caption('預算：' + format_totals(planning['totals']))
                if len(value['spent'] or {}) > 1:
                    st.caption('花費：' + format_totals(value['spent']))
                if not value['accounts']:
                    st.caption('尚未新增此平台的廣告帳號。')
                for error in value['errors']:
                    st.warning(error)
    st.caption('上方預算為全部已建立專案；花費為完整廣告帳號。不受下方年度、狀態、搜尋或單一專案選擇影響。')
    if manual:
        st.session_state.budget_refresh_requested = True
        st.rerun()
