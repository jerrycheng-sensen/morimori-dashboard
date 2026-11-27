"""Whole-project sources, scheduling snapshots and honest model boundaries."""
import copy
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from mori.core import AppError, TAIPEI, default_settings, validate_settings
from mori.festival_model import collect_projects, fit_projects, hill, projection, refresh_snapshot, SNAPSHOT_PATH
from mori.project_types import BASELINE_NAMES, baseline_groups, project_type
from mori.providers import GoogleProvider, MetaProvider


def settings():
    s=default_settings()
    s['accounts']=[{'key':'g','name':'Google','platform':'google','account_id':'123','google_action_ids':['7']}]
    s['project_groups']=[{'id':str(i),'name':name,'start':'2026-10-01','end':'2026-11-30','status':'已結案'} for i,name in enumerate(BASELINE_NAMES)]
    s['projects']=[{'id':'p'+str(i),'group_id':str(i),'account_key':'g','name':name,'start':'2026-10-01','end':'2026-11-18','status':'已結案','budget':10000,'keyword':name,'match_field':'campaign_name'} for i,name in enumerate(BASELINE_NAMES)]
    return s


def report():
    return {'currency':'TWD','attribution_detail':True,'rows':[
        {'date':'2026-11-18','campaign_id':str(i+1),'ad_id':str(i+10),'campaign_name':name,'spend_raw':'100.123456','spend':100.123456,'conversion_raw':'2.5','conversions':2.5}
        for i,name in enumerate(BASELINE_NAMES)]}


class Provider:
    def __init__(self): self.calls=[];self.fail=False;self.bookings='2.5'
    def fetch_model(self,a,start,end):
        self.calls.append((start,end))
        if self.fail: raise AppError('讀取失敗，不當成零。')
        result=report()
        for row in result['rows']: row['conversion_raw']=self.bookings
        result.update(events_audited=True,event_catalog=[{'id':'7','name':'訂位'}])
        return result


class Store:
    def __init__(self): self.data={};self.writes=0
    def read(self,path,default): return copy.deepcopy(self.data.get(path,default)),str(self.writes)
    def write(self,path,value,sha,**kwargs):
        assert sha==str(self.writes)
        self.data[path]=copy.deepcopy(value);self.writes+=1


def test_category_confirmed_names_legacy_and_explicit_override():
    s=settings()
    assert all(project_type(g)=='檔期' for g in baseline_groups(s))
    assert project_type({'name':'新北林口店｜開幕'})=='新店開幕'
    assert project_type({'name':'桃竹四家加碼案'})=='特殊專案'
    assert project_type({'name':'尚未確認的活動'})=='待分類'
    s['project_groups'][0]['category']='特殊專案'
    with pytest.raises(AppError,match='須分類為檔期'): baseline_groups(s)
    s['project_groups'][0]['category']='任意分類'
    with pytest.raises(AppError): validate_settings(s)


def test_closed_project_reads_ad_end_not_parent_end_and_preserves_micros():
    p=Provider();s=settings()
    output=collect_projects(s,lambda _:p,datetime(2026,11,27,tzinfo=TAIPEI))
    assert p.calls==[(date(2026,10,1),date(2026,11,18))]  # shared account/window cache
    assert all(x['ad_end']=='2026-11-18' and x['read_through']=='2026-11-18' for x in output)
    assert all(Decimal(x['spend'])==Decimal('100.123456') and x['bookings']=='2.5' for x in output)
    assert len(output[0]['rows'])==49
    assert output[0]['last_paid_date']=='2026-11-18'
    s['project_groups'][0]['status']='進行中';s['projects'][0]['status']='準備中'
    assert collect_projects(s,lambda _:p,datetime(2026,11,27,tzinfo=TAIPEI))==output


def test_snapshot_refresh_after_close_backfills_and_failure_keeps_last_success():
    s=settings();p=Provider();store=Store();now=datetime(2026,11,27,tzinfo=TAIPEI)
    old=refresh_snapshot(store,s,lambda _:p,now)
    assert old['mature_through']=='2026-11-23'
    assert refresh_snapshot(store,s,lambda _:p,now)==old and store.writes==1
    p.bookings='3.5'
    updated=refresh_snapshot(store,s,lambda _:p,now+timedelta(days=1))
    assert updated['projects'][0]['bookings']=='3.5'
    p.fail=True
    failed=refresh_snapshot(store,s,lambda _:p,now+timedelta(days=2))
    assert failed['projects']==updated['projects'] and failed['updated_at']==updated['updated_at']
    assert failed['last_error'] and store.data[SNAPSHOT_PATH]['last_error']


