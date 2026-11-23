from datetime import date
import copy
import pytest

from mori.meta_names import refresh_names
from mori.core import AppError, default_settings
from mori.unassigned import scan
from mori.budgets import collect_spend, configuration_key
from mori.project_matching import matches


def history():
    return {'ad_id':'101','campaign_id':'1','adset_id':'2','ad_name':'林口新開幕／素材B',
            'campaign_name':'舊活動','adset_name':'舊群組','currency':'TWD','spend':92166.,'spend_raw':'92166',
            'date':'2026-11-01','date_stop':'2026-11-10'}


def metadata(identifier='101'):
    return {'id':identifier,'account_id':'123','name':'林口開幕｜素材B',
            'campaign':{'id':'1','name':'林口開幕活動'},'adset':{'id':'2','name':'林口新客'},
            'effective_status':'PAUSED'}


def settings():
    s=default_settings()
    s['accounts']=[{'key':'m','platform':'meta','account_id':'act_123','name':'Meta'}]
    s['project_groups']=[{'id':'g','name':'林口開幕','start':'2026-11-01','end':'2026-11-10','status':'已結案'}]
    s['projects']=[{'id':'p','group_id':'g','name':'Meta','account_key':'m','budget':100000,'keyword':'林口開幕',
                    'match_field':'ad_name','start':'2026-11-01','end':'2026-11-10','status':'已結案'}]
    return s


def test_renamed_ad_matches_latest_name_without_changing_cost_or_identity():
    s=settings();r=history();original=copy.deepcopy(r)
    calls=[]
    def get(path, params):
        calls.append((path, params))
        return {'101':metadata()}
    refresh_names(get, s['accounts'][0], [r])
    assert r['names_verified'] and r['ad_name']=='林口開幕｜素材B'
    assert r['insights_ad_name']==original['ad_name'] and r['renamed']
    assert r['campaign_name']=='林口開幕活動' and r['adset_name']=='林口新客'
    assert r['spend_raw']==original['spend_raw'] and r['ad_id']==original['ad_id']
    assert matches(s['projects'][0],r) and not matches(s['projects'][0],original)
    def fetch(*_): return {'rows':[dict(r)],'currency':'TWD'}
    result=scan(s,fetch,'2026-11-01','2026-11-10')
    assert not result['pending'] and not result['unverified'] and len(result['covered'])==1
    costs=collect_spend(s['projects'],{'m':s['accounts'][0]},fetch,date(2026,11,22))
    assert costs['p']['spend_raw']=='92166' and costs['p']['rows'][0]['ad_name']==r['ad_name']
    assert calls[0][1]['ids']=='101'


@pytest.mark.parametrize('mode',['omitted','permission','account','ad_id','campaign','missing_parent','null'])
def test_name_failure_is_unknown_not_deleted_or_false_unassigned(mode):
    s=settings();r=history();item=metadata()
    if mode=='account': item['account_id']='999'
    if mode=='ad_id': item['id']='999'
    if mode=='campaign': item['campaign']['id']='999'
    if mode=='missing_parent': item.pop('adset')
    def get(*_):
        if mode=='permission': raise AppError('拒絕')
        if mode=='omitted': return {}
        if mode=='null': return {'101':None}
        return {'101':item}
    refresh_names(get,s['accounts'][0],[r])
    assert r['names_verified'] is False
    assert r['current_status']==('PAUSED' if mode=='missing_parent' else 'UNKNOWN')
    assert r['spend_raw']=='92166'
    result=scan(s,lambda *_:{'rows':[r],'currency':'TWD'},'2026-11-01','2026-11-10')
    assert not result['pending'] and len(result['unverified'])==1
    costs=collect_spend(s['projects'],{'m':s['accounts'][0]},lambda *_:{'rows':[r],'currency':'TWD'},date(2026,11,22))
    if mode=='missing_parent':
        assert costs['p']['spend_raw']=='92166'
    else:
        assert 'error' in costs['p'] and 'spend' not in costs['p']


def test_deleted_status_is_only_shown_when_returned_by_meta_and_cost_remains():
    s=settings();r=history();data=metadata();data['effective_status']='DELETED'
    refresh_names(lambda *_:{'101':data},s['accounts'][0],[r])
    assert r['names_verified'] and r['current_status']=='DELETED' and r['spend_raw']=='92166'


def test_batch_lookup_deduplicates_ids_and_bounds_request_size():
    s=settings();rows=[{**history(),'ad_id':str(i)} for i in range(1,102)]
    rows.append(dict(rows[0]));calls=[]
    def get(path,params):
        ids=params['ids'].split(',');calls.append(ids)
        return {key:metadata(key) for key in ids}
    refresh_names(get,s['accounts'][0],rows)
    assert len(calls)==3 and max(map(len,calls))<=50
    assert sum(map(len,calls))==101 and all(r['names_verified'] for r in rows)


def test_scalar_fallback_recovers_names_without_expanded_parents():
    s=settings(); r=history(); calls=[]
    def get(path, params):
        calls.append(params)
        if 'campaign{' in params['fields']:
            raise AppError('展開查詢失敗')
        if 'campaign_id' in params['fields']:
            return {'101': {'id':'101', 'account_id':'123', 'name':'林口開幕｜素材B',
                            'campaign_id':'1', 'adset_id':'2'}}
        return {'1':{'id':'1','account_id':'123','name':'林口開幕活動'},
                '2':{'id':'2','account_id':'123','name':'林口新客'}}
    refresh_names(get,s['accounts'][0],[r])
    assert r['names_verified'] and r['spend_raw']=='92166' and len(calls)==3


def test_unrelated_missing_field_does_not_block_plan_but_ambiguous_one_does():
    from mori.project_matching import verified_match
    s=settings(); r=history()
    r.update(names_verified=False, verified_name_fields=['ad_name'], ad_name='其他專案')
    plan=s['projects'][0]
    assert verified_match(plan,r) is False
    result=collect_spend([plan],{'m':s['accounts'][0]},lambda *_:{'rows':[r],'currency':'TWD'},date(2026,11,22))
    assert result['p']['spend_raw']=='0'
    combined={**plan,'match_conditions':[{'field':'ad_name','text':'林口開幕'},
                                       {'field':'campaign_name','text':'轉換'}]}
    assert verified_match(combined,r) is False
    assert verified_match({**combined,'match_mode':'any'},r) is None
    r['ad_name']='林口開幕'
    assert verified_match(combined,r) is None
    assert verified_match({**combined,'match_mode':'any'},r) is True
    r['name_lookup_issue']='尚未取得最新名稱：廣告活動'
    result=collect_spend([combined],{'m':s['accounts'][0]},lambda *_:{'rows':[r],'currency':'TWD'},date(2026,11,22))
    assert 'ID 101' in result['p']['error'] and '廣告活動' in result['p']['error']


def test_explicit_assignment_works_when_names_are_unavailable():
    from mori.project_matching import unit_identity, verified_match
    s=settings();r=history();r['names_verified']=False
    plan={**s['projects'][0], 'assigned_units':[unit_identity(r)]}
    assert verified_match(plan,r) is True
    result=collect_spend([plan],{'m':s['accounts'][0]},lambda *_:{'rows':[r],'currency':'TWD'},date(2026,11,22))
    assert result['p']['spend_raw']=='92166'
