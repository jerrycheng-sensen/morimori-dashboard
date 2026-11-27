"""Booking provenance, allocation accounting and deterministic source discovery.

No best-count selection, duplicate event sum or inferred customer identity.
"""
from collections import defaultdict
from datetime import date,timedelta
from decimal import Decimal
import re
from mori.core import AppError
from mori.project_types import canonical_name

META_SCENARIO={'曝光':Decimal('.20'),'流量':Decimal('.05'),'互動':Decimal('.05'),
               '轉換／新客':Decimal('.25'),'轉換／再行銷':Decimal('.45')}


def amount(v):
    try: n=Decimal(str(v))
    except Exception: raise AppError('模型認列缺少有效數值。') from None
    if not n.is_finite() or n<0: raise AppError('模型認列有缺值或負向調整。')
    return n


def validate_timelines(settings):
    timelines=settings.get('festival_model',{}).get('booking_timelines',{})
    if not isinstance(timelines,dict): raise AppError('歷史訂位事件設定不正確。')
    plans={p['id']:p for p in settings.get('projects',[])}
    for pid,segments in timelines.items():
        if pid not in plans or not isinstance(segments,list) or not 1<=len(segments)<=30: raise AppError('歷史事件須對應有效平台計畫。')
        account=next((a for a in settings.get('accounts',[]) if a['key']==plans[pid].get('account_key')),None)
        if account and account['platform']!='google': raise AppError('Meta 模型統一使用購買事件，不設定分段替代事件。')
        last=None
        for segment in sorted(segments,key=lambda r:r.get('since','')):
            try: start=date.fromisoformat(segment['since']);end=date.fromisoformat(segment['until'])
            except (ValueError,TypeError,KeyError): raise AppError('歷史事件日期不正確。') from None
            if start>end or (last and start<=last): raise AppError('歷史訂位事件期間不可重疊。')
            if not isinstance(segment.get('reason'),str) or not segment['reason'].strip(): raise AppError('歷史事件需記錄核對依據。')
            actions=segment.get('google_action_ids')
            if actions is not None and (not isinstance(actions,list) or len(actions)!=1 or not isinstance(actions[0],str) or not actions[0].isdigit()): raise AppError('每個期間只選一個已核對 Google 訂位事件，避免重複訂位。')
            if actions is None and not isinstance(segment.get('meta_action_type'),str): raise AppError('歷史期間缺少訂位事件。')
            last=end
    return timelines


def model_segments(settings,plan,account,start,end):
    timelines=validate_timelines(settings)
    if plan['id'] not in timelines: return [(account,start,end,False)]
    segments=[];next_day=start
    for rule in sorted(timelines[plan['id']],key=lambda r:r['since']):
        a=max(start,date.fromisoformat(rule['since']));b=min(end,date.fromisoformat(rule['until']))
        if a>b: continue
        if a!=next_day: raise AppError('歷史訂位事件走期有缺口，暫不計算整檔 CPA。')
        override=dict(account)
        if account['platform']=='google':
            override['google_action_ids']=rule['google_action_ids'];override['google_conversion_mode']='selected'
        else: override['meta_action_type']=rule['meta_action_type']
        segments.append((override,a,b,True));next_day=b+timedelta(days=1)
    if next_day<=end: raise AppError('歷史訂位事件未覆蓋完整廣告期間。')
    return segments


def bucket(platform,row):
    if platform=='google': return {'SEARCH':'搜尋','PERFORMANCE_MAX':'PMax'}.get(row.get('channel'),'其他／待分類')
    name=row.get('campaign_name','');prefix=re.split(r'[|｜]',name)[0].strip()
    objective=row.get('campaign_objective')
    kind={'OUTCOME_AWARENESS':'曝光','REACH':'曝光','BRAND_AWARENESS':'曝光','OUTCOME_TRAFFIC':'流量','LINK_CLICKS':'流量',
          'OUTCOME_ENGAGEMENT':'互動','POST_ENGAGEMENT':'互動','OUTCOME_SALES':'轉換','CONVERSIONS':'轉換'}.get(objective)
    kind=kind or next((v for v in ('曝光','流量','互動','轉換') if v in prefix),None)
    if kind!='轉換': return kind or '其他／待分類'
    return '轉換／再行銷' if '再行銷' in name else '轉換／新客' if '新客' in name else '轉換／未標新舊客'


