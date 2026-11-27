"""Read-only, source-backed capacity estimates; never require a user-set money ceiling.

Retargeting/brand searches are proxies, not verified repeat customers. Estimated
capacity is conditional on historical delivery frequency, CTR and CPC, not a
promise that every available impression can be profitably bought.
"""
import json
from datetime import date,timedelta
from decimal import Decimal

from mori.core import AppError,TAIPEI
from mori.providers import request_json,google_id


def value(raw):
    try: out=Decimal(str(raw))
    except Exception: raise AppError('量體來源未回傳有效數值。') from None
    if not out.is_finite() or out<0: raise AppError('量體來源有缺值或負向調整，暫不推估。')
    return out


def ids(values):
    if not isinstance(values,list) or not values or len(values)>100 or any(not isinstance(v,str) or not v.isdigit() for v in values):
        raise AppError('請選擇有效的廣告來源 ID。')
    return sorted(set(values))


def validate_config(settings):
    scopes=settings.get('festival_model',{}).get('capacity_scopes',{})
    if not isinstance(scopes,dict) or len(scopes)>100: raise AppError('舊客量體來源設定不正確。')
    accounts={a['key']:a for a in settings.get('accounts',[])}
    for scope,config in scopes.items():
        if not isinstance(scope,str) or not isinstance(config,dict): raise AppError('量體範圍設定不正確。')
        for platform in ('meta','google'):
            source=config.get(platform)
            if not source: continue
            if not isinstance(source,dict) or source.get('account_key') not in accounts or accounts[source['account_key']]['platform']!=platform:
                raise AppError('量體來源帳號不正確。')
            ids(source.get('ids'))
    return scopes


def _pages(provider,path,params):
    rows=[];seen=set();params=dict(params)
    while True:
        result=provider._get(path,params)
        if not isinstance(result.get('data'),list): raise AppError('Meta 量體來源清單不完整。')
        rows.extend(result['data'])
        if not result.get('paging',{}).get('next'): return rows
        cursor=result.get('paging',{}).get('cursors',{}).get('after')
        if not cursor or cursor in seen: raise AppError('Meta 量體清單分頁異常。')
        seen.add(cursor);params['after']=cursor


def source_catalog(provider,account):
    if account['platform']=='meta':
        rows=_pages(provider,'act_'+str(account['account_id']).removeprefix('act_')+'/adsets',
                    {'fields':'id,name,campaign{id,name},targeting','limit':100})
        return [{'id':str(r['id']),'name':r.get('name',''),'campaign_name':r.get('campaign',{}).get('name',''),
                 'has_custom_audience':bool(r.get('targeting',{}).get('custom_audiences'))} for r in rows]
    rows=provider.query(account,"SELECT campaign.id, campaign.name FROM campaign WHERE campaign.advertising_channel_type = 'SEARCH'")
    keywords=provider.query(account,"SELECT campaign.id, ad_group_criterion.keyword.text FROM ad_group_criterion WHERE campaign.advertising_channel_type = 'SEARCH' AND ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = FALSE AND ad_group_criterion.status != 'REMOVED'")
    words={}
    for r in keywords: words.setdefault(str(r['campaign']['id']),set()).add(r['adGroupCriterion']['keyword']['text'])
    return [{'id':str(r['campaign']['id']),'name':r['campaign'].get('name',''),'brand_verified':bool(words.get(str(r['campaign']['id']))) and all(any(t in w.casefold() for t in ('森森','mori')) for w in words[str(r['campaign']['id'])])} for r in rows]


