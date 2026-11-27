"""All-festival advertising response models and private snapshots.

A small, explicitly observational Hill response fit; not Meridian, causal lift,
operating ROI, or a proof that spend caused bookings. No operational data used.
"""
import hashlib
import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal

from mori.core import AppError, TAIPEI
from mori.project_types import festival_groups
from mori.project_matching import verified_match, unit_identity
from mori.festival_integrity import event_audit,bucket,model_segments,automatic_scopes,meta_projects

SNAPSHOT_PATH = 'festival-model.json'
VERSION = 3


def source_signature(settings):
    groups = festival_groups(settings)
    ids = {g['id'] for g in groups}
    plans = [p for p in settings['projects'] if p.get('group_id') in ids]
    keys = {p['account_key'] for p in plans}
    for scope in settings.get('festival_model',{}).get('capacity_scopes',{}).values():
        keys.update(v['account_key'] for v in scope.values() if isinstance(v,dict) and v.get('account_key'))
    value = [VERSION,[{k:v for k,v in g.items() if k!='status'} for g in groups],[{k:v for k,v in p.items() if k!='status'} for p in plans],[a for a in settings['accounts'] if a['key'] in keys],settings.get('budget_transactions',[]),settings.get('festival_model',{}).get('capacity_scopes',{}),settings.get('festival_model',{}).get('booking_timelines',{})]
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def numeric(value):
    try:
        result = Decimal(str(value))
    except Exception:
        raise AppError('檔期資料缺少有效數值。') from None
    if not result.is_finite() or result < 0:
        raise AppError('檔期資料有缺值或負向調整，暫不建立模型。')
    return result


