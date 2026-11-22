from datetime import date
from decimal import Decimal
import copy
import pytest

from mori.core import default_settings, AppError
from mori.unassigned import scan, assign, undo
from mori.project_matching import matches
from mori.budgets import collect_spend, save_plan


def setup(platform='meta'):
    s = default_settings()
    s['accounts'] = [{'key':'a','platform':platform,'account_id':'123','name':'主帳號'}]
    s['project_groups'] = [{'id':'g','name':'感謝祭','start':'2026-11-01','end':'2026-11-30','status':'進行中'}]
    s['projects'] = [{'id':'p','group_id':'g','account_key':'a','name':'平台','start':'2026-11-03',
                      'end':'2026-11-10','status':'已結案','keyword':'Known','budget':1000}]
    return s


def fetch(account, start, end):
    row = {'campaign_id':'1','campaign_name':'活動','adset_id':'2','adset_name':'群組',
           'date':str(start),'date_stop':str(end),'currency':'TWD','spend':23.615,'spend_raw':'23.615'}
    return {'currency':'TWD','attribution_detail':True,
            'rows':[{**row,'ad_id':'10','ad_name':'Known','campaign_name':'Known'}, {**row,'ad_id':'20','ad_name':'Other','campaign_name':'Other'}]}


def test_scan_checks_dates_even_for_closed_plan_and_decimal_cost():
    s = setup()
    r = scan(s, fetch, '2026-11-01', '2026-11-12')
    assert not r['errors']
    assert len(r['covered']) == 1
    assert r['covered'][0]['since'] == '2026-11-03'
    assert len(r['pending']) == 5  # Known before/after its plan, Other in all 3 segments.
    assert all(Decimal(x['amount']) == Decimal('23.615') for x in r['pending'])


def test_assign_exact_id_does_not_change_budget_or_text_rule_and_is_reversible():
    s = setup()
    item = next(x for x in scan(s, fetch, '2026-11-03', '2026-11-10')['pending'] if x['unit']['id'] == '20')
    updated = assign(s, fetch, item, 'p', date(2026,11,22))
    assert not s['projects'][0].get('assigned_units')
    assert updated['projects'][0]['budget'] == 1000
    assert updated['projects'][0]['keyword'] == 'Known'
    assert not scan(updated, fetch, '2026-11-03', '2026-11-10')['pending']
    reports = collect_spend(updated['projects'], {'a':s['accounts'][0]}, fetch, date(2026,11,22))
    assert reports['p']['spend_raw'] == '47.230'
    assert len(reports['p']['rows']) == 2
    reverted = undo(updated, 'p', item['unit'])
    assert len(reverted['projects'][0]['assignment_history']) == 2
    assert len(scan(reverted, fetch, '2026-11-03', '2026-11-10')['pending']) == 1
    with pytest.raises(AppError, match='已有歸屬'):
        assign(updated, fetch, item, 'p', date(2026,11,22))


def test_assignment_limits_cost_to_target_dates_and_rejects_wrong_account():
    s = setup()
    item = next(x for x in scan(s, fetch, '2026-11-01', '2026-11-12')['pending'] if x['unit']['id'] == '20')
    item = {**item, 'since':'2026-11-01','until':'2026-11-12'}
    updated = assign(s, fetch, item, 'p', date(2026,11,22))
    r = scan(updated, fetch, '2026-11-01', '2026-11-12')
    assert any(x['unit']['id'] == '20' and x['until'] == '2026-11-02' for x in r['pending'])
    assert any(x['unit']['id'] == '20' and x['since'] == '2026-11-11' for x in r['pending'])
    with pytest.raises(AppError, match='走期'):
        assign(s, fetch, {**item,'since':'2026-11-11','until':'2026-11-12'}, 'p')
    with pytest.raises(AppError, match='同一廣告帳號'):
        assign(s, fetch, {**item,'physical':('meta','999')}, 'p')


def test_conflicts_are_not_unassigned_and_block_stale_assignment():
    s = setup()
    item = scan(s, fetch, '2026-11-03', '2026-11-10')['pending'][0]
    s['projects'].append({**s['projects'][0], 'id':'p2','group_id':'', 'keyword':'Other'})
    with pytest.raises(AppError, match='已有歸屬'):
        assign(s, fetch, item, 'p')
    s['projects'][0]['keyword'] = 'Other'
    r = scan(s, fetch, '2026-11-03', '2026-11-10')
    assert r['conflicts'][0]['owners'] == ['p','p2']
    assert all(x['unit']['id'] != '20' for x in r['pending'])


