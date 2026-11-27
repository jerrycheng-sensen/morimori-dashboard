import copy
from datetime import date
from decimal import Decimal
import pytest
from mori.core import AppError
from mori.festival_integrity import (event_audit,automatic_scopes,allocation_summary,scenario_weights,
                                     meta_projects,model_segments,validate_timelines)
from mori.festival_model import allocation_projection,build_models,hill


def test_historical_google_gap_not_zero_and_never_auto_sums_booking_events():
    matched=[{'campaign_id':'1','ad_id':'10','date':'2026-06-01','conversions':'0'}]
    report={'events_audited':True,'event_catalog':[{'id':'new','name':'morimori_booking_once_ready'},{'id':'old','name':'booking_success'}],
            'event_rows':[{'campaign_id':'1','unit_id':'10','date':'2026-06-01','event_id':'old','value':'2500'}]}
    audit=event_audit(report,matched,{'platform':'google','google_action_ids':['new']},date(2026,6,1),date(2026,6,30))
    assert audit['status']=='needs_review' and audit['selected_bookings']=='0'
    assert audit['events'][0]['count']=='2500'  # audit only, not assigned bookings
    report['event_rows']*=2
    with pytest.raises(AppError,match='重複'): event_audit(report,matched,{'platform':'google','google_action_ids':['new']},date(2026,6,1),date(2026,6,30))


def test_meta_numerator_and_denominator_exclude_google_even_when_google_review_pending():
    p={'id':'one','name':'足球祭','ad_start':'2026-05-29','ad_end':'2026-07-19','read_through':'2026-07-19',
       'spend':'182520.464724','bookings':'1250','bookings_valid':False,
       'rows':[{'date':'2026-06-01','spend':'182520.464724','bookings':'1250'}],
       'components':[{'platform':'meta','kind':'轉換／再行銷','spend':'55589','bookings':'1250','bookings_valid':True,
                      'rows':[{'date':'2026-06-01','spend':'55589','bookings':'1250'}]},
                     {'platform':'google','kind':'搜尋','spend':'126931.464724','bookings':'0','bookings_valid':False,'rows':[]}]}
    meta=meta_projects([p])[0]
    assert meta['spend']=='55589' and meta['bookings']=='1250' and meta['bookings_valid']
    assert Decimal(meta['spend'])/Decimal(meta['bookings'])==Decimal('44.4712')
    rows=allocation_summary([p])
    assert next(r for r in rows if r['platform']=='meta')['bookings']=='1250'
    assert next(r for r in rows if r['platform']=='google')['bookings'] is None
    assert p['spend']=='182520.464724'  # never mutate actual cross-platform ledger


def test_automatic_meta_uses_campaign_and_project_adset_identity_not_all_retargeting():
    settings={'project_groups':[{'id':'a','name':'感謝祭第5彈'}]}
    projects=[{'id':'a','source_units':[{'account_key':'m','platform':'meta','campaign_id':'1','adset_id':'11'},
                                      {'account_key':'g','platform':'google','campaign_id':'21','adset_id':''}]}]
    catalogs={'m':{'rows':[{'id':'11','name':'感謝祭第5彈','campaign_name':'轉換｜再行銷'},
                          {'id':'12','name':'桃竹加碼','campaign_name':'轉換｜再行銷'},
                          {'id':'13','name':'感謝祭第5彈','campaign_name':'流量｜新客'}]},
              'g':{'rows':[{'id':'21','name':'品牌搜尋','brand_verified':True},
                          {'id':'22','name':'品牌搜尋','brand_verified':True}]}}
    result=automatic_scopes(settings,projects,catalogs)
    assert result['a']['meta']['ids']==['11'] and result['all']['meta']['ids']==['11']
    assert result['a']['google']['ids']==['21']


def test_scenario_uses_assumed_meta_mix_and_weighted_google_cost_mix_not_average_cpa():
    p={'components':[{'platform':'meta','kind':'曝光','spend':'100','bookings':'2'},
                     {'platform':'meta','kind':'轉換／新客','spend':'200','bookings':'20'},
                     {'platform':'google','kind':'搜尋','spend':'100','bookings':'20'},
                     {'platform':'google','kind':'PMax','spend':'500','bookings':'10'}]}
    weights=scenario_weights([p]);lookup={(r['platform'],r['kind']):Decimal(r['weight']) for r in weights}
    assert sum(lookup.values())==pytest.approx(Decimal(1))
    assert lookup[('meta','曝光')]==Decimal(300)/900*Decimal('.2')
    assert lookup[('google','搜尋')]==Decimal(100)/900
    # Correct aggregate CPA would be 900 / 52, not the mean of component CPA.
    sums=allocation_summary([p]);assert sum(Decimal(r['spend']) for r in sums)==900