def collect_projects(settings, factory, now, platforms=None, reports=None):
    """Read complete ad windows regardless of project/plan management status."""
    from mori.budget_ledger import balance
    through = now.astimezone(TAIPEI).date()
    accounts = {a['key']:a for a in settings['accounts']}
    output, cache, ownership = [], reports if reports is not None else {}, {}
    for group in festival_groups(settings):
        plans = [p for p in settings['projects'] if p.get('group_id')==group['id'] and (platforms is None or accounts[p['account_key']]['platform'] in platforms)]
        if not plans: continue
        days, currencies = {}, set()
        planned_start = min(date.fromisoformat(p['start']) for p in plans)
        planned_end = max(date.fromisoformat(p['end']) for p in plans)
        authoritative, daily_cost, budget = Decimal(0),Decimal(0),Decimal(0)
        plan_audit = [];components={};source_units={};integrity=[]
        segments=[]
        for base in plans:
            account=accounts[base['account_key']]
            budget += Decimal(str(balance(settings,base['id'],through)['adjusted']))
            start,end=date.fromisoformat(base['start']),min(through,date.fromisoformat(base['end']))
            if start<=end:
                for source,a,b,confirmed in model_segments(settings,base,account,start,end):
                    segments.append(({**base,'start':str(a),'end':str(b)},source,confirmed))
        for plan,account,confirmed in segments:
            start,end = date.fromisoformat(plan['start']),min(through,date.fromisoformat(plan['end']))
            if start>end: continue
            cache_key=(account['key'],str(start),str(end),str(account.get('google_action_ids')),account.get('meta_action_type'))
            if cache_key not in cache:
                cache[cache_key]=factory(account).fetch_model(account,start,end)
            report=cache[cache_key]
            if not report.get('attribution_detail'):
                raise AppError('模型缺少廣告／素材群組認列明細。')
            currencies.add(report['currency'])
            matched=[]
            for row in report['rows']:
                if not str(start)<=str(row['date'])<=str(end): continue
                match=verified_match(plan,row)
                cost=numeric(row.get('spend_raw',row.get('spend')))
                bookings=numeric(row.get('conversion_raw',row.get('conversions')))
                if match is None and (cost or bookings):
                    raise AppError('部分廣告名稱尚未核對，整檔模型暫不加總。')
                if match is not True: continue
                identity=unit_identity(row)
                if not identity: raise AppError('模型明細缺少穩定廣告 ID。')
                unit_key=(account['key'],str(row['date']),identity['kind'],identity['id'])
                if unit_key in ownership:
                    raise AppError('檔期或平台計畫認列重疊，暫不建立模型，請先核對專案條件。')
                ownership[unit_key]=group['id']
                item=days.setdefault(str(row['date']),{'spend':Decimal(0),'bookings':Decimal(0)})
                item['spend']+=cost;item['bookings']+=bookings
                matched.append(row)
                kind=bucket(account['platform'],row);ck=(account['platform'],kind)
                component=components.setdefault(ck,{'platform':ck[0],'kind':kind,'spend':Decimal(0),'bookings':Decimal(0),'days':{}})
                component['spend']+=cost;component['bookings']+=bookings
                daily_component=component['days'].setdefault(str(row['date']),{'spend':Decimal(0),'bookings':Decimal(0)})
                daily_component['spend']+=cost;daily_component['bookings']+=bookings
                source={k:str(row.get(k) or '') for k in ('campaign_id','campaign_name','adset_id','adset_name')}
                source.update(platform=account['platform'],account_key=account['key'])
                source_units[(account['key'],source['campaign_id'],source['adset_id'])]=source
            plan_daily=sum((numeric(r.get('spend_raw',r['spend'])) for r in matched),Decimal(0))
            plan_authoritative=plan_daily
            if account['platform']=='meta':
                if 'whole_rows' not in report:
                    raise AppError('缺少 Meta 整段花費，模型暫不加總。')
                plan_authoritative=Decimal(0)
                for row in report.get('whole_rows',[]):
                    state=verified_match(plan,row)
                    if state is None and numeric(row.get('spend_raw',row['spend'])):
                        raise AppError('Meta 整段花費的名稱尚未完整核對。')
                    if state is True:
                        plan_authoritative+=numeric(row.get('spend_raw',row['spend']))
            audit=event_audit(report,matched,account,start,end,confirmed)
            for ck in {(account['platform'],bucket(account['platform'],r)) for r in matched}:
                components[ck]['bookings_valid']=components[ck].get('bookings_valid',True) and audit['status']=='checked'
            if account['platform']=='meta':
                for r in matched: components[('meta',bucket('meta',r))]['spend']-=numeric(r.get('spend_raw',r['spend']))
                for r in report['whole_rows']:
                    if verified_match(plan,r) is True:
                        ck=('meta',bucket('meta',r))
                        component=components.setdefault(ck,{'platform':'meta','kind':ck[1],'spend':Decimal(0),'bookings':Decimal(0),'days':{},'bookings_valid':audit['status']=='checked'})
                        component['spend']+=numeric(r.get('spend_raw',r['spend']))
            integrity.append({'plan_id':plan['id'],'platform':account['platform'],'account_key':account['key'],**audit})
            daily_cost+=plan_daily;authoritative+=plan_authoritative
            plan_audit.append({'plan_id':plan['id'],'platform':account['platform'],'since':str(start),'until':str(end),
                               'daily_cost':str(plan_daily),'whole_cost':str(plan_authoritative),
                               'difference':str(plan_daily-plan_authoritative),'bookings':str(sum((numeric(r.get('conversion_raw',r.get('conversions'))) for r in matched),Decimal(0))),'event_status':audit['status'],'event':account.get('meta_action_type') if account['platform']=='meta' else account.get('google_action_ids',[])})
        if not currencies and planned_start>through: continue
        if len(currencies)!=1: raise AppError('同檔期的帳號幣別須一致且完整。')
        first,last = planned_start,min(planned_end,through)
        if first>last: raise AppError('檔期尚無可讀取的廣告日期。')
        rows=[]
        current=first
        while current<=last:
            value=days.get(str(current),{'spend':Decimal(0),'bookings':Decimal(0)})
            rows.append({'date':str(current),'spend':str(value['spend']),'bookings':str(value['bookings'])})
            current+=timedelta(days=1)
        output.append({'id':group['id'],'name':group['name'],'currency':next(iter(currencies)),
                       'ad_start':str(planned_start),'ad_end':str(planned_end),
                       'read_through':str(last),'duration_days':(planned_end-planned_start).days+1,
                       'budget':str(budget),'spend':str(authoritative),'daily_spend':str(daily_cost),
                       'cost_difference':str(daily_cost-authoritative),
                       'bookings':str(sum((numeric(r['bookings']) for r in rows),Decimal(0))),
                       'last_paid_date':max((r['date'] for r in rows if numeric(r['spend'])>0),default=None),
                       'platform_windows':{platform:{'start':min(p['start'] for p in plans if accounts[p['account_key']]['platform']==platform),'end':max(p['end'] for p in plans if accounts[p['account_key']]['platform']==platform)} for platform in {accounts[p['account_key']]['platform'] for p in plans}},
                       'rows':rows,'audit':plan_audit,'event_audits':integrity,'bookings_valid':all(a['status']=='checked' for a in integrity),
                       'source_units':list(source_units.values()),
                       'components':[{**{k:v for k,v in c.items() if k not in ('days','spend','bookings')},'spend':str(c['spend']),'bookings':str(c['bookings']),
                           'rows':[{'date':day,'spend':str(v['spend']),'bookings':str(v['bookings'])} for day,v in sorted(c['days'].items())]} for c in components.values()]})
    if len({p['currency'] for p in output})!=1:
        raise AppError('檔期幣別不同或尚無已開始的廣告資料，不能合併訓練。')
    return output


