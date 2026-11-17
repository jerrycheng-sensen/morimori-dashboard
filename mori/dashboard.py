"""Mori overview: native Streamlit controls with a modern dashboard layout."""
from __future__ import annotations

import html
import io
from datetime import datetime

import pandas as pd
import streamlit as st

from mori.core import TAIPEI
from mori.runner import conversion_label

PLATFORMS = {'meta': 'Meta', 'google': 'Google Ads'}

CSS = '''<style>
html,body,[data-testid="stApp"]{font-family:"Microsoft JhengHei","微軟正黑體",sans-serif;}
[data-testid="stAppViewContainer"]{background:#f7f9f8;}
[data-testid="stMainBlockContainer"]{max-width:1500px;padding-top:2.2rem;padding-bottom:3rem;}
[data-testid="stSidebar"]{background:#fff;border-right:1px solid #e3e9e5;}
[data-testid="stSidebar"] h1{font-size:1.2rem;letter-spacing:-.03em;}
h1{font-size:2rem!important;letter-spacing:-.045em;font-weight:750!important;}
h2{font-size:1.25rem!important;letter-spacing:-.025em;}
h3{font-size:1.05rem!important;}
[data-testid="stSidebar"] [role="radiogroup"]{gap:4px;}
[data-testid="stSidebar"] [role="radiogroup"] label{padding:9px 12px;border-radius:8px;}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){background:#e9f2ed;color:#174d38;font-weight:700;}
[data-testid="stVerticalBlockBorderWrapper"]>div{border-color:#e1e8e3!important;border-radius:14px!important;background:#fff;}
[data-testid="stMetric"]{background:#fff;border:1px solid #e1e8e3;border-radius:12px;padding:19px 20px;box-shadow:0 2px 3px #122b1e03;}
[data-testid="stMetricLabel"]{color:#64756b;font-size:.85rem;}
[data-testid="stMetricValue"]{color:#183c2c;font-weight:700;letter-spacing:-.04em;}
[data-testid="stButton"] button,[data-testid="stDownloadButton"] button{border-radius:8px;transition:background-color 80ms,border-color 80ms;}
[data-testid="stButton"] button:active{transform:translateY(1px);}
[data-testid="stDataFrame"]{border:1px solid #e3e9e5;border-radius:10px;overflow:hidden;}
.mori-eyebrow{font-size:11px;letter-spacing:.16em;font-weight:700;color:#718378;margin-bottom:7px;}
.mori-banner{display:flex;justify-content:space-between;align-items:center;gap:18px;border:1px solid #cfe0d5;background:linear-gradient(110deg,#eaf3ed,#f8fbf9);border-radius:12px;padding:18px 22px;margin:0 0 18px;}
.mori-banner strong{display:block;font-size:15px;color:#174d38;}
.mori-banner small{color:#64766a;line-height:1.8;}
.mori-pill{white-space:nowrap;border:1px solid #c9dbcf;border-radius:20px;padding:5px 11px;color:#28553c;background:#fff;font-size:12px;}
.mori-empty{text-align:center;padding:48px 20px;border:1px dashed #cbdcd1;border-radius:14px;background:#fff;}
.mori-empty .symbol{margin:0 auto 14px;width:44px;height:44px;background:#eaf3ed;color:#174d38;border-radius:12px;display:grid;place-items:center;font-size:23px;}
.mori-empty strong{display:block;font-size:18px;color:#234c36;margin-bottom:8px;}
.mori-empty p{color:#75877c;font-size:14px;}
@media(max-width:700px){.mori-banner{align-items:flex-start;flex-direction:column;}[data-testid="stMainBlockContainer"]{padding-top:1rem;}}
</style>'''