def test_date_timeline_requires_no_gaps_overlaps_or_multiple_event_sum():
    plan={'id':'p','start':'2026-10-01','end':'2026-10-04'};a={'platform':'google','google_action_ids':['3']}
    s={'projects':[plan],'festival_model':{'booking_timelines':{'p':[
      {'since':'2026-10-01','until':'2026-10-02','google_action_ids':['1'],'reason':'已核對'},
      {'since':'2026-10-03','until':'2026-10-04','google_action_ids':['2'],'reason':'換事件'}]}}}
    result=model_segments(s,plan,a,date(2026,10,1),date(2026,10,4))
    assert [r[0]['google_action_ids'] for r in result]==[['1'],['2']] and a['google_action_ids']==['3']
    s['festival_model']['booking_timelines']['p'][1]['since']='2026-10-04'
    with pytest.raises(AppError,match='缺口'): model_segments(s,plan,a,date(2026,10,1),date(2026,10,4))
    s['festival_model']['booking_timelines']['p'][0]['google_action_ids']=['1','2']
    with pytest.raises(AppError): validate_timelines(s)


def test_invalid_historical_bookings_cannot_leak_into_fallback_or_fit():
    p={'id':'1','name':'待核對','bookings_valid':False,'rows':[{'date':'2026-06-01','spend':'100','bookings':'10'}]}
    assert build_models([p],date(2026,7,1))['individual']['1']['status']=='needs_review'
    assert allocation_projection([p],date(2026,7,1),30)['candidate'] is None


def test_allocation_curve_derivative_is_not_average_cpa_and_respects_support():
    from datetime import timedelta
    from mori.festival_integrity import META_SCENARIO
    parts=[]
    for kind,weight in META_SCENARIO.items():
        rows=[]
        for i in range(64):
            total=100+(i*17%63)*20
            spend=total*float(weight)
            rows.append({'date':str(date(2026,6,1)+timedelta(days=i)),'spend':str(spend),
                         'bookings':str(100*float(weight)*hill(total,400,2))})
        parts.append({'platform':'meta','kind':kind,'spend':str(sum(Decimal(r['spend']) for r in rows)),
                      'bookings':str(sum(Decimal(r['bookings']) for r in rows)),'rows':rows})
    p={'id':'a','name':'測試','rows':parts[0]['rows'],'components':parts,'bookings_valid':True}
    result=allocation_projection([p],date(2026,9,1),30)
    assert result['curve'] and result['candidate']
    assert result['curve'][-1]['marginal_cpa']>result['curve'][-1]['cpa']
    assert all(3000<=r['budget']<=40200 for r in result['curve'])
    p['components'].pop()
    assert allocation_projection([p],date(2026,9,1),30)['candidate'] is None


def test_google_failure_does_not_stop_meta_snapshot_or_mix_cost():
    from datetime import datetime
    from mori.core import TAIPEI
    from mori.festival_model import refresh_snapshot
    from test_festival_model import settings,Store,BASELINE_NAMES
    s=settings();s['accounts'].append({'key':'m','name':'Meta','platform':'meta','account_id':'123','meta_action_type':'purchase'})
    for i,p in enumerate(copy.deepcopy(s['projects'])):
        p.update(id='meta'+str(i),account_key='m');s['projects'].append(p)
    class Meta:
        def fetch_model(self,a,start,end):
            rows=[{'campaign_id':str(i+1),'ad_id':str(i+10),'adset_id':str(i+20),'campaign_name':name,
                   'date':'2026-11-18','spend':'55589','conversion_raw':'1250','names_verified':True} for i,name in enumerate(BASELINE_NAMES)]
            return {'currency':'TWD','attribution_detail':True,'rows':rows,'whole_rows':rows}
    class Bad:
        def fetch_model(self,*a): raise AppError('Google 暫時無法讀取')
    out=refresh_snapshot(Store(),s,lambda a:Meta() if a['platform']=='meta' else Bad(),datetime(2026,11,28,tzinfo=TAIPEI))
    assert out['last_error'] is None and out['source_warnings']
    assert len(out['model_projects'])==2
    assert all(p['spend']=='55589' and p['bookings']=='1250' for p in out['model_projects'])
