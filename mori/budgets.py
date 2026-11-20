"""Project envelopes group existing account-level plans without changing their IDs."""
from __future__ import annotations

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from mori.core import AppError


def configuration_key(settings):
    return hashlib.sha256(json.dumps(['google-attribution-v2', settings.get('projects', []), settings.get('project_groups', []),
                                     settings.get('accounts', [])], sort_keys=True).encode()).hexdigest()


def time_progress(start, end, through):
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    return max(0., min(1., ((through - start).days + 1) / ((end - start).days + 1)))


def spend_window(plan, today):
    start = date.fromisoformat(plan['start'])
    end = min(date.fromisoformat(plan['end']), today - timedelta(days=1))
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
            'time_ratio': time_progress(plan['start'], plan['end'], today - timedelta(days=1)),
            'currency': result.get('currency') if known else None}


def collect_spend(plans, accounts, fetch, today):
    """A failed read remains unknown, never zero. Each plan uses its whole ad window."""
    def one(plan):
        window = spend_window(plan, today)
        if not window:
            return {'not_started': True, 'spend': 0., 'currency': None,
                    'since': None, 'until': None, 'rows': []}
        start, end = window
        report = fetch(accounts[plan['account_key']], start, end)
        from mori.project_matching import matches, conditions
        rules = conditions(plan)
        if accounts[plan['account_key']].get('platform') == 'google' and any(c['field'] != 'campaign_name' for c in rules) and not report.get('attribution_detail'):
            raise AppError('尚未取得 Google 廣告明細，不能用文案或廣告群組認列花費。')
        rows = [r for r in report['rows'] if matches(plan, r)]
        warnings = []
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
                'rows': rows, 'timezone': report.get('timezone'), 'warnings': warnings}
    results = {}
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(plans)))) as pool:
        jobs = [(plan, pool.submit(one, plan)) for plan in plans]
        for plan, job in jobs:
            try:
                results[plan['id']] = job.result()
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