def filter_rows(df, project=None, query='', channels=None):
    result = df.copy()
    if project:
        field = project.get('match_field', 'campaign_name')
        if field not in result:
            return result.iloc[0:0]
        result = result[(result.account_key == project['account_key']) &
                        result[field].fillna('').str.contains(project.get('keyword', ''), case=False, regex=False)]
    if channels is not None:
        result = result[result.channel.isin(channels)]
    if query.strip():
        result = result[result.campaign_name.fillna('').str.contains(query.strip(), case=False, regex=False)]
    return result


def totals(part):
    complete = part.conversions.notna().all()
    bookings = float(part.conversions.sum()) if complete else None
    spend = float(part.spend.sum())
    return {'spend': spend, 'bookings': bookings,
            'cpa': spend / bookings if bookings and bookings > 0 else None,
            'clicks': float(part.clicks.sum())}


def summary_table(df, names):
    rows = []
    for (key, platform, cid, name, currency), part in df.groupby(
            ['account_key', 'platform', 'campaign_id', 'campaign_name', 'currency'], dropna=False):
        metrics = totals(part)
        impressions, clicks = part.impressions.sum(), part.clicks.sum()
        rows.append({'平台': PLATFORMS.get(platform, platform), '帳號': names.get(key, key),
                     '活動 ID': cid, '活動': name, '幣別': currency, '花費': metrics['spend'],
                     '訂位': metrics['bookings'], 'CPA': metrics['cpa'], '曝光': impressions,
                     '點擊': clicks, 'CTR %': 100 * clicks / impressions if impressions else None,
                     'CPC': metrics['spend'] / clicks if clicks else None})
    return pd.DataFrame(rows)


def trend_data(part, field):
    # Missing conversion measurements remain null, including partially missing days.
    groups = part.groupby('date')[field]
    values = groups.apply(lambda x: x.sum() if x.notna().all() else None)
    return values.rename('value').reset_index()


def chart_spec(title, color, money=False):
    return {
        'height': 215,
        'layer': [
            {'mark': {'type': 'area', 'color': color, 'opacity': .09, 'interpolate': 'linear'}},
            {'mark': {'type': 'line', 'color': color, 'strokeWidth': 2.6, 'point': {'filled': True, 'size': 24}}},
        ],
        'encoding': {
            'x': {'field': 'date', 'type': 'temporal', 'title': None,
                  'axis': {'format': '%m/%d', 'grid': False, 'labelAngle': 0, 'tickCount': 6}},
            'y': {'field': 'value', 'type': 'quantitative', 'title': None,
                  'scale': {'zero': True}, 'axis': {'format': ',.0f' if money else ',.1~f', 'tickCount': 4}},
            'tooltip': [{'field': 'date', 'type': 'temporal', 'title': '日期', 'format': '%Y/%m/%d'},
                        {'field': 'value', 'type': 'quantitative', 'title': title, 'format': ',.2f'}],
        },
        'config': {'view': {'stroke': None}, 'axis': {'domain': False, 'ticks': False,
                   'gridColor': '#edf1ee', 'labelColor': '#7d8b82', 'labelPadding': 10},
                   'background': 'transparent'},
    }


