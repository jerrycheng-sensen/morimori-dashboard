"""Capacity provenance, deduplication and missing-source behaviour."""
import copy
from datetime import date,datetime
from decimal import Decimal
import pytest
from mori.core import AppError,TAIPEI
from mori.retention_capacity import meta_source,google_source,capacity_projection,collect_capacity_sources

META={'key':'m','platform':'meta','account_id':'123','meta_action_type':'purchase'}
START=date(2026,10,1);END=date(2026,10,7)
class Meta:
    def __init__(self): self.target={'custom_audiences':[{'id':'9'}],'geo_locations':{'countries':['TW']}};self.calls=[]
    def _get(self,path,params):
        self.calls.append((path,params))
        if path=='9': return {'subtype':'WEBSITE'}
        if path=='act_123': return {'currency':'TWD'}
        if path.endswith('/delivery_estimate'): return {'data':[{'estimate_ready':True,'estimate_mau_lower_bound':1000,'estimate_mau_upper_bound':2000}]}
        if path=='act_123/insights':
            if params['time_increment']=='all_days': return {'data':[{'date_start':str(START),'date_stop':str(END),'spend':'700','impressions':'14000','reach':'1000'}]}
            return {'data':[{'date_start':str(START),'spend':'700','actions':[{'action_type':'purchase','value':'14'}]}]}
        return {'account_id':'123','targeting':copy.deepcopy(self.target)}

def test_meta_uses_whole_week_dedup_reach_and_verified_currency():
    p=Meta();source=meta_source(p,META,['1','2'],START,END)
    assert source['frequency_per_day']=='2' and Decimal(source['cpm'])==50
    result=capacity_projection({'meta':source},30)
    assert Decimal(result['platforms']['meta']['upper'])==6000
    assert result['upper'] is None and result['status']=='incomplete'
    assert len([path for path,params in p.calls if path.endswith('/delivery_estimate')])==1
    assert any(path=='act_123' and params=={'fields':'currency'} for path,params in p.calls)

@pytest.mark.parametrize('change',['expansion','no_audience','lookalike','different','unready','currency'])
def test_meta_unsafe_or_unknown_capacity_never_becomes_zero(change):
    p=Meta();original=p._get
    def get(path,params):
        result=original(path,params)
        if change=='expansion' and 'targeting' in result: result['targeting']['targeting_automation']={'advantage_audience':1}
        if change=='no_audience' and 'targeting' in result: result['targeting'].pop('custom_audiences')
        if change=='different' and path=='2': result['targeting']['age_min']=25
        if change=='lookalike' and path=='9': result['subtype']='LOOKALIKE'
        if change=='unready' and path.endswith('/delivery_estimate'): result['data'][0]['estimate_ready']=False
        if change=='currency' and path=='act_123': result={}
        return result
    p._get=get
    with pytest.raises(AppError): meta_source(p,META,['1','2'],START,END)

class Google:
    root='https://googleads.googleapis.com/v23';session=object()
    def __init__(self): self.words=['森森燒肉','森森'];self.geo='geoTargetConstants/2158'
    def headers(self): return {'Authorization':'fake'}
    def query(self,a,sql):
        if 'FROM ad_group_criterion' in sql: return [{'adGroupCriterion':{'keyword':{'text':w}}} for w in self.words]
        if 'FROM campaign_criterion' in sql: return [{'campaign':{'id':'1'},'campaignCriterion':{'type':'LOCATION','location':{'geoTargetConstant':self.geo}}}]
        return [{'campaign':{'id':'1','advertisingChannelType':'SEARCH'}}]
    def fetch(self,a,start,end): return {'currency':'TWD','rows':[{'campaign_id':'1','spend_raw':'300.123456','impressions':1000,'clicks':100}]}

def test_brand_close_variants_count_once_and_preserve_raw_cost(monkeypatch):
    import mori.retention_capacity as mod
    def request(session,method,url,**kw):
        assert method=='POST' and url.endswith(':generateKeywordHistoricalMetrics')
        assert kw['json']['geoTargetConstants']==['geoTargetConstants/2158']
        return {'results':[{'text':'森森燒肉','closeVariants':['森森'],'keywordMetrics':{'avgMonthlySearches':'1000'}}]}
    monkeypatch.setattr(mod,'request_json',request)
    s=google_source(Google(),{'account_id':'123'},['1'],START,END)
    assert s['monthly_searches']=='1000' and Decimal(s['cpc'])==Decimal('3.00123456')
    m=meta_source(Meta(),META,['1'],START,END)
    result=capacity_projection({'meta':m,'google':s},30)
    expected=Decimal(6000)+Decimal(1000)*30/Decimal('30.4375')*Decimal('.1')*Decimal('3.00123456')
    assert abs(Decimal(result['upper'])-expected)<Decimal('.00000001')
    assert Decimal(capacity_projection({'meta':m,'google':s},60)['upper'])==Decimal(result['upper'])*2

@pytest.mark.parametrize('issue',['generic','no_geo','missing_word','duplicate'])
def test_brand_uncertain_scope_does_not_produce_partial_total(monkeypatch,issue):
    import mori.retention_capacity as mod
    p=Google()
    if issue=='generic': p.words=['燒肉推薦']
    if issue=='no_geo':
        query=p.query;p.query=lambda a,sql:[] if 'FROM campaign_criterion' in sql else query(a,sql)
    rows=[{'text':'森森燒肉','keywordMetrics':{'avgMonthlySearches':'100'}}]
    if issue=='duplicate': rows*=2
    monkeypatch.setattr(mod,'request_json',lambda *a,**kw:{'results':rows})
    with pytest.raises(AppError): google_source(p,{'account_id':'123'},['1'],START,END)

def test_source_failure_does_not_invent_zero_and_only_festival_calibrates():
    from test_festival_model import settings
    s=settings();s['accounts'].append(META)
    s['projects'].append({'id':'special','group_id':'special','start':'2020-01-01','end':'2027-01-01'})
    s['festival_model']={'capacity_scopes':{'all':{'meta':{'account_key':'m','ids':['1']}}}}
    calls=[]
    def factory(account): calls.append(account['key']);raise AppError('來源暫時無法讀取')
    result=collect_capacity_sources(s,factory,datetime(2026,11,27,tzinfo=TAIPEI))
    assert result['all']['meta']['status']=='unavailable' and 'upper' not in result['all']['meta']
    assert result['all']['google']['status']=='needs_source' and calls==['m']