@pytest.mark.parametrize('failure', ['bad_currency','duplicate','missing_id','negative','failed','warnings'])
def test_incomplete_reads_never_report_no_missing_ads(failure):
    def broken(a, start, end):
        r = fetch(a,start,end)
        if failure == 'failed': raise AppError('授權失敗')
        if failure == 'bad_currency': r['rows'][0]['currency']='USD'
        if failure == 'duplicate': r['rows'].append(dict(r['rows'][0]))
        if failure == 'missing_id': r['rows'][0]['ad_id']=''
        if failure == 'negative': r['rows'][0]['spend_raw']='-1'
        if failure == 'warnings': r['warnings']=['尚未同步']
        return r
    r = scan(setup(), broken, '2026-11-03', '2026-11-10')
    assert r['errors'] and not r['pending'] and not r['covered']


def test_google_pmax_assignment_uses_asset_group_not_blank_ad_id():
    s = setup('google')
    def pmax(a,start,end):
        r = fetch(a,start,end)
        r['rows'] = [{**r['rows'][1], 'ad_id':'','adset_id':'','asset_group_id':'99','asset_group_name':'新素材群組','channel':'PERFORMANCE_MAX'}]
        return r
    item = scan(s,pmax,'2026-11-03','2026-11-10')['pending'][0]
    updated = assign(s,pmax,item,'p')
    assert item['unit']['kind'] == 'asset_group'
    assert matches(updated['projects'][0], pmax(None,'2026-11-03','2026-11-10')['rows'][0])
    assert not scan(updated,pmax,'2026-11-03','2026-11-10')['pending']


def test_duplicate_account_config_is_scanned_once_and_manual_binding_survives_edit():
    s=setup()
    s['accounts'].append({**s['accounts'][0], 'key':'b','account_id':'act_123'})
    calls=[]
    def counted(*args): calls.append(1); return fetch(*args)
    item=scan(s,counted,'2026-11-03','2026-11-10')['pending'][0]
    assert len(calls)==1
    updated=assign(s,fetch,item,'p')
    updated=save_plan(updated, {**updated['projects'][0],'name':'改名'})
    assert updated['projects'][0]['assigned_units']
    with pytest.raises(AppError,match='先撤銷'):
        save_plan(updated, {**updated['projects'][0],'account_key':'b'})


def test_ui_scans_then_assigns_and_refreshes_project_totals_without_changing_budget():
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    source = '''
import streamlit as st
from mori.budget_ui import render_budgets
from tests.test_unassigned import setup, fetch
s = st.session_state.setdefault('settings', setup())
def save(updated, **kwargs):
    st.session_state.settings = updated
    st.session_state.pop('budget_view', None)
    st.rerun()
render_budgets(s, fetch, save, None, None)
'''
    # Tests isn't a package on every deployment; embed the fixture functions directly.
    import inspect
    source = source.replace('from tests.test_unassigned import setup, fetch',
                            'from mori.core import default_settings\n' + inspect.getsource(setup) + '\n' + inspect.getsource(fetch))
    app = AppTest.from_string(source,default_timeout=15).run()
    assert not app.exception
    app.button(key='unassigned_scan').click().run()
    assert not app.exception
    assert any('待歸案花費' in m.value and 'Other' in m.value for m in app.markdown)
    app.selectbox(key='unassigned_unit').set_value(0).run()
    app.selectbox(key='unassigned_target').set_value('p').run()
    next(c for c in app.checkbox if c.label.startswith('已確認廣告內容')).check()
    next(b for b in app.button if b.label == '確認歸案').click().run()
    assert not app.exception, [e.value for e in app.exception]
    saved = app.session_state['settings']
    assert saved['projects'][0]['assigned_units'][0]['id'] == '20'
    assert saved['projects'][0]['budget'] == 1000
    assert app.session_state['budget_view']['results']['p']['spend_raw'] == '47.230'
    app.button(key='unassigned_undo').click().run()
    assert not app.exception
    assert app.session_state['budget_view']['results']['p']['spend_raw'] == '23.615'