def render_report(view, keys, period, settings, names, account_by_key):
    if not view:
        st.markdown('<div class="mori-empty"><div class="symbol">↗</div><strong>從今天的廣告全貌開始</strong>'
                    '<p>選擇帳號與日期，按「讀取數據」，查看花費、訂位與 CPA。</p></div>', unsafe_allow_html=True)
        return
    if tuple(map(str, period)) != view['period'] or keys != view['keys']:
        st.info('篩選已變更，按「讀取數據」更新；下方仍是上次查詢結果。')
    at = datetime.fromisoformat(view['at']).astimezone(TAIPEI).strftime('%m/%d %H:%M')
    st.caption(f"資料期間 {' ～ '.join(view['period'])}　·　更新於 {at}（台灣時間）")
    for error in view['errors']:
        st.error(error)
    df = pd.DataFrame([row for report in view['reports'] for row in report['rows']])
    if df.empty:
        st.info('此區間沒有可顯示的資料；讀取失敗的帳號不列入零值。')
        return
    projects = {p['id']: p for p in settings['projects'] if p['account_key'] in view['keys']}
    with st.container(border=True):
        pcol, ccol, qcol = st.columns([1.15, 1.15, 1.7])
        project_id = pcol.selectbox('專案篩選', ['all'] + list(projects),
                                   format_func=lambda k: '全部專案／帳號資料' if k == 'all' else projects[k]['name'])
        channels = ccol.multiselect('廣告類型', sorted(df.channel.unique()), default=sorted(df.channel.unique()))
        query = qcol.text_input('搜尋廣告活動', placeholder='輸入活動名稱關鍵字…')
    shown = filter_rows(df, projects.get(project_id), query, channels)
    if shown.empty:
        st.info('沒有符合目前篩選的廣告，請調整專案、類型或關鍵字。')
        return
    available = list(shown.platform.unique())
    st.caption('平台分開統計訂位與 CPA；平台歸因數字可能重複，不代表去重後的實際訂位或到店。')
    tabs = st.tabs([PLATFORMS.get(p, p) for p in available])
    for tab, platform in zip(tabs, available):
        with tab:
            for currency, part in shown[shown.platform == platform].groupby('currency'):
                st.caption(f'{PLATFORMS.get(platform, platform)}　／　{currency}')
                metric = totals(part)
                a, b, c, d = st.columns(4)
                a.metric('廣告花費', f"{metric['spend']:,.2f}")
                b.metric('訂位（平台歸因）', f"{metric['bookings']:,.2f}".rstrip('0').rstrip('.') if metric['bookings'] is not None else '尚未設定')
                c.metric('訂位 CPA', f"{metric['cpa']:,.2f}" if metric['cpa'] is not None else '—')
                d.metric('Meta 連結點擊' if platform == 'meta' else '廣告點擊', f"{metric['clicks']:,.0f}")
                left, right = st.columns(2)
                for container, field, title, color in [(left, 'spend', '花費趨勢', '#247653'),
                                                        (right, 'conversions', '訂位趨勢', '#589d91')]:
                    with container, st.container(border=True):
                        st.subheader(title)
                        st.caption(currency if field == 'spend' else '依平台指定事件統計')
                        st.vega_lite_chart(trend_data(part, field), chart_spec(title, color, field == 'spend'), width='stretch')
    summary = summary_table(shown, names)
    with st.container(border=True):
        st.subheader('廣告活動成效')
        st.caption(f'{len(summary)} 個活動　·　點選欄位標題排序；表格右上角可搜尋')
        st.dataframe(summary.sort_values('花費', ascending=False), hide_index=True, width='stretch',
                     column_config={name: st.column_config.NumberColumn(format='%.2f') for name in ['花費', '訂位', 'CPA', 'CPC', 'CTR %']})
        export_key = (view['at'], project_id, tuple(channels), query)
        export = st.session_state.get('report_export')
        if export is None or export[0] != export_key:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                summary.to_excel(writer, index=False, sheet_name='活動總覽')
                shown.drop(columns=['available_actions'], errors='ignore').to_excel(writer, index=False, sheet_name='每日明細')
            export = (export_key, buffer.getvalue())
            st.session_state.report_export = export
        st.download_button('下載 Excel 報表', export[1], 'mori-ad-report.xlsx', on_click='ignore')
    with st.expander('數據口徑與帳號資訊'):
        st.caption('花費為平台帳號幣別，未另加服務費與稅；不等於儲值餘額。專案篩選依已設定的帳號與名稱條件，不限制查詢日期。')
        for key in view['keys']:
            if key in account_by_key:
                st.caption(f"{names[key]}｜{conversion_label(account_by_key[key])}")
        for report in view['reports']:
            st.caption(f"帳號時區：{report.get('timezone')}｜幣別：{report['currency']}")
