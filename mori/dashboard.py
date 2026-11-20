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
:root{--mori-brand:#17421E;--mori-ink:#142b1c;--mori-accent:#b8e572;}
html,body,[data-testid="stApp"]{font-family:"Microsoft JhengHei","微軟正黑體",sans-serif;}
[data-testid="stAppViewContainer"]{background:radial-gradient(ellipse at 95% 2%,#dcebdc80,transparent 45%),linear-gradient(#17421e03 1px,transparent 1px),linear-gradient(90deg,#17421e03 1px,transparent 1px),#f4f7f4;background-size:auto,32px 32px,32px 32px,auto;}
[data-testid="stHeader"]{background:#f4f7f4ef;border-bottom:1px solid #17421e10;}
[data-testid="stMainBlockContainer"]{max-width:1500px;padding-top:4.6rem!important;padding-bottom:3rem;}
h1{font-size:2.05rem!important;letter-spacing:-.035em;font-weight:750!important;color:#142b1c;}
h2{font-size:1.25rem!important;letter-spacing:-.025em;}
h3{font-size:1.05rem!important;}
[data-testid="stSidebar"]{background:radial-gradient(ellipse at 0 0,#17421E 0,transparent 70%),#0b1d12;border-right:1px solid #accf8c30;}
[data-testid="stSidebar"] [data-testid="stSidebarContent"]{padding-top:1rem;}
.mori-brand{padding:14px 4px 22px;margin-bottom:8px;border-bottom:1px solid #ffffff16;}
.mori-brand img{width:214px;max-width:100%;height:auto;display:block;}
.mori-brand span{display:block;color:#bdd0be;font-size:12px;letter-spacing:.22em;margin-top:16px;}
[data-testid="stSidebar"] [role="radiogroup"]{gap:7px;}
[data-testid="stSidebar"] [role="radiogroup"] label{padding:10px 12px;border:1px solid transparent;border-radius:9px;width:100%;color:#c7d5c9;transition:background 100ms;}
[data-testid="stSidebar"] [role="radiogroup"] label:hover{background:#ffffff0b;}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){background:linear-gradient(100deg,#5b8b443d,#b8e5720b);color:#e6f8cf;border:1px solid #b8e57245;box-shadow:inset 3px 0 #b8e572;}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:#94aa98;}
[data-testid="stSidebar"] button{background:#ffffff08;color:#d3e3d3;border-color:#adcba42b;}
[data-testid="stSidebar"] [data-testid="stExpander"]{background:transparent;border-color:#adcba42b;}
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]>div{border-color:#dae5db!important;border-radius:14px!important;background:#ffffffee;box-shadow:0 4px 24px #17351c04;}
[data-testid="stMetric"]{position:relative;overflow:hidden;background:linear-gradient(140deg,#fff,#f7faf6);border:1px solid #d9e6d9;border-radius:13px;padding:20px 22px;box-shadow:0 5px 20px #17421e07;}
[data-testid="stMetric"]:before{content:"";position:absolute;top:0;left:22px;width:38px;height:3px;background:#7ca65f;}
[data-testid="stMetricLabel"]{color:#617563;font-size:.85rem;}
[data-testid="stMetricValue"]{color:#17421E;font-weight:750;letter-spacing:-.045em;}
[data-testid="stColumn"]:first-child [data-testid="stMetric"]{background:radial-gradient(ellipse at 100% 0,#547941,#17421E 75%);border-color:#17421E;box-shadow:0 7px 22px #17421e23;}
[data-testid="stColumn"]:first-child [data-testid="stMetric"]:before{background:#b8e572;}
[data-testid="stColumn"]:first-child [data-testid="stMetricLabel"]{color:#c5d9bc;}
[data-testid="stColumn"]:first-child [data-testid="stMetricValue"]{color:#f6fbed;}
[data-testid="stButton"] button,[data-testid="stDownloadButton"] button{border-radius:9px;transition:background-color 80ms,border-color 80ms,box-shadow 80ms;}
[data-testid="stMain"] [data-testid="stButton"] button[kind="primary"]{background:#17421E;border-color:#17421E;box-shadow:0 4px 12px #17421e22;}
[data-testid="stButton"] button:active{transform:translateY(1px);}
[data-testid="stDataFrame"]{border:1px solid #dce7dc;border-radius:11px;overflow:hidden;}
.mori-banner{position:relative;isolation:isolate;overflow:hidden;display:flex;justify-content:space-between;align-items:center;gap:20px;border:1px solid #69845770;background:radial-gradient(ellipse at 85% -60%,#95bf5f6b,transparent 60%),linear-gradient(110deg,#102c17,#17421E 60%,#213d25);border-radius:17px;padding:29px 28px;margin:10px 0 20px;box-shadow:0 12px 38px #17421e16;}
.mori-banner:before{content:"";z-index:-1;position:absolute;inset:0;background:linear-gradient(#d3edaf0b 1px,transparent 1px),linear-gradient(90deg,#d3edaf0b 1px,transparent 1px);background-size:26px 26px;mask-image:linear-gradient(90deg,transparent,#000);}
.mori-banner:after{content:"";z-index:-1;position:absolute;width:210px;height:210px;right:50px;top:-100px;border:1px solid #c9f39e30;border-radius:50%;box-shadow:0 0 0 28px #c9f39e08,0 0 0 58px #c9f39e05;}
.mori-kicker{color:#c3e2a6;font-size:11px;letter-spacing:.18em;margin-bottom:10px;}
.mori-banner strong{display:block;font-size:24px;letter-spacing:-.03em;color:#f2f8ec;line-height:1.45;}
.mori-banner small{display:block;color:#bbcfb5;line-height:1.8;margin-top:8px;font-size:13px;}
.mori-pill{white-space:nowrap;border:1px solid #c2e59d55;border-radius:20px;padding:7px 12px;color:#d6efbd;background:#b8e5720f;font-size:12px;}
.mori-pill:before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:#b8e572;box-shadow:0 0 8px #b8e57270;margin-right:8px;}
.mori-empty{position:relative;overflow:hidden;text-align:center;padding:46px 20px;border:1px solid #d3e3d1;border-radius:15px;background:radial-gradient(ellipse at 50% 0,#e2efdc90,transparent 65%),#ffffffd9;}
.mori-empty:before{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(#17421e04 1px,transparent 1px),linear-gradient(90deg,#17421e04 1px,transparent 1px);background-size:24px 24px;mask-image:linear-gradient(#000,transparent);}
.mori-empty .symbol{position:relative;margin:0 auto 17px;width:52px;height:52px;border:1px solid #7a9c6d45;background:linear-gradient(145deg,#17421E,#2f5b2c);color:#d3edb4;border-radius:15px;box-shadow:0 8px 24px #17421e25;display:grid;place-items:center;font-size:27px;}
.mori-empty strong{position:relative;display:block;font-size:18px;color:#17421E;margin-bottom:8px;}
.mori-empty p{position:relative;color:#73846f;font-size:13px;}
@media(max-width:700px){.mori-banner{align-items:flex-start;flex-direction:column;padding:23px;}.mori-banner strong{font-size:21px;}[data-testid="stMainBlockContainer"]{padding-top:4.3rem!important;}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;}}
</style>''' 


def filter_rows(df, project=None, query='', channels=None):
    result = df.copy()
    if project:
        from mori.project_matching import matches
        mask = result.apply(lambda row: row.get('account_key') == project['account_key'] and matches(project, row), axis=1)
        result = result[mask]
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
    selected_project = projects.get(project_id)
    if selected_project:
        from mori.project_matching import conditions
        account = next(a for a in settings['accounts'] if a['key'] == selected_project['account_key'])
        if account['platform'] == 'google' and any(c['field'] != 'campaign_name' for c in conditions(selected_project)):
            st.info('此 Google 計畫使用廣告明細認列，請到「專案預算」更新並查看專案花費。本頁目前為行銷活動層級，尚不提供這筆計畫的訂位／CPA。')
            return
    shown = filter_rows(df, selected_project, query, channels)
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
                for container, field, title, color in [(left, 'spend', '花費趨勢', '#17421E'),
                                                        (right, 'conversions', '訂位趨勢', '#168578')]:
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