def test_uncertain_names_missing_conversion_and_overlap_are_not_zero():
    s=settings()
    for change in ('names','conversion','overlap'):
        r=report()
        if change=='names': r['rows'][0].update(names_verified=False,verified_name_fields=[])
        if change=='conversion': r['rows'][0]['conversion_raw']=None
        if change=='overlap': s['projects'][1]['keyword']=BASELINE_NAMES[0]
        p=type('P',(),{'fetch_model':lambda *_:r})()
        with pytest.raises(AppError): collect_projects(s,lambda _:p,datetime(2026,11,27,tzinfo=TAIPEI))


def synthetic():
    result=[]
    for j in range(2):
        rows=[]
        for i in range(64):
            x=50+(i*17%63)*15
            rows.append({'date':str(date(2026,6,1)+timedelta(days=i)),'spend':str(x),'bookings':str((100+j*20)*hill(x,350,2))})
        result.append({'id':str(j),'rows':rows})
    return result


def test_two_flights_holdout_and_whole_budget_scale():
    fitted=fit_projects(synthetic(),date(2026,9,1))
    assert fitted['status']=='estimated' and len(fitted['checks'])==2
    one=projection(fitted,'0',30,10)
    two=projection(fitted,'0',60,10)
    assert one['sweet'] and two['sweet']['budget']==pytest.approx(one['sweet']['budget']*2)
    assert two['sweet']['cpa']==pytest.approx(one['sweet']['cpa'])
    assert one['upper'] and one['upper']['budget']>one['sweet']['budget']
    assert projection(fitted,'0',30)['upper'] is None
    fitted['slope']=1
    assert projection(fitted,'0',30,10)['sweet'] is None


def test_bad_holdout_or_insufficient_data_never_gives_numbers():
    projects=synthetic()
    assert fit_projects(projects,date(2026,6,10))['status']=='insufficient'
    for project in projects:
        for row in project['rows'][48:]: row['bookings']='100000'
    fit=fit_projects(projects,date(2026,9,1))
    assert fit['status']=='unreliable'
    assert projection(fit,'0',60)=={'sweet':None,'upper':None,'curve':[]}


def google_fixture():
    provider=GoogleProvider({'GOOGLE_CLIENT_ID':'c','GOOGLE_CLIENT_SECRET':'s','GOOGLE_REFRESH_TOKEN':'r'})
    data={'attribution_detail':True,'rows':[
        {'campaign_id':'1','ad_id':'10','date':'2026-11-01','channel':'SEARCH','spend':100},
        {'campaign_id':'2','asset_group_id':'20','date':'2026-11-01','channel':'PERFORMANCE_MAX','spend':200}],
        'campaign_rows':[{'campaign_id':'1','date':'2026-11-01','conversions':1.25},{'campaign_id':'2','date':'2026-11-01','conversions':2.5}]}
    provider.fetch_budget=lambda *_:copy.deepcopy(data)
    queries=[]
    def query(account,sql):
        queries.append(sql)
        if 'FROM conversion_action' in sql: return [{'conversionAction':{'id':'7','name':'指定訂位'}},{'conversionAction':{'id':'8','name':'其他事件'}}]
        assert 'metrics.cost_micros' not in sql and 'segments.conversion_action' in sql
        asset='FROM asset_group ' in sql
        return [{'campaign':{'id':'2' if asset else '1'},
                 'assetGroup':{'id':'20'},'adGroupAd':{'ad':{'id':'10'}},
                 'segments':{'date':'2026-11-01','conversionAction':'customers/123/conversionActions/'+action},
                 'metrics':{'allConversions':amount}} for action,amount in [('7','2.5' if asset else '1.25'),('8','999')]]
    provider.query=query
    return provider,data,queries