def hill(x,k,s):
    return 0. if x<=0 else 1./(1.+(k/x)**s)


def _fit(series):
    """Shared saturation shape, separate campaign response scales."""
    positive=[x for rows in series.values() for x,y in rows if x>0]
    lo,hi=min(positive),max(positive)
    best=None
    for i in range(35):
        k=math.exp(math.log(lo*.2)+i/34*(math.log(hi*2)-math.log(lo*.2)))
        for slope in (.5,.75,1.,1.25,1.5,2.,2.5,3.,4.):
            amplitudes={};loss=0.
            for gid,rows in series.items():
                f=[hill(x,k,slope) for x,y in rows]
                denom=sum(v*v for v in f)
                a=sum(v*y for v,(x,y) in zip(f,rows))/denom if denom else 0.
                amplitudes[gid]=a
                loss+=sum((y-a*v)**2 for v,(x,y) in zip(f,rows))/max(sum(y*y for x,y in rows),1.)
            if best is None or loss<best['loss']:
                best={'k':k,'slope':slope,'amplitudes':amplitudes,'loss':loss}
    return best


def fit_projects(projects, through):
    series={}
    for p in projects:
        if p.get('bookings_valid') is False: return {'status':'needs_review','reason':'歷史訂位事件尚未覆蓋完整走期，暫停 CPA、邊際 CPA 與預算建議；保留花費與逐事件核對。'}
        rows=[(float(numeric(r['spend'])),float(numeric(r['bookings']))) for r in p['rows'] if r['date']<=str(through)]
        active=[x for x,y in rows if x>0]
        if len(rows)<28 or len(active)<21 or len(set(active))<8 or sum(y for x,y in rows)<30:
            return {'status':'insufficient','reason':'每檔至少需 28 個成熟資料日、21 個有花費日、8 種日花費及 30 次訂位；門檻是操作護欄，不是統計證明。'}
        series[p['id']]=rows
    if not series: return {'status':'insufficient','reason':'至少需一檔可用資料。'}
    training={gid:rows[:max(1,int(len(rows)*.75))] for gid,rows in series.items()}
    if any(not any(x>0 for x,y in rows) for rows in training.values()):
        return {'status':'unreliable','reason':'訓練期間缺少有效花費變化，暫不推估。'}
    trial=_fit(training)
    checks=[]
    for gid,rows in series.items():
        holdout=rows[len(training[gid]):]
        actual=[y for x,y in holdout]
        predicted=[trial['amplitudes'][gid]*hill(x,trial['k'],trial['slope']) for x,y in holdout]
        nrmse=math.sqrt(sum((a-b)**2 for a,b in zip(actual,predicted))/len(actual))/max(sum(actual)/len(actual),1.)
        checks.append({'id':gid,'holdout_days':len(actual),'normalized_rmse':nrmse})
    if any(c['normalized_rmse']>.5 for c in checks):
        return {'status':'unreliable','reason':'最後 25% 日期的回測誤差過高，暫不顯示預算建議。','checks':checks}
    fitted=_fit(series)
    fitted.update(status='estimated',checks=checks,
                  ranges={gid:[min(x for x,y in rows if x>0),max(x for x,y in rows)] for gid,rows in series.items()},
                  reason='檔期反應形狀、各檔各自規模的廣告歸因反應曲線；未控制競價、素材、星期、受眾及延遲效應，不是因果或營運 ROI 模型。')
    return fitted


