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