def event_audit(report,matched,account,start,end,confirmed=False):
    """Only outcomes for immutable units already attributed to this project."""
    platform=account['platform'];selected=set(account.get('google_action_ids',[])) if platform=='google' else {account.get('meta_action_type','')}
    lookup={(str(r['campaign_id']),str(r.get('asset_group_id') or r.get('ad_id')),r['date']):r for r in matched}
    rows=report.get('event_rows',[]);names={str(e['id']):e.get('name','') for e in report.get('event_catalog',[])}
    sums=defaultdict(lambda:Decimal(0));dates=defaultdict(list);seen=set()
    for r in rows:
        key=(str(r['campaign_id']),str(r['unit_id']),r['date'])
        if key not in lookup: continue
        identity=(*key,r['event_id'])
        if identity in seen: raise AppError('歷史訂位事件明細重複，已停止加總。')
        seen.add(identity);n=amount(r['value']);sums[r['event_id']]+=n
        if n>0: dates[r['event_id']].append(r['date'])
    entries=[{'id':eid,'name':names.get(eid,eid),'selected':eid in selected,'count':str(n),
              'first_date':min(dates[eid],default=None),'last_date':max(dates[eid],default=None)} for eid,n in sorted(sums.items())]
    # All-events metadata is essential for historical Google coverage checks.
    ready=(report.get('events_audited',False) and selected<=set(names) and all(r['event_id'] in names for r in rows)) if platform=='google' else True
    current=sum((amount(r.get('conversion_raw',r.get('conversions'))) for r in matched),Decimal(0))
    alternatives=[e for e in entries if not e['selected'] and amount(e['count'])>0 and any(t in e['name'].casefold() for t in ('booking','預約','訂位','purchase'))]
    selected_dates=[d for eid,ds in dates.items() if eid in selected for d in ds]
    earlier=bool(alternatives and (not selected_dates or min(e['first_date'] for e in alternatives)<min(selected_dates)))
    issue=None
    if platform=='google' and not ready: issue='Google 歷史事件清單未完整核對，暫停整檔 CPA 與預算建議。'
    elif platform=='google' and not confirmed and earlier:
        issue='目前指定事件未覆蓋前段歷史訂位；其他舊訂位事件有回報，須核對歷史切換期間，不自動相加。'
    return {'status':'needs_review' if issue else 'checked','reason':issue,'selected':sorted(selected),'selected_bookings':str(current),
            'since':str(start),'until':str(end),'events':entries,'confirmed_timeline':confirmed}


def automatic_scopes(settings,projects,catalogs):
    """Meta: campaign contains 再行銷 AND the adset belongs to this flight.

    Existing immutable attribution is stronger than a fuzzy project name. Google
    brand candidates must belong to the project and be explicitly brand-named;
    the capacity adapter then verifies every keyword and the targeting region.
    """
    output={};groups={g['id']:g for g in settings.get('project_groups',[])}
    for scope in ['all']+[p['id'] for p in projects]:
        relevant=projects if scope=='all' else [p for p in projects if p['id']==scope]
        found=defaultdict(lambda:defaultdict(set))
        for p in relevant:
            group_name=canonical_name(groups[p['id']]['name'])
            for unit in p.get('source_units',[]):
                key=unit['account_key'];platform=unit['platform'];catalog=catalogs.get(key,{})
                if catalog.get('error'): continue
                for row in catalog.get('rows',[]):
                    if platform=='meta':
                        belongs=str(row['id'])==unit.get('adset_id') or (group_name and group_name in canonical_name(row.get('name','')))
                        if belongs and '再行銷' in row.get('campaign_name',''): found['meta'][key].add(str(row['id']))
                    else:
                        belongs=str(row['id'])==unit.get('campaign_id')
                        name=row.get('name','').casefold()
                        if belongs and row.get('brand_verified') is True: found['google'][key].add(str(row['id']))
        config={}
        for platform in ('meta','google'):
            sources=found[platform]
            if len(sources)==1:
                key=next(iter(sources));config[platform]={'account_key':key,'ids':sorted(sources[key]),'discovery':'automatic'}
        output[scope]=config
    return output