def meta_source(provider,account,selected,start,end):
    selected=ids(selected);specs=[]
    for identifier in selected:
        obj=provider._get(identifier,{'fields':'id,account_id,name,targeting,optimization_goal'})
        if str(obj.get('account_id'))!=str(account['account_id']).removeprefix('act_'):
            raise AppError('Meta 量體來源不屬於此帳號。')
        target=obj.get('targeting',{})
        if not target.get('custom_audiences'):
            raise AppError('選定 Meta 廣告組合沒有自訂再行銷受眾，不能當成舊客量體。')
        if target.get('targeting_automation',{}).get('advantage_audience') in (1,True) or target.get('targeting_optimization') in ('expansion_all','expansion_detail'):
            raise AppError('選定來源允許受眾擴展，不能把全部量體視為再行銷母體。')
        for audience in target['custom_audiences']:
            subtype=provider._get(str(audience['id']),{'fields':'subtype'}).get('subtype')
            if not subtype or subtype=='LOOKALIKE': raise AppError('自訂受眾類型未核對或包含類似受眾，暫不視為舊客母體。')
        specs.append(json.dumps(target,sort_keys=True))
    if len(set(specs))!=1:
        raise AppError('多個 Meta 來源的地區或受眾不同，無法直接去重相加；系統保留已辨識來源，暫不以重複母體加總。')
    estimate=provider._get(selected[0]+'/delivery_estimate',{'fields':'estimate_ready,estimate_mau_lower_bound,estimate_mau_upper_bound'})
    data=estimate.get('data',[])
    if len(data)!=1 or data[0].get('estimate_ready') is not True:
        raise AppError('Meta 尚未提供可用的再行銷母體估計；量體缺值不當成零。')
    lower=value(data[0].get('estimate_mau_lower_bound'));upper=value(data[0].get('estimate_mau_upper_bound'))
    if lower<=0 or upper<lower: raise AppError('Meta 再行銷母體範圍不足，暫不推估預算上限。')
    path='act_'+str(account['account_id']).removeprefix('act_')+'/insights'
    params={'level':'account','fields':'date_start,date_stop,spend,impressions,actions','time_increment':1,
            'filtering':json.dumps([{'field':'adset.id','operator':'IN','value':selected}]),
            'time_range':json.dumps({'since':str(start),'until':str(end)}),'limit':500,
            'action_report_time':'impression','use_unified_attribution_setting':'true'}
    daily=_pages(provider,path,params);bydate={}
    action=account.get('meta_action_type','')
    if not action: raise AppError('Meta 尚未指定訂位事件，無法找出較佳投放頻次。')
    for row in daily:
        key=row['date_start']
        if key in bydate: raise AppError('Meta 量體校準資料重複。')
        bydate[key]=(value(row.get('spend')),value(next((a.get('value') for a in row.get('actions',[]) if a.get('action_type')==action),0)))
    blocks=[];day=start
    while day+timedelta(days=6)<=end:
        stop=day+timedelta(days=6)
        cost=sum((v[0] for k,v in bydate.items() if str(day)<=k<=str(stop)),Decimal(0))
        bookings=sum((v[1] for k,v in bydate.items() if str(day)<=k<=str(stop)),Decimal(0))
        if cost>0 and bookings>0: blocks.append((cost/bookings,day,stop))
        day=stop+timedelta(days=1)
    if not blocks: raise AppError('再行銷來源尚無完整七日且有訂位的校準區間。')
    _,since,until=min(blocks,key=lambda b:b[0])
    whole=provider._get(path,{**params,'time_increment':'all_days','fields':'date_start,date_stop,spend,impressions,reach',
                             'time_range':json.dumps({'since':str(since),'until':str(until)})})
    rows=whole.get('data',[])
    if len(rows)!=1 or whole.get('paging',{}).get('next'): raise AppError('Meta 七日去重觸及資料不完整。')
    raw=rows[0];reach=value(raw.get('reach'));impressions=value(raw.get('impressions'));spend=value(raw.get('spend'))
    if reach<=0 or impressions<=0 or spend<=0: raise AppError('Meta 尚無足夠觸及或花費校準資料。')
    if raw.get('date_start')!=str(since) or raw.get('date_stop')!=str(until): raise AppError('Meta 量體校準期間不一致。')
    currency=provider._get('act_'+str(account['account_id']).removeprefix('act_'),{'fields':'currency'}).get('currency')
    if not isinstance(currency,str) or not currency.strip(): raise AppError('Meta 量體來源未確認帳號幣別。')
    return {'status':'ready','currency':currency,'audience_lower':str(lower),'audience_upper':str(upper),
            'frequency_per_day':str(impressions/reach/7),'cpm':str(spend/impressions*1000),
            'since':str(since),'until':str(until),'ids':selected,'measured_days':7,
            'basis':'目前月活躍再行銷母體 × 歷史較佳七日的每日頻次 × CPM；固定目前母體，不將每月人數相加。'}


