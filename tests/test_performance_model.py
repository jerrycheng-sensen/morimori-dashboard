from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from mori.performance_model import (campaign_type, metric_bundle, comparative_rows, spend_response,
                                    acquisition_plan, direct_reach)


def data(conversions=(10,18,18)):
    output=[]
    for i in range(36):
        band=i//12
        output.append({'account_key':'m','platform':'meta','currency':'TWD','campaign_id':'123',
                       'campaign_name':'同一活動','campaign_objective':'OUTCOME_SALES','channel':'META',
                       'date':str(date(2026,1,1)+timedelta(days=i)),'spend':100*(band+1),
                       'conversions':conversions[band],'impressions':1000,'clicks':100,'engagements':150})
    return pd.DataFrame(output)


def test_campaign_classification_uses_api_objective_not_name():
    assert campaign_type({'platform':'meta','campaign_name':'轉換｜測試'})=='待分類／其他目標'
    for objective, expected in [('OUTCOME_AWARENESS','曝光'),('OUTCOME_ENGAGEMENT','互動'),('OUTCOME_TRAFFIC','流量'),('OUTCOME_SALES','轉換')]:
        assert campaign_type({'platform':'meta','campaign_objective':objective,'campaign_name':'曝光'})==expected
    assert campaign_type({'platform':'google','channel':'SEARCH'})=='搜尋'
    assert campaign_type({'platform':'google','channel':'PERFORMANCE_MAX'})=='PMax'
    assert campaign_type({'platform':'google','channel':'DISPLAY'})=='其他類型'


def test_metric_ratios_are_weighted_and_missing_values_are_not_zero():
    frame=data().iloc[:2].copy()
    frame['spend']=[100,900];frame['impressions']=[100,10000];frame['clicks']=[10,10];frame['conversions']=[1,1]
    metric=metric_bundle(frame)
    assert metric['ctr']==Decimal(20)/Decimal(10100)
    assert metric['cpa']==Decimal(500)
    assert metric['booking_click_rate']==Decimal('.1')
    frame.loc[0,'engagements']=None
    frame.loc[0,'conversions']=None
    metric=metric_bundle(frame)
    assert metric['interactions'] is None and metric['cpe'] is None and metric['booking_click_rate'] is None
    frame['platform']='google';frame['interactions']=[2,3]
    assert metric_bundle(frame)['interactions']==5
    assert comparative_rows(frame)[0]['主要觀察']=='未分類'


def test_observed_marginal_plateau_candidate_is_not_an_automatic_budget_limit():
    result=spend_response(data(),'2026-12-31',Decimal(15))
    assert result['best']['cpa']==10
    assert result['upper']['mean_spend']==200
    assert result['bands'][1]['marginal_cpa']==Decimal('12.5')
    assert result['bands'][2]['plateau']
    assert '候選' in result['status'] and '驗證' in result['status']


def test_no_upper_is_invented_when_response_still_grows_or_target_is_unset():
    result=spend_response(data((10,20,30)),'2026-12-31',Decimal(15))
    assert result['upper'] is None and '尚未找到上限' in result['status']
    unset=spend_response(data(),'2026-12-31')
    assert unset['upper'] is None and '請先設定' in unset['status']
    bad=spend_response(data(),'2026-12-31',Decimal(5))
    assert bad['upper'] is None


def test_model_guards_small_sample_immature_dates_unknowns_and_mixed_campaigns():
    assert spend_response(data().iloc[:15],'2026-12-31',15)['best'] is None
    assert spend_response(data(),'2026-01-15',15)['upper'] is None
    mixed=data();mixed.loc[0,'campaign_id']='456'
    assert '同一活動' in spend_response(mixed,'2026-12-31',15)['status']
    missing=data();missing.loc[0,'conversions']=None
    assert '缺漏' in spend_response(missing,'2026-12-31',15)['status']
    negative=data();negative.loc[0,'conversions']=-1
    assert '負向調整' in spend_response(negative,'2026-12-31',15)['status']
    constant=data();constant['spend']=100
    assert spend_response(constant,'2026-12-31',15)['upper'] is None


def test_zero_booking_spend_is_retained_and_invalid_dates_do_not_make_cpa_free():
    frame=data();frame['conversions']=0
    result=spend_response(frame,'2026-12-31',15)
    assert result['days']==36 and all(b['spend']>0 and b['cpa'] is None for b in result['bands'])
    assert result['best'] is None and result['upper'] is None


def test_4_to_6_is_a_booking_target_not_a_budget_split():
    plan=acquisition_plan(60,150)
    assert plan['new_bookings']==40 and plan['new_budget']==6000
    assert acquisition_plan(0,150) is None
    assert acquisition_plan(60,0) is None


def test_reach_is_same_scope_period_only_and_never_summed():
    reports=[{'account_key':'m','reach_metrics':[{'scope':'campaign','campaign_id':'123','since':'2026-01-01','until':'2026-01-31','reach':1234}]}]
    assert direct_reach(reports,'m','123',('2026-01-01','2026-01-31'))==1234
    assert direct_reach(reports,'m','123',('2026-01-02','2026-01-31')) is None
    assert direct_reach(reports,'other','123',('2026-01-01','2026-01-31')) is None
    assert direct_reach(reports+reports,'m','123',('2026-01-01','2026-01-31')) is None


def test_observation_and_ratio_ui_update_locally_without_modifying_report():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string('''
import streamlit as st
from mori.performance_model import render_sweet_spot
render_sweet_spot(st.session_state.frame,st.session_state.view)
''',default_timeout=15)
    frame=data()
    app.session_state['frame']=frame
    app.session_state['view']={'period':('2026-01-01','2026-02-05')}
    app.run()
    assert not app.exception
    app.number_input(key='model_target_cpa').set_value(15.).run()
    assert not app.exception
    assert any('找到上限觀察候選' in m.value for m in app.markdown)
    app.radio(key='model_mode').set_value('新舊客 4:6 試算').run()
    app.number_input(key='model_old_bookings').set_value(60.)
    app.number_input(key='model_new_cpa').set_value(150.).run()
    assert not app.exception
    assert any('data-money-value="$6,000.00"' in m.value for m in app.markdown)
    assert app.session_state['frame'].equals(frame)