def test_google_model_selected_booking_join_to_search_and_pmax():
    provider,data,queries=google_fixture()
    r=provider.fetch_model(settings()['accounts'][0],date(2026,11,1),date(2026,11,1))
    assert [r['conversion_raw'] for r in r['rows']]==['1.25','2.5']
    assert len(queries)==3 and all('999' not in str(r['conversions']) for r in r['rows'])
    assert 'conversions' not in data['rows'][0]  # no cached budget mutation


@pytest.mark.parametrize('issue',['mismatch','duplicate','unmatched','failure'])
def test_google_model_incomplete_sources_fail_closed(issue):
    provider,data,_=google_fixture();query=provider.query
    if issue=='mismatch': data['campaign_rows'][0]['conversions']=8
    def broken(account,sql):
        if issue=='failure': raise AppError('失敗')
        rows=query(account,sql)
        if issue=='duplicate': return rows+rows
        if issue=='unmatched': rows[0]['adGroupAd']['ad']['id']='999'
        return rows
    provider.query=broken
    with pytest.raises(AppError): provider.fetch_model(settings()['accounts'][0],date(2026,11,1),date(2026,11,1))


def test_meta_model_current_names_whole_period_cost_and_missing_name():
    provider=MetaProvider({'META_ACCESS_TOKEN':'fake'})
    provider.fetch=lambda *_:{'rows':[{'ad_id':'1','ad_name':'舊名稱','spend':34,'conversions':1},{'ad_id':'2','spend':10,'conversions':0}]}
    provider.fetch_budget=lambda *_:{'rows':[{'ad_id':'1','ad_name':'新名稱','names_verified':True,'spend_raw':'33','spend':33}]}
    account={'platform':'meta','meta_action_type':'purchase'}
    result=provider.fetch_model(account,date(2026,4,1),date(2026,5,1))
    assert result['rows'][0]['ad_name']=='新名稱' and result['rows'][0]['spend']==34
    assert result['whole_rows'][0]['spend_raw']=='33'
    assert result['rows'][1]['names_verified'] is False


def test_classification_ui_persists_and_whole_model_entry_renders():
    from streamlit.testing.v1 import AppTest
    source='''
import streamlit as st
from mori.budget_ui import render_budgets
from mori.core import default_settings
s=default_settings()
s['accounts']=[{'key':'g','name':'Google','platform':'google','account_id':'123'}]
s['project_groups']=[{'id':'f','name':'感謝祭第5彈','start':'2026-10-01','end':'2026-11-30','status':'進行中'}]
def persist(updated,**kwargs): st.session_state.saved=updated
render_budgets(s,lambda *_: {'currency':'TWD','rows':[]},persist)
'''
    app=AppTest.from_string(source,default_timeout=15).run()
    app.button(key='budget_nav_edit').click().run()
    app.selectbox(key='budget_group_editor').select('f').run()
    app.selectbox(key='budget_category_f').select('特殊專案')
    next(b for b in app.button if b.label=='儲存專案資料').click().run()
    assert not app.exception and app.session_state['saved']['project_groups'][0]['category']=='特殊專案'


def test_model_ui_uses_private_snapshot_and_does_not_refetch_on_view_change():
    from streamlit.testing.v1 import AppTest
    source='''
import streamlit as st
from datetime import datetime
from mori.core import TAIPEI
from mori.festival_model import source_signature
from mori.festival_ui import render_festival_model
from mori.invoices import DemoInvoiceStore
s=st.session_state.config
snapshot=st.session_state.snapshot
store=DemoInvoiceStore()
store.write('festival-model.json',snapshot,None)
def no_fetch(*args): raise AssertionError('畫面切換不可重讀 API')
render_festival_model(s,store,no_fetch,lambda *args,**kwargs:None)
'''
    app=AppTest.from_string(source,default_timeout=15)
    s=settings();projects=collect_projects(s,lambda _:Provider(),datetime(2026,11,27,tzinfo=TAIPEI))
    from mori.festival_model import source_signature
    for project,data in zip(projects,synthetic()): project['rows']=data['rows']
    fit=fit_projects(projects,date(2026,11,23))
    app.session_state['config']=s
    app.session_state['snapshot']={'source_signature':source_signature(s),'updated_at':'2026-11-27T09:15:00+08:00','projects':projects,'fit':fit}
    app.run()
    assert not app.exception
    app.selectbox(key='festival_reference').select('1').run()
    assert not app.exception
    app.radio(key='festival_curve').set_value('邊際 CPA').run()
    assert not app.exception
    assert any('模型估計' in m.value for m in app.markdown)