def allocation_summary(projects):
    totals=defaultdict(lambda:{'spend':Decimal(0),'bookings':Decimal(0),'valid':True})
    for p in projects:
        for component in p.get('components',[]):
            t=totals[(component['platform'],component['kind'])]
            t['spend']+=amount(component['spend']);t['bookings']+=amount(component['bookings']);t['valid'] &=component.get('bookings_valid',p.get('bookings_valid',True))
    grand=sum((t['spend'] for t in totals.values()),Decimal(0));platform_total=defaultdict(lambda:Decimal(0))
    for (platform,kind),t in totals.items(): platform_total[platform]+=t['spend']
    out=[]
    for (platform,kind),t in sorted(totals.items()):
        out.append({'platform':platform,'kind':kind,'spend':str(t['spend']),'bookings':str(t['bookings']) if t['valid'] else None,
                    'cpa':str(t['spend']/t['bookings']) if t['valid'] and t['bookings']>0 else None,
                    'total_share':float(t['spend']/grand) if grand else None,
                    'platform_share':float(t['spend']/platform_total[platform]) if platform_total[platform] else None})
    return out


def scenario_weights(projects):
    """Hypothetical Meta internal mix; platform and Google mix learned by spend."""
    rows=allocation_summary(projects);total=sum((amount(r['spend']) for r in rows),Decimal(0))
    meta=sum((amount(r['spend']) for r in rows if r['platform']=='meta'),Decimal(0))
    google=sum((amount(r['spend']) for r in rows if r['platform']=='google'),Decimal(0))
    if not total: return []
    out=[{'platform':'meta','kind':k,'weight':str(meta/total*v),'basis':'假設 Meta 內部比例'} for k,v in META_SCENARIO.items()] if meta else []
    if google:
        for r in rows:
            if r['platform']=='google': out.append({'platform':'google','kind':r['kind'],'weight':str(amount(r['spend'])/total),'basis':'歷史花費比例'})
    return out


def meta_projects(projects):
    """Meta-only denominator/numerator. Never divide combined cost by Meta bookings."""
    output=[]
    for p in projects:
        components=[c for c in p.get('components',[]) if c['platform']=='meta']
        if not components: continue
        daily=defaultdict(lambda:{'spend':Decimal(0),'bookings':Decimal(0)})
        for c in components:
            for r in c['rows']:
                d=daily[r['date']];d['spend']+=amount(r['spend']);d['bookings']+=amount(r['bookings'])
        audits=[a for a in p.get('event_audits',[]) if a['platform']=='meta']
        window=p.get('platform_windows',{}).get('meta',{})
        first=window.get('start',p['ad_start']);last=window.get('end',p['ad_end']);read_through=min(last,p['read_through'])
        dates=[r['date'] for r in p['rows'] if first<=r['date']<=read_through]
        rows=[{'date':d,'spend':str(daily[d]['spend']),'bookings':str(daily[d]['bookings'])} for d in dates]
        spend=sum((amount(c['spend']) for c in components),Decimal(0));bookings=sum((amount(c['bookings']) for c in components),Decimal(0))
        output.append({**p,'spend':str(spend),'bookings':str(bookings),'rows':rows,'components':components,
                       'bookings_valid':all(c.get('bookings_valid',True) for c in components),'analysis_platform':'meta','ad_start':first,'ad_end':last,'read_through':read_through,'duration_days':(date.fromisoformat(last)-date.fromisoformat(first)).days+1})
    return output