def google_source(provider,account,selected,start,end):
    selected=ids(selected);clause=','.join(selected)
    campaigns=provider.query(account,'SELECT campaign.id, campaign.advertising_channel_type FROM campaign WHERE campaign.id IN ('+clause+')')
    if {str(r['campaign']['id']) for r in campaigns}!=set(selected) or any(r['campaign']['advertisingChannelType']!='SEARCH' for r in campaigns):
        raise AppError('Google 舊客量體只使用已確認的搜尋活動。')
    keywords=provider.query(account,"SELECT ad_group_criterion.keyword.text FROM ad_group_criterion WHERE campaign.id IN ("+clause+") AND ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = FALSE AND ad_group_criterion.status != 'REMOVED'")
    words=sorted({r['adGroupCriterion']['keyword']['text'].strip() for r in keywords})
    if not words or any(not any(token in word.casefold() for token in ('森森','mori')) for word in words):
        raise AppError('來源包含非品牌字或缺少品牌關鍵字，不能把整個活動當成品牌搜尋量體。')
    criteria=provider.query(account,"SELECT campaign.id, campaign_criterion.type, campaign_criterion.negative, campaign_criterion.location.geo_target_constant, campaign_criterion.language.language_constant FROM campaign_criterion WHERE campaign.id IN ("+clause+") AND campaign_criterion.type IN ('LOCATION','LANGUAGE')")
    geos=set();languages=set();bycampaign={k:{'geo':set(),'lang':set()} for k in selected}
    for row in criteria:
        c=row['campaignCriterion']
        if c.get('negative'): raise AppError('來源含排除地區，搜尋量體尚無同範圍估計，暫不擴大代算。')
        if c.get('type')=='LOCATION':
            geo=c['location']['geoTargetConstant'];geos.add(geo);bycampaign[str(row['campaign']['id'])]['geo'].add(geo)
        if c.get('type')=='LANGUAGE':
            lang=c['language']['languageConstant'];languages.add(lang);bycampaign[str(row['campaign']['id'])]['lang'].add(lang)
    if len({(tuple(sorted(v['geo'])),tuple(sorted(v['lang']))) for v in bycampaign.values()})!=1:
        raise AppError('品牌搜尋活動的地區／語言不同，暫不混合估計；自動來源地區不同，目前暫不以跨區混合數字代算。')
    if not geos or len(geos)>10 or len(languages)>1: raise AppError('請使用可核對的地區範圍與單一語言品牌搜尋來源。')
    body={'keywords':words,'geoTargetConstants':sorted(geos),'keywordPlanNetwork':'GOOGLE_SEARCH'}
    if languages: body['language']=next(iter(languages))
    result=request_json(provider.session,'POST',provider.root+'/customers/'+google_id(account['account_id'])+':generateKeywordHistoricalMetrics',headers=provider.headers(),json=body)
    rows=result.get('results')
    if not isinstance(rows,list) or not rows: raise AppError('Google 尚未回傳品牌字搜尋量體。')
    seen=set();monthly=Decimal(0);covered=set()
    for row in rows:
        variants={str(row.get('text','')).casefold(),*[str(x).casefold() for x in row.get('closeVariants',[])]}
        if seen & variants: raise AppError('Google 品牌搜尋變體量體重複，暫不相加。')
        seen|=variants;covered|=variants
        monthly+=value(row.get('keywordMetrics',{}).get('avgMonthlySearches'))
    if any(w.casefold() not in covered for w in words): raise AppError('部分品牌字未取得搜尋量體，暫不以部分數字當總量。')
    report=provider.fetch(account,start,end)
    chosen=[r for r in report['rows'] if str(r['campaign_id']) in selected]
    cost=sum((value(r.get('spend_raw',r.get('spend'))) for r in chosen),Decimal(0))
    impressions=sum((value(r.get('impressions')) for r in chosen),Decimal(0));clicks=sum((value(r.get('clicks')) for r in chosen),Decimal(0))
    if monthly<=0 or impressions<=0 or clicks<=0 or cost<=0: raise AppError('品牌搜尋量、點擊或花費不足，暫不推估承接預算。')
    return {'status':'ready','currency':report['currency'],'monthly_searches':str(monthly),'ctr':str(clicks/impressions),'cpc':str(cost/clicks),
            'since':str(start),'until':str(end),'ids':selected,'keywords':words,'geos':sorted(geos),
            'basis':'去重品牌字近十二月平均搜尋量 × 推估天數 ÷ 30.4375 × 歷史 CTR × CPC；假設可參與全部相關搜尋，不等同已確認舊客。'}