def projection(fit, project_id, duration_days, target_cpa=0):
    if fit.get('status')!='estimated': return {'sweet':None,'upper':None,'curve':[]}
    k,s,a=fit['k'],fit['slope'],fit['amplitudes'][project_id]
    low,high=fit['ranges'][project_id]
    points=[]
    for i in range(121):
        x=low+(high-low)*i/120
        h=hill(x,k,s);y=a*h
        derivative=a*s*h*(1-h)/x if x>0 else 0.
        points.append({'budget':x*duration_days,'bookings':y*duration_days,
                       'cpa':x/y if y>0 else None,'marginal_cpa':1/derivative if derivative>0 else None})
    # An interior minimum only exists for slope > 1. Never invent an optimum at zero.
    x_star=k*(s-1)**(1/s) if s>1 else None
    sweet=None
    if x_star and low<x_star<high:
        y=a*hill(x_star,k,s)
        sweet={'budget':x_star*duration_days,'bookings':y*duration_days,'cpa':x_star/y}
    inflection=k*((s-1)/(s+1))**(1/s) if s>1 else 0.
    upper=None
    if target_cpa>0:
        for old,new in zip(points,points[1:]):
            daily=old['budget']/duration_days
            if daily>=inflection and old['marginal_cpa'] is not None and new['marginal_cpa'] is not None and old['marginal_cpa']<=target_cpa<new['marginal_cpa'] and old['cpa']<=target_cpa:
                upper=old
                break
    return {'sweet':sweet,'upper':upper,'curve':points}



def observed_candidate(project, duration_days):
    """Best observed seven-day block, explicitly not an identified global optimum."""
    if project.get('bookings_valid') is False: return None
    rows=sorted(project.get('rows',[]),key=lambda r:r['date'])
    blocks=[]
    for i in range(0,len(rows),7):
        block=rows[i:i+7]
        cost=sum((numeric(r['spend']) for r in block),Decimal(0))
        bookings=sum((numeric(r['bookings']) for r in block),Decimal(0))
        if cost>0 and bookings>0:
            blocks.append({'budget':float(cost/len(block)*duration_days),'cpa':float(cost/bookings),
                           'bookings':float(bookings/len(block)*duration_days),'since':block[0]['date'],
                           'until':block[-1]['date'],'days':len(block),'basis':'historical_observation'})
    complete=[b for b in blocks if b['days']==7]
    return min(complete or blocks,key=lambda b:b['cpa'],default=None)


def current_projection(fit, project, duration_days):
    result=projection(fit,project['id'],duration_days)
    if result['sweet']:
        result.update(candidate={**result['sweet'],'basis':'model_interior'},diagnosis='曲線出現內部最低點；仍屬觀察模型估計。')
    elif result['curve']:
        points=[p for p in result['curve'] if p['cpa'] is not None]
        candidate=min(points,key=lambda p:p['cpa'],default=None)
        result.update(candidate={**candidate,'basis':'model_boundary'} if candidate else None,
                      diagnosis='目前最低 CPA 位於已觀察投入範圍的邊界。可查看當下較佳投入，但尚未證明真正最低點。')
    else:
        result.update(candidate=observed_candidate(project,duration_days),
                      diagnosis=fit.get('reason','資料仍在累積。')+' 先呈現目前較佳的歷史觀察區間，不冒充已驗證甜蜜點。')
    return result


