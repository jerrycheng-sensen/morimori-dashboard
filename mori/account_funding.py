"""Header totals: invoice-recognized funding and direct account-level spend."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from mori.core import AppError
from mori.invoices import active_records


def account_identity(account):
    return (account['platform'], str(account['account_id']).removeprefix('act_').replace('-', ''))


def default_since(settings, today):
    dates = [date.fromisoformat(p['start']) for p in settings['projects']]
    dates += [date.fromisoformat(r['registered_on']) for r in settings.get('project_invoices', [])]
    return min([today, *dates]) if dates else date(today.year, 1, 1)


def view_key(settings, start, end):
    # Changes to account metadata can alter query scope; invoice amounts are local
    # and never require another cost read when the reporting window is unchanged.
    return hashlib.sha256(json.dumps([settings['accounts'], str(start), str(end)], sort_keys=True).encode()).hexdigest()


def collect_accounts(settings, fetch, start, end):
    accounts = {account_identity(a): a for a in settings['accounts']}
    results = {}
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(accounts)))) as pool:
        jobs = {key: pool.submit(fetch, account, start, end) for key, account in accounts.items()}
        for key, future in jobs.items():
            try:
                row = future.result()
                amount = Decimal(str(row['spend_raw']))
                if (not amount.is_finite() or amount < 0 or not re.fullmatch(r'[A-Z]{3}', row['currency'])
                        or row.get('since') != str(start) or row.get('until') != str(end)):
                    raise AppError('帳號花費金額、幣別或期間不正確，未當成零值。')
                results[key] = row
            except AppError as exc:
                results[key] = {'error': str(exc)}
            except (KeyError, TypeError, InvalidOperation, ValueError):
                results[key] = {'error': '帳號花費回傳資料不完整，未當成零值。'}
    return results


def summary_totals(settings, results, start, end):
    summary = {}
    for platform in ('meta', 'google'):
        accounts = {account_identity(a) for a in settings['accounts'] if a['platform'] == platform}
        invoices = [r for r in active_records(settings) if r['platform'] == platform and str(start) <= r['registered_on'] <= str(end)]
        funds, spent = {}, {}
        for row in invoices:
            cur = row['currency']
            funds[cur] = funds.get(cur, Decimal(0)) + Decimal(row['allocated_amount'])
        known = bool(accounts) and all(key in results and not results[key].get('error') for key in accounts)
        if known:
            for key in accounts:
                row = results[key]
                cur = row['currency']
                spent[cur] = spent.get(cur, Decimal(0)) + Decimal(row['spend_raw'])
        summary[platform] = {'funds': funds, 'spent': spent if known else None, 'accounts': len(accounts),
                             'invoices': len(invoices), 'errors': [results.get(key, {}).get('error', '尚未取得帳號花費') for key in sorted(accounts)
                                                                   if key not in results or results[key].get('error')]}
    currencies = {cur for p in summary.values() for cur in [*p['funds'], *(p['spent'] or {})]}
    existing = [p for p in summary.values() if p['accounts']]
    combined = None
    if existing and all(p['spent'] is not None for p in existing) and len(currencies) == 1:
        cur = next(iter(currencies))
        combined = {'currency': cur, 'funds': sum((p['funds'].get(cur, Decimal(0)) for p in existing), Decimal(0)),
                    'spent': sum((p['spent'].get(cur, Decimal(0)) for p in existing), Decimal(0)),
                    'invoices': sum(p['invoices'] for p in existing)}
    return summary, combined


def project_budget_totals(settings, results, through):
    """Sum current plan envelopes, independently of invoices and spend failures.

    Currency comes from the account API or explicit account configuration. An
    unconfirmed account stays in its own bucket; its numeric budget can still be
    shown without pretending that its currency matches another account.
    """
    from mori.budget_ledger import balance, money, impacts
    from mori.invoices import invoice_summary
    accounts = {a['key']: a for a in settings['accounts']}
    groups = {g['id']: g for g in settings.get('project_groups', [])}
    platforms = {p: {'totals': {}, 'pending': [], 'plans': 0, 'unset': 0} for p in ('meta', 'google')}
    all_pending = []
    for plan in settings['projects']:
        account = accounts[plan['account_key']]
        identity = account_identity(account)
        report = results.get(identity, {})
        currency = report.get('currency') or account.get('currency', '')
        if not re.fullmatch(r'[A-Z]{3}', str(currency)):
            currency = '?' + ':'.join(identity)
        value = platforms[account['platform']]
        value['plans'] += 1
        amount = money(balance(settings, plan['id'], through)['adjusted'])
        value['totals'][currency] = value['totals'].get(currency, Decimal(0)) + amount
        if not plan.get('budget') and not any(plan['id'] in impacts(t)
                                               for t in settings.get('budget_transactions', [])):
            value['unset'] += 1
        if not invoice_summary(settings, plan['id'])['count']:
            group = groups.get(plan.get('group_id'))
            pending = {'plan_id': plan['id'], 'project_key': 'group:' + group['id'] if group else 'plan:' + plan['id'],
                       'name': group['name'] if group else plan['name'], 'platform': account['platform'],
                       'account_name': account['name']}
            value['pending'].append(pending)
            all_pending.append(pending)
    totals = {}
    for value in platforms.values():
        for cur, amount in value['totals'].items():
            totals[cur] = totals.get(cur, Decimal(0)) + amount
    return {'platforms': platforms, 'totals': totals, 'pending': all_pending,
            'missing_projects': len({r['project_key'] for r in all_pending}),
            'plans': len(settings['projects']), 'unset': sum(v['unset'] for v in platforms.values())}


def project_kpis(settings, project_results, account_results, through):
    """Comparable planned-budget/spend/remaining totals for the same plan set."""
    accounts = {a['key']: a for a in settings['accounts']}
    sources = {key: dict(value) for key, value in account_results.items()}
    for plan in settings['projects']:
        result = project_results.get(plan['id'], {})
        key = account_identity(accounts[plan['account_key']])
        if result.get('currency') and not result.get('error') and not sources.get(key, {}).get('currency'):
            sources.setdefault(key, {})['currency'] = result['currency']
    planning = project_budget_totals(settings, sources, through)
    values = {}
    for platform in ('meta', 'google'):
        plans = [p for p in settings['projects'] if accounts[p['account_key']]['platform'] == platform]
        spent, errors, owners = {}, [], {}
        for plan in plans:
            result = project_results.get(plan['id'], {})
            if date.fromisoformat(plan['start']) > through:
                continue  # Before advertising starts, the plan has no incurred spend.
            if not result or result.get('error') or not result.get('currency'):
                errors.append(result.get('error', '部分專案花費尚未取得。'))
                continue
            key = account_identity(accounts[plan['account_key']])
            currency = result['currency']
            if sources.get(key, {}).get('currency') != currency:
                errors.append('專案與帳號回報幣別不一致，暫不計算剩餘預算。')
                continue
            try:
                amount = Decimal(str(result['spend_raw'] if 'spend_raw' in result else result['spend']))
                if not amount.is_finite() or amount < 0:
                    raise ValueError()
            except (KeyError, ValueError, InvalidOperation):
                errors.append('部分專案花費金額不正確。')
                continue
            spent[currency] = spent.get(currency, Decimal(0)) + amount
            # Full-period Meta rows cannot safely be added across overlapping
            # project windows for the same ad. Fail closed rather than guessing.
            for row in result.get('rows', []):
                if not row.get('spend'):
                    continue
                entity = row.get('ad_id') or row.get('asset_group_id')
                if not entity:
                    continue
                identity = (key, row.get('campaign_id'), entity)
                start = row.get('date') if platform == 'google' else result.get('since', plan['start'])
                end = row.get('date') if platform == 'google' else result.get('until', plan['end'])
                if not start or not end:
                    continue
                for old_start, old_end, owner in owners.get(identity, []):
                    if owner != plan['id'] and max(old_start, start) <= min(old_end, end):
                        errors.append('同一廣告花費在不同專案的走期重疊，請調整認列條件；未重複加總。')
                owners.setdefault(identity, []).append((start, end, plan['id']))
        budget = planning['platforms'][platform]
        # Include zero-cost future plans in the confirmed currency buckets.
        for currency in budget['totals']:
            if not currency.startswith('?'):
                spent.setdefault(currency, Decimal(0))
        remaining = None
        if not errors and not budget['unset'] and not any(c.startswith('?') for c in budget['totals']):
            remaining = {c: amount - spent.get(c, Decimal(0)) for c, amount in budget['totals'].items()}
        values[platform] = {'budget': budget['totals'], 'spent': spent if not errors else None,
                            'remaining': remaining, 'errors': sorted(set(errors)), 'plans': len(plans)}
    combined = {'budget': planning['totals'], 'spent': {}, 'remaining': {}}
    for field in ('spent', 'remaining'):
        for platform, value in values.items():
            if not value['plans']:
                continue
            if value[field] is None:
                combined[field] = None
                break
            for currency, amount in value[field].items():
                combined[field][currency] = combined[field].get(currency, Decimal(0)) + amount
    return {'platforms': values, 'combined': combined, 'planning': planning}