def collect_capacity_sources(settings,factory,now,scopes=None):
    scopes=validate_config(settings) if scopes is None else scopes;accounts={a['key']:a for a in settings['accounts']};out={}
    from mori.project_types import festival_groups
    groups={g['id']:g for g in festival_groups(settings)}
    for key,scope in scopes.items():
        plans=[p for p in settings['projects'] if p.get('group_id') in groups and (key=='all' or p.get('group_id')==key)]
        if not plans: continue
        until=min(now.astimezone(TAIPEI).date()-timedelta(days=1),max((date.fromisoformat(p['end']) for p in plans),default=now.date()))
        since=min((date.fromisoformat(p['start']) for p in plans),default=until-timedelta(days=89))
        value_by_platform={}
        for platform in ('meta','google'):
            source=scope.get(platform)
            if not source:
                value_by_platform[platform]={'status':'needs_source','reason':'自動辨識尚未找到'+('再行銷廣告組合' if platform=='meta' else '品牌搜尋活動')+'來源。'}
                continue
            try:
                account=accounts[source['account_key']];provider=factory(account)
                function=meta_source if platform=='meta' else google_source
                value_by_platform[platform]=function(provider,account,source['ids'],since,until)
            except Exception as exc:
                value_by_platform[platform]={'status':'unavailable','reason':str(exc) if isinstance(exc,AppError) else '量體來源格式不完整，暫不推估。'}
        out[key]=value_by_platform
    return out


def capacity_projection(sources,days):
    if not 1<=days<=365: raise AppError('推估天數須為 1～365 天。')
    results={};currencies=set()
    for platform in ('meta','google'):
        source=sources.get(platform,{})
        if source.get('status')!='ready':
            results[platform]={'status':source.get('status','needs_source'),'reason':source.get('reason','自動辨識尚未找到舊客廣告來源。')};continue
        currencies.add(source['currency'])
        if platform=='meta':
            unit=value(source['frequency_per_day'])*days*value(source['cpm'])/1000
            lower=value(source['audience_lower'])*unit;upper=value(source['audience_upper'])*unit
        else:
            lower=upper=value(source['monthly_searches'])*Decimal(days)/Decimal('30.4375')*value(source['ctr'])*value(source['cpc'])
        results[platform]={'status':'estimated','lower':str(lower),'upper':str(upper),'source':source}
    complete=all(results[p]['status']=='estimated' for p in ('meta','google')) and len(currencies)==1
    return {'status':'estimated' if complete else 'incomplete','platforms':results,
            'lower':str(sum((value(results[p]['lower']) for p in ('meta','google')),Decimal(0))) if complete else None,
            'upper':str(sum((value(results[p]['upper']) for p in ('meta','google')),Decimal(0))) if complete else None,
            'currency':next(iter(currencies)) if len(currencies)==1 else None,'days':days}


def collect_catalogs(settings,factory):
    """Catalog failures are independent of performance-model availability."""
    out={}
    for account in settings['accounts']:
        try: out[account['key']]={'rows':source_catalog(factory(account),account)}
        except Exception as exc:
            out[account['key']]={'rows':[],'error':str(exc) if isinstance(exc,AppError) else '來源清單暫時無法讀取。'}
    return out
