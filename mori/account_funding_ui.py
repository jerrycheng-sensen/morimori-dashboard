"""Always-visible account totals above the project budget navigation."""
from datetime import datetime
import html

import streamlit as st

from mori.account_funding import default_since, view_key, collect_accounts, summary_totals
from mori.core import TAIPEI


@st.fragment
def render_account_totals(settings, fetch):
    today = datetime.now(TAIPEI).date()
    suggested = default_since(settings, today)
    st.markdown('<div class="mori-account-title">雙平台預算總覽</div>', unsafe_allow_html=True)
    with st.expander('統計期間與計算說明'):
        custom = st.checkbox('自行指定統計起日', key='account_totals_custom_since')
        since = st.date_input('帳號總覽統計起日', suggested, max_value=today, key='account_totals_since') if custom else suggested
        st.caption('預設從最早的平台計畫開始日或發票儲值登錄日（含作廢歷史）起算，至今日；不是帳號成立以來的歷史總額。')
        st.caption('總儲值金額＝期間內有效發票的本專案認列金額；總花費＝期間內完整帳號花費。不同專案重疊不重複計算；內部預算轉移不算新增儲值。金額不代表平台錢包餘額。')
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
    platforms, combined = summary_totals(settings, reports, since, today)
    stamp = datetime.fromisoformat(view['at']).strftime('%Y/%m/%d %H:%M') if view.get('at') and view.get('key') == key else '尚未讀取'
    st.caption(f'帳號統計期間 {since} ～ {today}｜資料讀取時間 {stamp}（台灣時間）｜依帳號時區、含今日已回報花費；平台可能延遲或回補')
    if combined is not None:
        funds = f"{combined['currency']} {combined['funds']:,.2f}" if combined['invoices'] else '尚未登錄發票'
        cost = f"{combined['currency']} {combined['spent']:,.2f}"
        st.markdown('<div class="mori-account-combined"><strong>雙平台合計</strong><div><span>總儲值金額／可使用預算</span><b>' + html.escape(funds) +
                    '</b></div><div><span>總花費／已使用預算</span><b>' + html.escape(cost) + '</b></div></div>', unsafe_allow_html=True)
    elif settings['accounts']:
        st.caption('雙平台合計：帳號花費尚未全部取得，或包含不同幣別，暫不合成一個金額。')
    for column, platform in zip(st.columns(2), ('meta', 'google')):
        value = platforms[platform]
        with column:
            with st.container(border=True):
                st.subheader('Meta' if platform == 'meta' else 'Google Ads')
                st.caption(f"{value['accounts']} 個廣告帳號｜{value['invoices']} 筆有效發票認列")
                funds = '；'.join(f'{cur} {v:,.2f}' for cur, v in sorted(value['funds'].items())) or '尚未登錄發票'
                cost = ('；'.join(f'{cur} {v:,.2f}' for cur, v in sorted(value['spent'].items())) if value['spent'] is not None else '—')
                a, b = st.columns(2)
                a.metric('總儲值金額', funds if len(value['funds']) <= 1 else '分幣別列示')
                b.metric('總花費', cost if len(value['spent'] or {}) <= 1 else '分幣別列示')
                if len(value['funds']) > 1:
                    st.caption('儲值：' + funds)
                if len(value['spent'] or {}) > 1:
                    st.caption('花費：' + cost)
                st.caption('可使用預算：發票認列金額　｜　已使用預算：帳號 API 花費')
                if not value['accounts']:
                    st.caption('尚未新增此平台的廣告帳號。')
                for error in value['errors']:
                    st.warning(error)
    st.caption('上方為完整帳號統計，不受下方年度、狀態、搜尋或單一專案選擇影響；既有發票與專案儲值機制不變。')
    if manual:
        st.session_state.budget_refresh_requested = True
        st.rerun()
