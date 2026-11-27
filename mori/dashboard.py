"""Mori overview: native Streamlit controls with a modern dashboard layout."""
from __future__ import annotations

import html
import io
import base64
from pathlib import Path
from decimal import Decimal
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from mori.core import TAIPEI
from mori.runner import conversion_label
from mori.money_display import money_metric, money_html, money_text, money_table, styled_money_frame

PLATFORMS = {'meta': 'Meta', 'google': 'Google Ads'}

CSS = '''<style>
.mori-money-fraction{font-size:.58em!important;font-weight:500!important;opacity:.6;letter-spacing:0;white-space:nowrap;}
.mori-money-metric{padding:20px 18px;border:1px solid #dedbd4;border-radius:14px;background:#fffefa;min-width:0;}
.mori-money-label{font-size:15px;color:#5c6b5f;margin-bottom:10px;}
.mori-money-value{font-size:clamp(24px,2.15vw,32px);font-weight:750;line-height:1.35;color:#17421E;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;}
.mori-money-note{font-size:14px!important;line-height:1.8;color:#718075;margin:8px 0;}
:root{--mori-brand:#17421E;--mori-ink:#142b1c;--mori-accent:#b8e572;}
html,body,[data-testid="stApp"]{font-family:"Microsoft JhengHei","微軟正黑體",sans-serif!important;}
[data-testid="stApp"] *:not([data-testid="stIconMaterial"]):not([class*="material-symbols"]){font-family:"Microsoft JhengHei","微軟正黑體",sans-serif!important;}
[data-testid="stIconMaterial"],[class*="material-symbols"]{font-family:"Material Symbols Rounded"!important;}
body [role="tooltip"],body [role="listbox"],body [role="option"],body [data-baseweb="popover"],body [data-baseweb="popover"] *{font-family:"Microsoft JhengHei","微軟正黑體",sans-serif!important;}
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
    spend = sum((Decimal(str(r.get('spend_raw') if pd.notna(r.get('spend_raw')) else r['spend'])) for r in part.to_dict('records')), Decimal(0))
    return {'spend': spend, 'bookings': bookings,
            'cpa': spend / Decimal(str(bookings)) if bookings and bookings > 0 else None,
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
                     'CPC': metrics['spend'] / Decimal(str(clicks)) if clicks else None})
    return pd.DataFrame(rows)


def trend_data(part, field):
    # Missing conversion measurements remain null, including partially missing days.
    groups = part.groupby('date')[field]
    values = groups.apply(lambda x: x.sum() if x.notna().all() else None)
    return values.rename('value').reset_index()


def chart_spec(title, color, money=False, platform='combined'):
    money_format = '$,.0f' if platform == 'meta' else '$,.2f'
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
                  'scale': {'zero': True}, 'axis': {'format': money_format if money else ',.1~f', 'tickCount': 4}},
            'tooltip': [{'field': 'date', 'type': 'temporal', 'title': '日期', 'format': '%Y/%m/%d'},
                        {'field': 'value', 'type': 'quantitative', 'title': title, 'format': money_format if money else ',.2f'}],
        },
        'config': {'font': 'Microsoft JhengHei', 'view': {'stroke': None}, 'axis': {'domain': False, 'ticks': False,
                   'gridColor': '#edf1ee', 'labelColor': '#7d8b82', 'labelPadding': 10},
                   'background': 'transparent'},
    }


def previous_period(period):
    start, end = map(lambda d: date.fromisoformat(str(d)), period)
    length = (end - start).days + 1
    return start - timedelta(days=length), start - timedelta(days=1)


def overview_controls(names):
    st.markdown(OVERVIEW_CSS, unsafe_allow_html=True)
    st.markdown('<div class="overview-hero"><div class="overview-eyebrow">MORI · AD PERFORMANCE</div>'
                '<h1>廣告成效，一眼掌握。</h1><p>先看投入與訂位，再找出值得調整的地方。</p></div>', unsafe_allow_html=True)
    with st.container(key='overview_query', border=True):
        a, b, c = st.columns([1.4, .9, .65], vertical_alignment='bottom')
        keys = a.multiselect('廣告帳號', list(names), default=list(names), format_func=names.get, key='overview_accounts')
        preset = b.selectbox('查詢期間', ['近 7 天', '昨天', '近 30 天', '近 90 天', '本月', '自訂日期'], key='overview_period_preset')
        compare = c.checkbox('與前期比較', value=True, help='使用相同天數；例如本次 7 天，就與前 7 天比較。', key='overview_compare')
        today = datetime.now(TAIPEI).date()
        yesterday = today - timedelta(days=1)
        if preset == '自訂日期':
            period = st.date_input('查詢區間（依各廣告帳號時區）', (today-timedelta(days=7), yesterday), max_value=today, key='overview_custom_period')
        else:
            start = yesterday if preset == '昨天' else today.replace(day=1) if preset == '本月' else today-timedelta(days=90 if preset == '近 90 天' else 30 if preset == '近 30 天' else 7)
            period = (start, max(start, yesterday))
        read = st.button('讀取數據', type='primary', icon=':material/refresh:', key='overview_read')
        if len(period) == 2:
            st.caption(f'本次查詢 {period[0]:%Y/%m/%d} — {period[1]:%Y/%m/%d} · 依各帳號時區。按「讀取數據」更新，下方切換檢視沿用本次資料。')
    return keys, period, compare, read


def report_frame(reports):
    columns = ['account_key', 'platform', 'date', 'campaign_id', 'campaign_name', 'channel', 'currency',
               'spend', 'conversions', 'impressions', 'clicks']
    rows = [row for report in reports for row in report['rows']]
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=columns)


def project_slice(df, plans, period):
    """Union by original row index, scoped to each plan's dates and account.

    Campaign-only Google reports must never stand in for ad/asset attribution.
    """
    from mori.project_matching import conditions, verified_match
    selected = set()
    for plan in plans:
        account_rows = df[df.account_key == plan['account_key']]
        if account_rows.empty:
            continue
        if (account_rows.platform == 'google').any() and (
                any(c['field'] != 'campaign_name' for c in conditions(plan)) or plan.get('assigned_units')):
            return df.iloc[:0], 'Google 使用廣告／素材條件，需至專案預算查看完整認列。'
        start = max(str(period[0]), plan['start'])
        end = min(str(period[1]), plan['end'])
        for index, row in account_rows.iterrows():
            if not start <= str(row['date']) <= end:
                continue
            if any(c['field'] not in row.index for c in conditions(plan)):
                return df.iloc[:0], '缺少認列所需的廣告明細，暫不顯示專案合計。'
            matched = verified_match(plan, row.to_dict())
            if matched is None:
                return df.iloc[:0], '廣告名稱尚未核對，暫不顯示專案合計。'
            if matched:
                selected.add(index)
    return df.loc[sorted(selected)], ''


def metric_delta(current, previous, lower=False):
    if current is None or previous is None:
        return '尚無可比較資料', 'neutral'
    if previous == 0:
        return ('前期為 0，無法計算升降' if current else '與前期相同'), 'neutral'
    change = (Decimal(str(current)) / Decimal(str(previous)) - 1) * 100
    if abs(change) < Decimal('.05'):
        return '與前期持平', 'neutral'
    favorable = change < 0 if lower else change > 0
    return f'{"下降" if change < 0 else "上升"} {abs(change):.1f}% · 對比前期', ('good' if favorable else 'attention') if lower else 'neutral'


def number_html(value):
    if value is None:
        return '—'
    text = f'{value:,.2f}'.rstrip('0').rstrip('.')
    if '.' in text:
        integer, fraction = text.split('.')
        return integer + '<span class="overview-fraction">.' + fraction + '</span>'
    return text


def render_kpis(part, previous=None, incomplete=False, comparison=False):
    currencies = list(part.currency.dropna().unique())
    if len(currencies) > 1:
        st.warning('查詢結果包含不同幣別，以下按幣別分開呈現，不直接加總金額。')
    for currency in currencies or ['TWD']:
        current = part[part.currency == currency]
        metrics = totals(current)
        before = totals(previous[previous.currency == currency]) if previous is not None else {}
        platform = 'meta' if set(current.platform.unique()) == {'meta'} else 'combined'
        if currency != 'TWD':
            st.write('帳號幣別：' + currency)
        with st.container(key='overview_kpis_' + str(currency)):
            for col, label, key, monetary in zip(st.columns(3), ['廣告花費', '平台回報訂位', '訂位 CPA'], ['spend', 'bookings', 'cpa'], [True, False, True]):
                value = None if incomplete else metrics[key]
                content = money_html(value, platform) if monetary else number_html(value)
                delta, kind = metric_delta(value, before.get(key), key == 'cpa') if comparison else ('按各平台指定的訂位事件統計' if key == 'bookings' else '廣告花費 ÷ 平台回報訂位' if key == 'cpa' else '未含服務費與稅', 'neutral')
                if incomplete:
                    delta, kind = '資料尚未完整，不以部分數字當成總計', 'attention'
                col.markdown(f'<article class="overview-kpi"><div class="overview-kpi-label">{label}</div><div class="overview-kpi-value">{content}</div><div class="overview-delta {kind}">{delta}</div></article>', unsafe_allow_html=True)


def platform_logo(platform):
    path = Path(__file__).resolve().parents[1] / 'assets' / ('meta-logo.svg' if platform == 'meta' else 'google-ads-logo.svg')
    data = base64.b64encode(path.read_bytes()).decode()
    return f'<img alt="{PLATFORMS[platform]} Logo" src="data:image/svg+xml;base64,{data}">'


def render_report(view, keys, period, settings, names, account_by_key):
    st.markdown(OVERVIEW_CSS, unsafe_allow_html=True)
    with st.container(key='overview_workspace'):
        _render_report(view, keys, period, settings, names, account_by_key)


def _render_report(view, keys, period, settings, names, account_by_key):
    if not view:
        st.markdown('<div class="overview-start"><span>準備查看廣告成效</span><h2>選好日期，讀取你的雙平台數據。</h2><p>預設查看近 7 個完整日；先避開今天還在變動的數字。</p></div>', unsafe_allow_html=True)
        return
    if tuple(map(str, period)) != view['period'] or keys != view['keys'] or st.session_state.get('overview_compare', view.get('comparison', False)) != view.get('comparison', False):
        st.info('上方查詢條件已變更。請按「讀取數據」更新；目前顯示上次查詢結果。')
    at = datetime.fromisoformat(view['at']).astimezone(TAIPEI).strftime('%Y/%m/%d %H:%M')
    st.markdown(f'<div class="overview-status"><strong>{html.escape(" — ".join(view["period"]))}</strong><span>更新於 {at}（台灣時間）</span></div>', unsafe_allow_html=True)
    errors = view.get('errors', [])
    for error in errors:
        st.error(error)
    for report in view['reports']:
        for warning in report.get('overview_warnings', []):
            st.warning(warning)
    if view['period'][1] >= str(datetime.now(TAIPEI).date()):
        st.warning('本次包含今天，花費與訂位仍會更新。和後台核對時，請使用相同日期、時區與更新時間。')
    df = report_frame(view['reports'])
    if df.empty:
        st.info('此區間沒有可顯示的資料；讀取失敗的帳號不會當成零值。')
        return
    previous = report_frame(view.get('previous_reports', [])) if view.get('comparison') and not view.get('previous_errors') else None
    if view.get('previous_errors'):
        st.warning('前期資料未完整讀取，已停用升降比較；本期資料仍可查看。')
    groups = {g['id']: g for g in settings.get('project_groups', [])}
    plans = [p for p in settings.get('projects', []) if p['account_key'] in view['keys']]
    grouped = {}
    for plan in plans:
        group = plan.get('group_id') or 'plan:' + plan['id']
        grouped.setdefault(group, []).append(plan)
    def group_name(key):
        return groups[key]['name'] if key in groups else grouped[key][0]['name']
    with st.container(border=True, key='overview_filters'):
        a, b = st.columns([1.25, 1])
        group_id = a.selectbox('查看專案', ['all'] + list(grouped), format_func=lambda k: '全部帳號資料' if k == 'all' else group_name(k), key='overview_project')
        platform = b.radio('查看平台', ['all', 'meta', 'google'], format_func=lambda k: '雙平台' if k == 'all' else PLATFORMS[k], horizontal=True, key='overview_platform')
    selected_plans = grouped.get(group_id)
    if selected_plans and platform != 'all':
        selected_plans = [p for p in selected_plans if account_by_key[p['account_key']]['platform'] == platform]
        if not selected_plans:
            st.info('此專案沒有設定這個平台的計畫。')
            return
    issue = ''
    shown, issue = project_slice(df, selected_plans, view['period']) if selected_plans else (df, '')
    before = previous
    if selected_plans and before is not None:
        before, previous_issue = project_slice(before, selected_plans, view.get('previous_period', previous_period(view['period'])))
        if previous_issue:
            before = None
    if platform != 'all':
        shown = shown[shown.platform == platform]
        before = before[before.platform == platform] if before is not None else None
    if selected_plans:
        if st.button('查看此專案預算與認列明細', key='overview_open_budget', icon=':material/arrow_forward:'):
            st.session_state.overview_budget_target = ('group:' + group_id) if group_id in groups else group_id
            st.rerun(scope='app')
    if issue:
        st.info(issue + ' 本頁不會以整個活動的成效代替。')
        return
    if shown.empty:
        st.info('此專案／平台在查詢區間沒有符合條件的廣告資料。')
        return
    relevant_keys = [p['account_key'] for p in selected_plans] if selected_plans else view['keys']
    relevant_keys = [k for k in relevant_keys if platform == 'all' or account_by_key[k]['platform'] == platform]
    loaded = set(view.get('loaded_keys', [r['account_key'] for r in df.to_dict('records')]))
    incomplete = bool(set(relevant_keys) - loaded)
    st.markdown('<h2 class="overview-section-title">這段時間的廣告表現</h2>', unsafe_allow_html=True)
    render_kpis(shown, before, incomplete, view.get('comparison', False))
    st.caption('平台回報訂位可能重複認列，不等於去重後的實際訂位人數或到店人數。不同幣別不合併。')
    if view.get('comparison'):
        st.caption('前期比較：' + ' — '.join(map(str, view.get('previous_period', previous_period(view['period'])))) + (' · 專案檢視另依各計畫廣告走期篩選。' if selected_plans else ' · 相同天數，採相同平台篩選。'))
    st.divider()
    st.subheader('每天的變化')
    indicator = st.radio('趨勢指標', ['spend', 'conversions', 'cpa'], format_func=lambda k: {'spend':'廣告花費','conversions':'平台回報訂位','cpa':'訂位 CPA'}[k], horizontal=True, key='overview_trend')
    chart_rows = []
    for (p, cur), part in shown.groupby(['platform', 'currency']):
        for day, daily in part.groupby('date'):
            values = totals(daily)
            value = values[{'spend':'spend','conversions':'bookings','cpa':'cpa'}[indicator]]
            chart_rows.append({'date':day, 'value':float(value) if value is not None else None, '平台':PLATFORMS[p], 'currency':cur})
    for cur in shown.currency.unique():
        chart = pd.DataFrame([r for r in chart_rows if r['currency'] == cur])
        spec = chart_spec({'spend':'廣告花費','conversions':'平台回報訂位','cpa':'訂位 CPA'}[indicator], '#17421E', indicator != 'conversions', 'meta' if set(shown.platform) == {'meta'} else 'combined')
        spec['height'] = 280
        spec['encoding']['color'] = {'field':'平台','type':'nominal','scale':{'domain':['Meta','Google Ads'],'range':['#17421E','#b79a65']},'legend':{'title':None,'orient':'top'}}
        spec['encoding']['tooltip'].append({'field':'平台','type':'nominal'})
        for layer in spec['layer']:
            layer['mark'].pop('color', None)
        with st.container(border=True):
            st.vega_lite_chart(chart, spec, width='stretch')
    st.divider()
    st.subheader('雙平台成效比較' if platform == 'all' else PLATFORMS[platform] + ' 成效')
    chosen_platforms = [p for p in ('meta','google') if any(account_by_key[k]['platform'] == p for k in relevant_keys)]
    for col, p in zip(st.columns(max(1,len(chosen_platforms))), chosen_platforms):
        with col, st.container(border=True):
            st.markdown(f'<div class="overview-platform-title">{platform_logo(p)}<h3>{PLATFORMS[p]}</h3></div>', unsafe_allow_html=True)
            pkeys = [k for k in relevant_keys if account_by_key[k]['platform'] == p]
            p_incomplete = bool(set(pkeys) - loaded)
            part = shown[shown.platform == p]
            if p_incomplete:
                st.warning('此平台資料讀取不完整，暫不顯示合計。')
            for cur, values in part.groupby('currency'):
                metric = totals(values)
                if cur != 'TWD': st.caption(cur)
                money_metric(st, '廣告花費', None if p_incomplete else metric['spend'], p)
                a,b = st.columns(2)
                a.markdown('<div class="overview-inline"><span>平台回報訂位</span><strong>'+number_html(None if p_incomplete else metric['bookings'])+'</strong></div>',unsafe_allow_html=True)
                b.markdown('<div class="overview-inline"><span>訂位 CPA</span><strong>'+money_html(None if p_incomplete else metric['cpa'],p)+'</strong></div>',unsafe_allow_html=True)
            st.caption('Meta 為連結點擊；Google 為廣告點擊，兩者分開查看。')
            with st.expander('查看流量表現'):
                for cur, values in part.groupby('currency'):
                    impressions, clicks = values.impressions.sum(), values.clicks.sum()
                    st.write(f'曝光 {impressions:,.0f} · 點擊 {clicks:,.0f}')
                    st.write(f'CTR {100*clicks/impressions:.2f}%' if impressions else 'CTR —')
                    money_metric(st, 'CPC', totals(values)['spend']/Decimal(str(clicks)) if clicks else None, p)
    from mori.performance_model import render_activity_comparison, render_sweet_spot
    render_activity_comparison(shown, view, selected_plans is None,
                               {account_by_key[k]['platform'] for k in relevant_keys if k not in loaded})
    if not incomplete:
        render_sweet_spot(shown, view)
    else:
        st.info('帳號資料尚未完整，暫不建立甜蜜點觀察。')
    if grouped:
        st.divider()
        st.subheader('各專案成效')
        st.caption('依各專案條件與廣告走期認列；專案可能重疊，不加總成帳號總花費。')
        project_rows, project_platforms = [], []
        for gid, group_plans in grouped.items():
            if selected_plans and gid != group_id: continue
            relevant = [p for p in group_plans if platform == 'all' or account_by_key[p['account_key']]['platform'] == platform]
            if not relevant: continue
            part, problem = project_slice(df, relevant, view['period'])
            if set(p['account_key'] for p in relevant) - loaded:
                problem = '帳號讀取不完整'
            curs = list(part.currency.unique())
            if len(curs)>1: problem = '不同幣別，請分平台查看'
            metric = totals(part)
            row_platform = 'meta' if all(account_by_key[p['account_key']]['platform']=='meta' for p in relevant) else 'combined'
            project_rows.append({'專案':group_name(gid), '廣告花費':None if problem else metric['spend'], '平台回報訂位':None if problem or metric['bookings'] is None else f"{metric['bookings']:,.2f}".rstrip('0').rstrip('.'), '訂位 CPA':None if problem else metric['cpa'], '資料狀態':problem or ('此區間無符合資料' if part.empty else '依專案條件與走期認列')})
            project_platforms.append(row_platform)
        if project_rows:
            money_table(st, pd.DataFrame(project_rows), project_platforms, {'廣告花費','訂位 CPA'})
    st.divider()
    with st.expander('查看廣告活動明細與下載報表'):
        a,b = st.columns([1,1.5])
        channels = a.multiselect('廣告類型', sorted(shown.channel.unique()), default=sorted(shown.channel.unique()), key='overview_channels')
        query = b.text_input('搜尋廣告活動', placeholder='輸入活動名稱關鍵字…', key='overview_search')
        detail = filter_rows(shown, query=query, channels=channels)
        st.caption('以下篩選只影響明細與匯出，不會改變上方成效總計。')
        summary = summary_table(detail, names)
        if not summary.empty:
            ordered = summary.sort_values('花費', ascending=False)
            platforms = ['meta' if p=='Meta' else 'google' for p in ordered['平台']]
            st.dataframe(styled_money_frame(ordered, {'花費','CPA','CPC'}, platforms), hide_index=True, width='stretch', column_config={name:st.column_config.NumberColumn(format='%.2f') for name in ['訂位','CTR %']})
            export_key = (view['at'],group_id,platform,tuple(channels),query)
            export = st.session_state.get('report_export')
            if export is None or export[0] != export_key:
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    summary.to_excel(writer,index=False,sheet_name='活動總覽')
                    detail.drop(columns=['available_actions'],errors='ignore').to_excel(writer,index=False,sheet_name='每日明細')
                export = (export_key,buffer.getvalue())
                st.session_state.report_export = export
            st.download_button('下載 Excel 報表',export[1],'mori-ad-report.xlsx',on_click='ignore')
        else:
            st.info('明細沒有符合目前篩選的廣告。')
    with st.expander('查看數據口徑與帳號資訊'):
        st.write('花費未另加服務費與稅，不等於儲值餘額。前期比較不表示投放效果的因果關係。專案檢視依條件及走期篩選；Google 素材／廣告層級的專案請至專案預算查看。')
        for key in view['keys']:
            if key in account_by_key:
                st.caption(f'{names[key]}｜{conversion_label(account_by_key[key])}')
        for report in view['reports']:
            st.caption(f'帳號時區：{report.get("timezone")}｜幣別：{report["currency"]}')


OVERVIEW_CSS = """<style>
[data-testid="stAppViewContainer"]:has(.overview-hero){background:radial-gradient(ellipse at 100% 0,#ece5d780,transparent 55%),#f6f4ef;background-size:auto;}
.overview-hero{padding:30px 0 28px;border-bottom:1px solid #e6dfd2;margin-bottom:24px;}
.overview-eyebrow{font-size:12px;letter-spacing:.2em;color:#967d51;font-weight:700;margin-bottom:12px;}
.overview-hero h1{font-size:clamp(28px,3vw,42px)!important;color:#17421E;line-height:1.3;}
.overview-hero p{font-size:17px;color:#68756b;margin-top:12px;}
.st-key-overview_query{background:#fffefa;border-color:#e3ddd1!important;border-radius:18px!important;padding:22px!important;box-shadow:0 8px 28px #17351c08;}
.st-key-overview_workspace{color:#203b28;}
.st-key-overview_workspace p,.st-key-overview_workspace label p,.st-key-overview_query p{font-size:16px!important;line-height:1.75;}
.st-key-overview_workspace hr{border-color:#e3ddd1;margin:32px 0;}
.st-key-overview_workspace h2{font-size:24px!important;font-weight:750!important;}
.st-key-overview_workspace h3{font-size:22px!important;}
.st-key-overview_workspace [data-testid="stVerticalBlock"]{gap:18px;}
.st-key-overview_filters{padding:20px!important;background:#fffefa;border-color:#e3ddd1!important;border-radius:16px;}
.st-key-overview_workspace [data-testid="stExpander"]{border-color:#e3ddd1;border-radius:12px;background:#fffefa;}
.st-key-overview_workspace [data-testid="stDataFrame"]{border-color:#e3ddd1;}
.st-key-overview_workspace [data-testid="stVerticalBlockBorderWrapper"]>div{background:#fffefa!important;border-color:#e3ddd1!important;}
.overview-status{display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;font-size:15px;color:#69786d;padding:20px 0;}
.overview-status strong{color:#17421E;font-weight:650;}
.overview-kpi{padding:28px 26px;min-height:190px;background:#fffefa;border:1px solid #dfd8ca;border-radius:20px;box-shadow:0 12px 34px #1d38230a;}
.overview-kpi-label{font-size:18px;font-weight:600;color:#5d6d60;margin-bottom:20px;}
.overview-kpi-value{font-size:clamp(32px,3.3vw,50px);font-weight:750;color:#17421E;line-height:1.3;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;}
.overview-delta{font-size:14px;margin-top:20px;color:#758074;line-height:1.7;}
.overview-delta.good{color:#216d47;}.overview-delta.attention{color:#986720;}
.overview-fraction{font-size:.58em;opacity:.6;}
.overview-platform-title{display:flex;align-items:center;gap:13px;border-bottom:1px solid #e6dfd2;padding:6px 0 18px;margin-bottom:12px;}
.overview-platform-title img{width:34px;height:30px;object-fit:contain;}.overview-platform-title h3{padding:0!important;margin:0;}
.overview-inline{padding:18px 0;}.overview-inline span{display:block;font-size:15px;color:#6b796e;}.overview-inline strong{display:block;font-size:29px;color:#17421E;margin-top:10px;}
.st-key-overview_workspace .mori-money-table{overflow-x:auto;border:1px solid #e3ddd1;border-radius:16px;}
.st-key-overview_workspace .mori-money-table table{width:100%;border-collapse:collapse;background:#fffefa;font-size:16px;}
.st-key-overview_workspace .mori-money-table th{background:#f2eee5;color:#17421E;font-weight:650;text-align:left;padding:18px;white-space:nowrap;}
.st-key-overview_workspace .mori-money-table td{padding:20px 18px;border-top:1px solid #e9e4da;line-height:1.7;}
.st-key-overview_workspace .mori-money-table tbody tr:hover{background:#f8f5ed;}
.overview-start{padding:45px 30px;background:#fffefa;border:1px solid #e3ddd1;border-radius:20px;margin-top:28px;}.overview-start span{color:#9d8151;font-size:14px;}.overview-start h2{font-size:27px!important;color:#17421E;margin:12px 0;}.overview-start p{color:#68756b;}
@media(min-width:1100px){.st-key-overview_query{position:sticky;top:3.7rem;z-index:50;}}
@media(max-width:760px){.overview-kpi{min-height:150px;padding:24px;}.overview-status{font-size:14px;}.st-key-overview_query{padding:16px!important;}.overview-inline strong{font-size:25px;}}
</style>"""
