"""Project envelopes group existing account-level plans without changing their IDs."""
from __future__ import annotations

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from mori.core import AppError


def configuration_key(settings):
    return hashlib.sha256(json.dumps(['google-attribution-v3-include-today', settings.get('projects', []), settings.get('project_groups', []),
                                     settings.get('accounts', [])], sort_keys=True).encode()).hexdigest()


def time_progress(start, end, through):
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    return max(0., min(1., ((through - start).days + 1) / ((end - start).days + 1)))


def spend_window(plan, today):
    start = date.fromisoformat(plan['start'])
    end = min(date.fromisoformat(plan['end']), today)
    return (start, end) if start <= end else None


def plan_summary(plan, result, today, settings=None):
    from mori.budget_ledger import balance
    budget = balance(settings, plan["id"], today)["adjusted"] if settings is not None else float(plan.get("budget", 0))
    if plan.get('status') == '已結案':
        state = '已結案'
    elif today < date.fromisoformat(plan['start']):
        state = '尚未開始'
    elif today > date.fromisoformat(plan['end']):
        state = '廣告走期已結束'
    else:
        state = '廣告走期內'
    known = result is not None and not result.get('error') and not result.get('not_started')
    spend = float(result['spend']) if known else None
    percent = spend / budget if known and budget > 0 else None
    return {'state': state, 'budget': budget, 'spend': spend,
            'remaining': budget - spend if spend is not None else None, 'ratio': percent,
            'time_ratio': time_progress(plan['start'], plan['end'], today),
            'currency': result.get('currency') if known else None}


def refresh_due(settings, view, now, force=False):
    """Initial load/manual refresh only; no time-based polling or expiry."""
    if not settings['projects']:
        return False
    if force or not view or view.get('key') != configuration_key(settings) or view.get('date') != str(now.date()):
        return True
    try:
        datetime.fromisoformat(view['at'])
    except (ValueError, TypeError, KeyError):
        return True
    return False


def period_state(start, end, today, closed=False):
    if closed or today > date.fromisoformat(str(end)):
        return '已結案'
    if today < date.fromisoformat(str(start)):
        return '準備中'
    return '進行中'


def advertising_state(plans, today):
    states = [period_state(p['start'], p['end'], today, p.get('status') == '已結案') for p in plans]
    if not states:
        return '準備中'
    if all(s == '已結案' for s in states):
        return '已結案'
    if '進行中' in states:
        return '進行中'
    return '準備中'


def group_summary(plans, results, today, settings):
    """Combine a project's platform envelopes only when currency/cost are known."""
    from mori.budget_ledger import balance, impacts
    summaries = [plan_summary(p, results.get(p['id']), today, settings) for p in plans]
    currencies = {d['currency'] for d in summaries if d['currency']}
    known = bool(summaries) and all(d['spend'] is not None and d['currency'] for d in summaries)
    same_currency = known and len(currencies) == 1
    initialized = all(balance(settings, p['id'], today)['original'] > 0 or
                      any(p['id'] in impacts(t) for t in settings.get('budget_transactions', [])) for p in plans)
    spend = sum(d['spend'] for d in summaries) if same_currency else None
    budget = sum(d['budget'] for d in summaries) if same_currency and initialized else None
    return {'budget': budget, 'spend': spend,
            'remaining': budget - spend if budget is not None else None,
            'ratio': spend / budget if budget is not None and budget > 0 else None,
            'currency': next(iter(currencies)) if same_currency else None,
            'reason': '不同幣別分開呈現，不加總為專案金額。' if len(currencies) > 1 else
                      '待所有平台花費與幣別讀取成功後，顯示專案合計。' if not known else
                      '部分平台預算尚未設定，暫不計算總預算與整體進度。' if not initialized else ''}


