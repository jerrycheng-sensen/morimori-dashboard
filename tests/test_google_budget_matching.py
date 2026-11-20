from datetime import date
import copy
import pytest
from mori.core import AppError
from mori.project_matching import matches, validate_matching
from mori.providers import GoogleProvider
from mori.budgets import collect_spend


def plan(**kw):
    return {'id': 'g1', 'account_key': 'g', 'start': '2026-10-01', 'end': '2026-11-18',
            'match_conditions': [{'field': 'headlines', 'text': '感謝祭'}], **kw}


def test_literal_asset_matching_or_city_and_id():
    p = plan(match_conditions=[{'field': 'headlines', 'text': '桃園|新竹'},
                               {'field': 'descriptions', 'text': '感謝祭'}])
    assert matches(p, {'headlines': ['新竹燒肉'], 'descriptions': ['感謝祭開跑']})
    assert not matches(p, {'headlines': ['台中'], 'descriptions': ['感謝祭']})
    assert not matches(plan(), {'headlines': ['感謝', '祭']})
    assert matches(plan(match_mode='any', match_conditions=[{'field': 'paths', 'text': '感謝祭'},
                   {'field': 'campaign_name', 'text': '感謝祭 PMAX'}]), {'campaign_name': '感謝祭 PMAX'})
    assert not matches(plan(match_conditions=[{'field': 'ad_id', 'text': '123'}]), {'ad_id': '1234'})
    for rules in [[{'field': 'paths', 'text': '|'}], [{'field': 'ad_name', 'text': 'x'}], [{'field': 'ad_id', 'text': '12|34'}]]:
        with pytest.raises(AppError):
            validate_matching(plan(match_conditions=rules), 'google')


def test_google_budget_query_replaces_search_campaign_cost_without_duplicate_assets():
    provider = GoogleProvider({'GOOGLE_CLIENT_ID': 'c', 'GOOGLE_CLIENT_SECRET': 's', 'GOOGLE_REFRESH_TOKEN': 'r'})
    provider.fetch = lambda *_: {'currency': 'TWD', 'timezone': 'Asia/Taipei', 'rows': [
        {'channel': 'SEARCH', 'campaign_id': '10', 'date': '2026-11-01', 'spend': 123.456789}, {'channel': 'PERFORMANCE_MAX', 'spend': 55}]}
    queries = []
    def query(account, sql):
        queries.append(sql)
        return [{'campaign': {'id': '10', 'name': '品牌'}, 'adGroup': {'id': '20', 'name': '高意圖'},
                 'adGroupAd': {'ad': {'id': '30', 'responsiveSearchAd': {
                     'headlines': [{'text': '感謝祭'}, {'text': '感謝祭加碼'}],
                     'descriptions': [{'text': '訂位'}], 'path1': '感謝祭'}}},
                 'segments': {'date': '2026-11-01'}, 'metrics': {'costMicros': '123456789'}}]
    provider.query = query
    result = provider.fetch_budget({'key': 'g'}, '2026-10-01', '2026-11-18')
    assert result['attribution_detail']
    assert len(result['rows']) == 2
    assert sum(r['spend'] for r in result['rows']) == pytest.approx(178.456789)
    assert result['rows'][1]['ad_id'] == '30'
    assert 'FROM ad_group_ad' in queries[0] and 'segments.conversion_action' not in queries[0]


def test_budget_match_once_conflicts_block_and_missing_detail_is_unknown():
    rows = [{'date': '2026-11-01', 'campaign_id': '10', 'ad_id': '30', 'adset_id': '20',
             'headlines': ['感謝祭', '感謝祭加碼'], 'currency': 'TWD', 'spend': 100}]
    def fetch(*_):
        return {'rows': rows, 'currency': 'TWD', 'attribution_detail': True}
    accounts = {'g': {'platform': 'google'}}
    today = date(2026, 11, 20)
    p = plan(match_mode='any', match_conditions=[{'field': 'headlines', 'text': '感謝祭'}, {'field': 'ad_id', 'text': '30'}])
    assert collect_spend([p], accounts, fetch, today)['g1']['spend'] == 100
    conflict = collect_spend([p, {**p, 'id': 'g2'}], accounts, fetch, today)
    assert all('error' in r for r in conflict.values())
    assert 'error' in collect_spend([p], accounts, lambda *_: {'rows': [], 'currency': 'TWD'}, today)['g1']


def test_google_matching_preview_then_save_from_ui():
    from streamlit.testing.v1 import AppTest
    source = """
from mori.budget_ui import render_budgets
from mori.core import default_settings
import streamlit as st
s = default_settings()
s['accounts'] = [{'key':'g','name':'Google','platform':'google','account_id':'123'}]
s['project_groups'] = [{'id':'f','name':'感謝祭','start':'2026-10-01','end':'2026-11-30','status':'已結案'}]
def fetch(*_):
    return {'currency':'TWD','attribution_detail':True,'rows':[{'date':'2026-11-01','campaign_id':'1','ad_id':'2','headlines':['感謝祭'],'currency':'TWD','spend':90}]}
def persist(updated, **kwargs):
    st.session_state.saved = updated
render_budgets(s, fetch, persist)
"""
    app = AppTest.from_string(source, default_timeout=15).run()
    next(x for x in app.selectbox if x.label == '所屬專案').select('f')
    next(x for x in app.text_input if x.label == '平台計畫名稱').set_value('感謝祭 Google')
    app.selectbox(key='budget_field_new_0').select('headlines')
    app.text_input(key='budget_text_new_0').set_value('感謝祭')
    next(x for x in app.date_input if x.label == '廣告開始日（可含預熱）').set_value(date(2026,10,1))
    next(x for x in app.date_input if x.label == '廣告結束日').set_value(date(2026,11,18))
    next(x for x in app.button if x.label == '預覽認列廣告（不儲存）').click().run()
    assert not app.exception and not app.error
    assert any('90.00' in x.value for x in app.success)
    assert 'saved' not in app.session_state
    next(x for x in app.button if x.label == '儲存平台計畫').click().run()
    assert not app.exception and not app.error
    saved = app.session_state['saved']['projects'][0]
    assert saved['match_conditions'] == [{'field':'headlines','text':'感謝祭'}]
