import pandas as pd
import pytest

from mori.dashboard import filter_rows, summary_table, totals, trend_data


def rows():
    return pd.DataFrame([
        dict(account_key='m', platform='meta', date='2026-11-16', campaign_id='1', campaign_name='開幕 [A]',
             ad_name='永華店', channel='META', currency='TWD', spend=120., conversions=2., impressions=1000., clicks=10.),
        dict(account_key='g', platform='google', date='2026-11-16', campaign_id='1', campaign_name='開幕 [A]',
             ad_name='永華店', channel='SEARCH', currency='TWD', spend=60., conversions=1.5, impressions=500., clicks=5.)])


def test_summary_keeps_platforms_and_fractional_attribution_separate():
    result = summary_table(rows(), {'m': 'Meta帳號', 'g': 'Google帳號'})
    assert len(result) == 2
    meta = result[result['平台'] == 'Meta'].iloc[0]
    google = result[result['平台'] == 'Google Ads'].iloc[0]
    assert meta['訂位'] == 2 and meta['CPA'] == 60
    assert google['訂位'] == 1.5 and google['CPA'] == 40


def test_missing_conversion_does_not_become_zero_or_partial_total():
    data = rows()
    data.loc[1, 'conversions'] = None
    assert totals(data)['bookings'] is None
    assert totals(data)['cpa'] is None
    assert pd.isna(trend_data(data, 'conversions').iloc[0]['value'])
    assert totals(data)['spend'] == 180


def test_project_and_search_filters_are_literal_and_account_scoped():
    data = rows()
    project = {'account_key': 'm', 'match_field': 'ad_name', 'keyword': '永華'}
    result = filter_rows(data, project, '[A]', ['META', 'SEARCH'])
    assert result.account_key.tolist() == ['m']
    assert filter_rows(data, query='[').shape[0] == 2
    assert filter_rows(data, channels=[]).empty
    assert filter_rows(data, {**project, 'match_field': 'missing'}).empty


def test_previous_period_has_equal_inclusive_days_across_month_and_year():
    from mori.dashboard import previous_period
    from datetime import date
    assert previous_period(('2026-11-03','2026-11-23')) == (date(2026,10,13), date(2026,11,2))
    assert previous_period(('2026-01-01','2026-01-01')) == (date(2025,12,31), date(2025,12,31))


def test_exact_spend_sums_raw_precision_before_display_and_zero_baseline_delta():
    from mori.dashboard import metric_delta
    from decimal import Decimal
    data = rows()
    data['spend_raw'] = ['1.004999','1.004999']
    assert totals(data)['spend'] == Decimal('2.009998')
    assert metric_delta(33,0)[0] == '前期為 0，無法計算升降'
    assert metric_delta(0,0)[0] == '與前期相同'
    assert metric_delta(None,100)[0] == '尚無可比較資料'
    assert metric_delta(80,100,lower=True) == ('下降 20.0% · 對比前期','good')


def test_project_union_respects_dates_account_and_no_duplicate_rows():
    from mori.dashboard import project_slice
    data = rows()
    extra = data.iloc[[0]].copy()
    extra['date'] = '2026-11-15'
    data = pd.concat([data,extra],ignore_index=True)
    plan = {'account_key':'m','start':'2026-11-16','end':'2026-11-18','match_field':'ad_name','keyword':'永華'}
    selected, issue = project_slice(data,[plan,plan],('2026-11-01','2026-11-30'))
    assert not issue and selected.index.tolist() == [0]
    assert totals(selected)['spend'] == 120
    google = {**plan,'account_key':'g'}
    selected, issue = project_slice(data,[google],('2026-11-01','2026-11-30'))
    assert selected.empty and 'Google' in issue


def test_overview_unknown_names_are_not_treated_as_unmatched_or_zero():
    from mori.dashboard import project_slice
    data = rows().iloc[[0]].copy()
    data['names_verified'] = False
    data['verified_name_fields'] = [[]]
    plan = {'account_key':'m','start':'2026-11-01','end':'2026-11-30','keyword':'開幕'}
    selected, issue = project_slice(data,[plan],('2026-11-01','2026-11-30'))
    assert selected.empty and '尚未核對' in issue


def test_overview_failed_account_hides_combined_total_but_keeps_valid_platform():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
from mori.dashboard import render_report
render_report(st.session_state.view,['m','g'],('2026-11-16','2026-11-16'),st.session_state.settings,{'m':'Meta','g':'Google'},st.session_state.accounts)
''',default_timeout=15)
    app.session_state['accounts'] = {'m':{'platform':'meta','meta_action_type':'booking'},'g':{'platform':'google'}}
    app.session_state['settings'] = {'projects':[]}
    app.session_state['view'] = {'reports':[{'rows':rows().iloc[[0]].to_dict('records'),'currency':'TWD','timezone':'Asia/Taipei'}],
                                 'errors':['Google 讀取失敗'],'keys':['m','g'],'loaded_keys':['m'],
                                 'period':('2026-11-16','2026-11-16'),'at':'2026-11-17T09:00:00+08:00'}
    app.run()
    assert not app.exception
    kpis = [m.value for m in app.markdown if '<article class="overview-kpi">' in m.value]
    assert len(kpis)==3 and all('<div class="overview-kpi-value">—</div>' in k for k in kpis)
    assert any('data-money-value="$120"' in m.value for m in app.markdown)
    assert any('資料讀取不完整' in m.value for m in app.warning)
