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

from mori.design_system import stylesheet, page_header

CSS = stylesheet()


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
    st.html(stylesheet())
    st.markdown(page_header('廣告成效總覽','掌握投入與訂位，找出值得調整的地方。','MORI / PERFORMANCE'), unsafe_allow_html=True)
    with st.container(key='overview_query', border=True):
        a, b, c, d = st.columns([1.4, .8, .6, .55], vertical_alignment='bottom')
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
        read = d.button('讀取數據', type='primary', icon=':material/refresh:', key='overview_read',width='stretch')
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
    st.html(stylesheet())
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
        from mori.project_types import PROJECT_TYPES, project_type
        ca, a, b = st.columns([.8, 1.1, 1.25], vertical_alignment='bottom')
        category = ca.selectbox('專案分類', ['全部', *PROJECT_TYPES, '待分類'], key='overview_category')
        visible_groups = {k:v for k,v in grouped.items() if category=='全部' or project_type(groups.get(k, v[0]))==category}
        if st.session_state.get('overview_project') not in ['all', *visible_groups]:
            st.session_state.overview_project='all'
        group_id = a.selectbox('查看專案', ['all'] + list(visible_groups), format_func=lambda k: '全部帳號資料' if k == 'all' else group_name(k), key='overview_project')
        platform = b.radio('查看平台', ['all', 'meta', 'google'], format_func=lambda k: '雙平台' if k == 'all' else PLATFORMS[k], horizontal=True, key='overview_platform')
    selected_plans = grouped.get(group_id)
    if selected_plans and platform != 'all':
        selected_plans = [p for p in selected_plans if account_by_key[p['account_key']]['platform'] == platform]
        if not selected_plans:
            st.info('此專案沒有設定這個平台的計畫。')
            return
    issue = ''
    category_plans = [p for members in visible_groups.values() for p in members] if category != '全部' else None
    scope_plans = selected_plans if selected_plans else category_plans
    shown, issue = project_slice(df, scope_plans, view['period']) if scope_plans is not None else (df, '')
    before = previous
    if scope_plans is not None and before is not None:
        before, previous_issue = project_slice(before, scope_plans, view.get('previous_period', previous_period(view['period'])))
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
    relevant_keys = [p['account_key'] for p in scope_plans] if scope_plans is not None else view['keys']
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
    render_activity_comparison(shown, view, scope_plans is None,
                               {account_by_key[k]['platform'] for k in relevant_keys if k not in loaded})
    with st.expander('進階：單一活動日花費觀察與新舊客試算'):
        if not incomplete:
            render_sweet_spot(shown, view)
        else:
            st.info('帳號資料尚未完整，暫不建立活動觀察。')
    if grouped:
        st.divider()
        st.subheader('各專案成效')
        st.caption('依各專案條件與廣告走期認列；專案可能重疊，不加總成帳號總花費。')
        project_rows, project_platforms = [], []
        for gid, group_plans in visible_groups.items():
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


OVERVIEW_CSS = CSS