def test_app_model_mode_no_data_shows_setup_without_fake_numbers(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('DEMO_MODE','true')
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=15).run()
    app.radio(key='overview_mode').set_value('檔期投資模型').run()
    assert not app.exception and any('尚無檔期專案' in x.value for x in app.info)


def test_malformed_provider_retains_last_snapshot_and_redacts_exception():
    s=settings();p=Provider();store=Store();now=datetime(2026,11,27,tzinfo=TAIPEI)
    good=refresh_snapshot(store,s,lambda _:p,now)
    def invalid(_): raise ValueError('sensitive request content')
    bad=refresh_snapshot(store,s,invalid,now+timedelta(days=1))
    assert bad['projects']==good['projects'] and bad['fit']==good['fit']
    assert 'sensitive' not in bad['last_error']


def test_all_festival_categories_and_status_independent_signature():
    from mori.festival_model import source_signature
    from mori.project_types import festival_groups
    s=settings();s['project_groups'].append({'id':'third','name':'下一檔','category':'檔期','start':'2026-11-01','end':'2026-12-31','status':'準備中'})
    assert len(festival_groups(s))==3
    signature=source_signature(s)
    for g in s['project_groups']: g['status']='進行中'
    for p in s['projects']: p['status']='進行中'
    assert source_signature(s)==signature
    s['projects'][0]['end']='2026-12-31'
    p=Provider();out=collect_projects(s,lambda _:p,datetime(2026,11,27,tzinfo=TAIPEI))
    assert out[0]['read_through']=='2026-11-27'


def test_individual_fit_bad_new_project_does_not_hide_other_flights():
    from mori.festival_model import build_models,current_projection
    data=synthetic();data.append({'id':'new','name':'新檔','rows':data[0]['rows'][:5]})
    for p in data: p.setdefault('name',p['id'])
    models=build_models(data,date(2026,9,1))
    assert models['individual']['new']['status']=='insufficient'
    assert models['aggregate']['included_ids']==['0','1']
    assert models['aggregate']['fit']['status']=='estimated'
    assert current_projection(models['individual']['new'],data[2],30)['candidate']['basis']=='historical_observation'


def test_boundary_result_visible_without_calling_it_validated_optimum():
    from mori.festival_model import current_projection
    fit=fit_projects(synthetic(),date(2026,9,1));fit['slope']=1
    result=current_projection(fit,synthetic()[0],30)
    assert result['sweet'] is None and result['candidate']['basis']=='model_boundary'
    assert '尚未證明' in result['diagnosis']


def test_snapshot_hourly_refresh_not_waiting_for_closure_or_midnight():
    s=settings();p=Provider();store=Store();now=datetime(2026,11,27,10,tzinfo=TAIPEI)
    old=refresh_snapshot(store,s,lambda _:p,now);p.bookings='4.5'
    assert refresh_snapshot(store,s,lambda _:p,now+timedelta(minutes=30))==old
    result=refresh_snapshot(store,s,lambda _:p,now+timedelta(minutes=61))
    assert result['projects'][0]['bookings']=='4.5'


def test_normalized_pool_accepts_more_than_two_flights_without_summing_budget():
    from mori.festival_model import build_models,current_projection
    data=synthetic();third=copy.deepcopy(data[0]);third['id']='third'
    for row in third['rows']:
        row['spend']=str(Decimal(row['spend'])*10)
        row['bookings']=str(Decimal(row['bookings'])*10)
    data.append(third)
    for p in data: p['name']=p['id']
    models=build_models(data,date(2026,9,1))
    assert models['aggregate']['fit']['status']=='estimated'
    assert models['aggregate']['included_ids']==['0','1','third']
    result=current_projection(models['aggregate']['fit'],{'id':'all'},30)
    assert result['candidate'] and result['candidate']['budget']<100000