def build_models(projects, through):
    """Independent flight models and an equal-flight, intensity-normalized pool."""
    import statistics
    individual={p['id']:fit_projects([p],through) for p in projects}
    eligible=[p for p in projects if individual[p['id']].get('status')=='estimated']
    diagnostics=[{'id':p['id'],'name':p['name'],'status':individual[p['id']]['status'],
                  'reason':individual[p['id']].get('reason','')} for p in projects]
    if not eligible:
        aggregate={'status':'insufficient','reason':'目前尚無通過樣本與回測檢查的檔期；仍顯示各檔歷史資料與當下觀察。'}
    else:
        series={};scales={}
        for p in eligible:
            rows=[(float(numeric(r['spend'])),float(numeric(r['bookings']))) for r in p['rows'] if r['date']<=str(through)]
            xscale=statistics.mean(x for x,y in rows if x>0)
            yscale=statistics.mean(y for x,y in rows)
            scales[p['id']]=(xscale,yscale)
            series[p['id']]=[(x/xscale,y/yscale) for x,y in rows]
        training={gid:rows[:int(len(rows)*.75)] for gid,rows in series.items()}
        trial=_fit(training);checks=[]
        for gid,rows in series.items():
            hold=rows[len(training[gid]):]
            rmse=math.sqrt(sum((y-trial['amplitudes'][gid]*hill(x,trial['k'],trial['slope']))**2 for x,y in hold)/len(hold))
            checks.append({'id':gid,'holdout_days':len(hold),'normalized_rmse':rmse/max(statistics.mean(y for x,y in hold),1e-9)})
        if any(c['normalized_rmse']>.5 for c in checks):
            aggregate={'status':'unreliable','reason':'集合模型的跨檔回測誤差過高；個別檔期與實際觀察仍可查看。','checks':checks}
        else:
            fitted=_fit(series)
            dx=statistics.median(s[0] for s in scales.values());dy=statistics.median(s[1] for s in scales.values())
            aggregate={'status':'estimated','k':fitted['k']*dx,'slope':fitted['slope'],
                       'amplitudes':{'all':statistics.median(fitted['amplitudes'].values())*dy},
                       'ranges':{'all':[statistics.median(min(x for x,y in rows if x>0) for rows in series.values())*dx,
                                        statistics.median(max(x for x,y in rows) for rows in series.values())*dx]},
                       'checks':checks,'eligible_ids':[p['id'] for p in eligible],
                       'reason':'按各檔日花費與訂位規模正規化，等權重學習共同反應；換回歷史中位規模作為典型檔期情境，不是全部檔期預算相加。'}
    return {'individual':individual,'aggregate':{'fit':aggregate,'included_ids':[p['id'] for p in eligible],
             'total_count':len(projects),'diagnostics':diagnostics}}

def refresh_snapshot(store, settings, factory, now=None, force=False):
    now=now or datetime.now(TAIPEI)
    previous,sha=store.read(SNAPSHOT_PATH,{})
    signature=source_signature(settings)
    today=str(now.astimezone(TAIPEI).date())
    if not force and previous.get('source_signature')==signature and previous.get('updated_at') and now-datetime.fromisoformat(previous['updated_at'])<timedelta(hours=1):
        return previous
    try:
        reports={};source_warnings=[]
        festival_ids={g['id'] for g in festival_groups(settings)}
        has_meta=any(a['platform']=='meta' and any(p['account_key']==a['key'] and p.get('group_id') in festival_ids for p in settings['projects']) for a in settings['accounts'])
        meta_raw=collect_projects(settings,factory,now,platforms={'meta'},reports=reports) if has_meta else []
        try: projects=collect_projects(settings,factory,now,reports=reports)
        except AppError:
            if not meta_raw: raise
            projects=meta_raw;source_warnings.append('Google 歷史明細本次未完整取得；Meta 購買模型照常更新，Google 未取得資料不當成零。')
        through=now.astimezone(TAIPEI).date()-timedelta(days=4)
        model_projects=meta_projects(meta_raw or projects)
        models=build_models(model_projects,through)
        fit=models['aggregate']['fit']
        from mori.retention_capacity import collect_capacity_sources,collect_catalogs
        catalogs=collect_catalogs(settings,factory)
        scopes=automatic_scopes(settings,projects,catalogs)
        capacities=collect_capacity_sources(settings,factory,now,scopes=scopes)
        snapshot={'version':VERSION,'source_signature':signature,'updated_at':now.isoformat(),
                  'success_date':today,'mature_through':str(through),'projects':projects,'model_projects':model_projects,'analysis_platform':'meta','fit':fit,'models':models,'capacities':capacities,'source_catalogs':catalogs,'automatic_sources':scopes,'source_warnings':source_warnings,'last_error':None}
    except Exception as exc:
        reason=str(exc) if isinstance(exc,AppError) else '模型資料格式或運算尚未完成，保留上次成功結果，請核對來源後重試。'
        snapshot={**previous,'last_attempt':now.isoformat(),'last_error':reason}
    store.write(SNAPSHOT_PATH,snapshot,sha,message='更新私人檔期廣告模型 [skip ci]')
    return snapshot


def main():
    import os
    from mori.credentials import credentials_from_env
    from mori.storage import GitHubStore
    from mori.vault import resolve_credentials
    from mori.providers import provider_for
    from mori.core import validate_settings
    try:
        store=GitHubStore(os.environ.get('STATE_REPO',''),os.environ.get('STATE_TOKEN',''),os.environ.get('STATE_BRANCH') or 'main')
        settings=validate_settings(store.settings()[0])
        if not settings.get('festival_model',{}).get('enabled',True):
            print('Festival model status: disabled')
            return 0
        credentials=resolve_credentials(credentials_from_env(),store,os.environ.get('CREDENTIALS_KEY',''))
        result=refresh_snapshot(store,settings,lambda a:provider_for(a,credentials))
        print('Festival model status:', 'retained-last-result' if result.get('last_error') else result.get('fit',{}).get('status','unavailable'))
        return 1 if result.get('last_error') else 0
    except Exception:
        print('Festival model update failed; inspect private snapshot and application settings.')
        return 1



