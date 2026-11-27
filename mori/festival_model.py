"""Two whole-project advertising response model and private daily snapshots.

A small, explicitly observational Hill response fit; not Meridian, causal lift,
operating ROI, or a proof that spend caused bookings. No operational data used.
"""
import hashlib
import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal

from mori.core import AppError, TAIPEI
from mori.project_types import baseline_groups
from mori.project_matching import verified_match, unit_identity

SNAPSHOT_PATH = 'festival-model.json'
VERSION = 1


def source_signature(settings):
    groups = baseline_groups(settings)
    ids = {g['id'] for g in groups}
    plans = [p for p in settings['projects'] if p.get('group_id') in ids]
    keys = {p['account_key'] for p in plans}
    value = [VERSION,groups,plans,[a for a in settings['accounts'] if a['key'] in keys],settings.get('budget_transactions',[])]
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def numeric(value):
    try:
        result = Decimal(str(value))
    except Exception:
        raise AppError('檔期資料缺少有效數值。') from None
    if not result.is_finite() or result < 0:
        raise AppError('檔期資料有缺值或負向調整，暫不建立模型。')
    return result


def collect_projects(settings, factory, now):
    """Read complete ad windows regardless of project/plan management status."""
    from mori.budget_ledger import balance
    through = now.astimezone(TAIPEI).date()-timedelta(days=1)
    accounts = {a['key']:a for a in settings['accounts']}
    output, cache, ownership = [], {}, {}
    for group in baseline_groups(settings):
        plans = [p for p in settings['projects'] if p.get('group_id')==group['id']]
        if not plans: raise AppError('檔期尚未設定平台投放計畫。')
        days, currencies = {}, set()
        planned_start = min(date.fromisoformat(p['start']) for p in plans)
        planned_end = max(date.fromisoformat(p['end']) for p in plans)
        authoritative, daily_cost, budget = Decimal(0),Decimal(0),Decimal(0)
        plan_audit = []
        for plan in plans:
            account = accounts[plan['account_key']]
            start,end = date.fromisoformat(plan['start']),min(through,date.fromisoformat(plan['end']))
            budget += Decimal(str(balance(settings,plan['id'],through)['adjusted']))
            if start>end: continue
            cache_key=(account['key'],str(start),str(end))
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
                    raise AppError('兩檔或平台計畫認列重疊，暫不建立模型，請先核對專案條件。')
                ownership[unit_key]=group['id']
                item=days.setdefault(str(row['date']),{'spend':Decimal(0),'bookings':Decimal(0)})
                item['spend']+=cost;item['bookings']+=bookings
                matched.append(row)
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
            daily_cost+=plan_daily;authoritative+=plan_authoritative
            plan_audit.append({'plan_id':plan['id'],'platform':account['platform'],'since':str(start),'until':str(end),
                               'daily_cost':str(plan_daily),'whole_cost':str(plan_authoritative),
                               'difference':str(plan_daily-plan_authoritative),'event':account.get('meta_action_type') if account['platform']=='meta' else account.get('google_action_ids',[])})
        if len(currencies)!=1: raise AppError('模型兩檔的帳號幣別須一致且完整。')
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
                       'rows':rows,'audit':plan_audit})
    if len({p['currency'] for p in output})!=1:
        raise AppError('兩檔幣別不同，不能合併訓練。')
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
        rows=[(float(numeric(r['spend'])),float(numeric(r['bookings']))) for r in p['rows'] if r['date']<=str(through)]
        active=[x for x,y in rows if x>0]
        if len(rows)<28 or len(active)<21 or len(set(active))<8 or sum(y for x,y in rows)<30:
            return {'status':'insufficient','reason':'每檔至少需 28 個成熟資料日、21 個有花費日、8 種日花費及 30 次訂位；門檻是操作護欄，不是統計證明。'}
        series[p['id']]=rows
    if len(series)!=2: return {'status':'insufficient','reason':'需完整兩檔資料。'}
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
                  reason='兩檔共同形狀、各檔各自規模的廣告歸因反應曲線；未控制競價、素材、星期、受眾及延遲效應，不是因果或營運 ROI 模型。')
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


def refresh_snapshot(store, settings, factory, now=None, force=False):
    now=now or datetime.now(TAIPEI)
    previous,sha=store.read(SNAPSHOT_PATH,{})
    signature=source_signature(settings)
    today=str(now.astimezone(TAIPEI).date())
    if not force and previous.get('source_signature')==signature and previous.get('success_date')==today:
        return previous
    try:
        projects=collect_projects(settings,factory,now)
        through=now.astimezone(TAIPEI).date()-timedelta(days=4)
        fit=fit_projects(projects,through)
        snapshot={'version':VERSION,'source_signature':signature,'updated_at':now.isoformat(),
                  'success_date':today,'mature_through':str(through),'projects':projects,'fit':fit,'last_error':None}
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


if __name__=='__main__':
    raise SystemExit(main())