def collect_spend(plans, accounts, fetch, today):
    """A failed read remains unknown, never zero. Each plan includes reported spend today, capped at its ad end date."""
    def one(plan, report):
        window = spend_window(plan, today)
        if not window:
            return {'not_started': True, 'spend': 0., 'currency': None,
                    'since': None, 'until': None, 'rows': []}
        start, end = window
        from mori.project_matching import matches, conditions
        rules = conditions(plan)
        if accounts[plan['account_key']].get('platform') == 'google' and any(c['field'] != 'campaign_name' for c in rules) and not report.get('attribution_detail'):
            raise AppError('尚未取得 Google 廣告明細，不能用文案或廣告群組認列花費。')
        rows = [r for r in report['rows'] if matches(plan, r)]
        warnings = list(report.get('warnings', []))
        if accounts[plan['account_key']].get('platform') == 'google' and any(c['field'] != 'campaign_name' for c in rules):
            warnings.append('文案為 API 目前設定，不代表歷史每次曝光的文案；花費以整則廣告／整個素材群組與設定走期認列。')
            if any(r.get('channel') == 'PERFORMANCE_MAX' for r in rows):
                warnings.append('PMax 以素材群組認列花費：標題／說明／路徑命中即計入該素材群組整筆花費，無法分拆成單一字詞或單一素材的花費；請確認群組沒有混用多個專案。')
            copy_fields = {c['field'] for c in rules} & {'headlines', 'descriptions', 'paths'}
            incomplete = [r for r in report['rows'] if copy_fields and 'available_fields' in r
                          and not copy_fields.issubset(set(r['available_fields'])) and not matches(plan, r)]
            if incomplete:
                formats = '、'.join(sorted({r.get('ad_type', 'UNKNOWN') for r in incomplete}))
                amount = sum(float(r['spend']) for r in incomplete)
                warnings.append(f'有 {len(incomplete)} 筆廣告／日資料未提供全部選定的文案欄位，未命中且未納入花費 {report["currency"]} {amount:,.2f}（格式：{formats}）。可改用廣告活動、廣告群組或 ID 認列；缺少路徑不代表零花費。')
            if any(c['field'] in ('adset_name', 'ad_id') for c in rules) and any(r.get('channel') == 'PERFORMANCE_MAX' for r in report['rows']):
                warnings.append('PMax 使用素材群組，不是一般廣告群組或單一廣告 ID；如需指定 PMax，請選素材群組名稱／ID 或廣告活動。')
        currencies = {r['currency'] for r in rows}
        if len(currencies) > 1 or (currencies and report['currency'] not in currencies):
            raise AppError('回傳資料包含不同幣別，已停止加總。')
        spend = sum(float(r['spend']) for r in rows)
        if spend < 0:
            raise AppError('回傳負花費，請先核對平台帳務調整。')
        return {'spend': spend, 'currency': report['currency'], 'since': str(start), 'until': str(end),
                'rows': rows, 'timezone': report.get('timezone'), 'warnings': warnings, 'includes_today': end == today}
    results = {}
    # Several projects often share the same account/window. Fetch once, then
    # apply each plan's attribution independently; never share across accounts.
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(plans)))) as pool:
        jobs = {}
        windows = {}
        for plan in plans:
            window = spend_window(plan, today)
            key = (plan['account_key'], *window) if window else None
            windows[plan['id']] = key
            if key is not None and key not in jobs:
                jobs[key] = pool.submit(fetch, accounts[plan['account_key']], *window)
        for plan in plans:
            try:
                key = windows[plan['id']]
                results[plan['id']] = one(plan, jobs[key].result() if key is not None else None)
            except AppError as exc:
                results[plan['id']] = {'error': str(exc)}
    owners = {}
    conflicts = set()
    for plan in plans:
        if accounts[plan['account_key']].get('platform') != 'google':
            continue
        for row in results[plan['id']].get('rows', []):
            if not row.get('date') or not row.get('campaign_id') or not row.get('spend'):
                continue
            key = (plan['account_key'], row['date'], row['campaign_id'], row.get('adset_id', ''), row.get('ad_id', ''), row.get('asset_group_id', ''))
            if key in owners and owners[key] != plan['id']:
                conflicts.update((owners[key], plan['id']))
            owners[key] = plan['id']
    for plan_id in conflicts:
        results[plan_id] = {'error': '同一天的 Google 廣告花費符合多個專案；請縮小文字、廣告 ID 或走期條件，避免重複認列。'}
    return results


def save_group(settings, group):
    from mori.core import validate_settings
    updated = copy.deepcopy(settings)
    groups = updated.setdefault('project_groups', [])
    old = next((p for p in groups if p['id'] == group['id']), None)
    item = {**(old or {}), **group}
    updated['project_groups'] = [item if p['id'] == item['id'] else p for p in groups] if old else groups + [item]
    from mori.budget_ledger import protect_history
    protect_history(settings, updated)
    return validate_settings(updated)


def save_plan(settings, plan):
    from mori.core import validate_settings
    updated = copy.deepcopy(settings)
    old = next((p for p in updated['projects'] if p['id'] == plan['id']), None)
    if old and old['account_key'] != plan['account_key'] and any(r.get('project_id') == plan['id'] for r in settings['rules']):
        raise AppError('此平台計畫已連結異常規則，不能直接換成另一個廣告帳號；請新增平台計畫。')
    item = {**(old or {}), **plan}
    updated['projects'] = [item if p['id'] == item['id'] else p for p in updated['projects']] if old else updated['projects'] + [item]
    from mori.budget_ledger import protect_history
    protect_history(settings, updated)
    return validate_settings(updated)