def allocation_projection(projects,through,duration_days):
    """Fixed Meta mix, with separately fitted direct-attribution responses.

    Cannot infer upper-funnel causal assistance from booking attribution. Never
    substitute historical average CPA for the derivative of a response curve.
    """
    from mori.festival_integrity import META_SCENARIO
    empty={'sweet':None,'upper':None,'curve':[],'candidate':None}
    if not projects or any(p.get('bookings_valid') is False for p in projects):
        return {**empty,'diagnosis':'Meta 訂位事件或花費尚未核對，暫不推估。'}
    fits={};missing=[]
    for kind,weight in META_SCENARIO.items():
        parts=[]
        for p in projects:
            component=next((c for c in p.get('components',[]) if c['platform']=='meta' and c['kind']==kind),None)
            if not component: continue
            byday={r['date']:r for r in component['rows']}
            rows=[byday.get(r['date'],{'date':r['date'],'spend':'0','bookings':'0'}) for r in p['rows']]
            parts.append({'id':p['id'],'name':p['name'],'rows':rows,'bookings_valid':component.get('bookings_valid',True)})
        if not parts:
            missing.append(kind+'：未找到對應廣告');continue
        total=sum((numeric(r['bookings']) for p in parts for r in p['rows'] if r['date']<=str(through)),Decimal(0))
        active=[float(numeric(r['spend'])) for p in parts for r in p['rows'] if r['date']<=str(through) and numeric(r['spend'])>0]
        if total==0 and len(active)>=21:
            fits[kind]={'zero_attributed':True,'ranges':{'all':[min(active),max(active)]}};continue
        model=build_models(parts,through)['aggregate']['fit']
        if model.get('status')!='estimated': missing.append(kind+'：樣本或回測不足')
        else: fits[kind]=model
    if any(c['kind'] in ('其他／待分類','轉換／未標新舊客') and numeric(c['spend'])>0 for p in projects for c in p.get('components',[])):
        missing.append('部分 Meta 廣告類型或新舊客尚未辨識')
    if missing:
        return {**empty,'diagnosis':'尚無足夠資料估計這組配置：'+'；'.join(missing)+'。保留實際 CPA，不沿用忽略配置差異的舊曲線。','missing_components':missing}
    # All proposed spends must be within each component's observed support.
    low=max(fits[k]['ranges']['all'][0]/float(w) for k,w in META_SCENARIO.items())
    high=min(fits[k]['ranges']['all'][1]/float(w) for k,w in META_SCENARIO.items())
    if low>=high:
        return {**empty,'diagnosis':'20%／5%／5%／25%／45% 配置超出歷史共同觀察範圍，暫不外推甜蜜點。'}
    points=[]
    for i in range(121):
        daily=low+(high-low)*i/120;y=0.;derivative=0.
        for kind,w in META_SCENARIO.items():
            f=fits[kind]
            if f.get('zero_attributed'): continue
            share=float(w);x=daily*share;h=hill(x,f['k'],f['slope']);a=f['amplitudes']['all']
            y+=a*h;derivative+=share*a*f['slope']*h*(1-h)/x
        if y<=0: continue
        points.append({'budget':daily*duration_days,'bookings':y*duration_days,'cpa':daily/y,'marginal_cpa':1/derivative if derivative>0 else None})
    if not points: return {**empty,'diagnosis':'這組配置尚無可估計訂位。'}
    best=min(range(len(points)),key=lambda i:points[i]['cpa']);interior=0<best<len(points)-1
    candidate={**points[best],'basis':'model_interior' if interior else 'model_boundary'}
    return {'sweet':points[best] if interior else None,'upper':None,'curve':points,'candidate':candidate,
            'diagnosis':'固定 Meta 假設配置下的直接歸因觀察模型；'+('最低點在觀察範圍內。' if interior else '最低點位於範圍邊界，尚未證明真正最低點。')+' 曝光、流量與互動的間接助攻無法由這個模型識別。'}


if __name__=='__main__':
    raise SystemExit(main())
