from datetime import date
from decimal import Decimal

import pytest

from mori.account_funding import collect_accounts, summary_totals, default_since
from mori.core import AppError, default_settings

START, END = date(2026, 9, 29), date(2026, 11, 22)


def settings():
    s = default_settings()
    s['accounts'] = [{'key':'m','platform':'meta','account_id':'123','name':'Meta'},
                     {'key':'duplicate','platform':'meta','account_id':'act_123','name':'同一帳號'},
                     {'key':'g','platform':'google','account_id':'456','name':'Google'}]
    s['projects'] = [{'start':'2026-09-29'}]
    s['project_invoices'] = [{'id':'i1','platform':'meta','registered_on':'2026-10-01','currency':'TWD','allocated_amount':'100'},
                             {'id':'i2','platform':'google','registered_on':'2026-10-02','currency':'TWD','allocated_amount':'200'},
                             {'id':'void','platform':'meta','registered_on':'2026-10-03','currency':'TWD','allocated_amount':'999'},
                             {'id':'old','platform':'meta','registered_on':'2025-01-01','currency':'TWD','allocated_amount':'999'}]
    s['invoice_voids'] = [{'invoice_id':'void'}]
    return s


def test_header_uses_unique_full_accounts_not_project_spend_and_excludes_voided_proof():
    s = settings()
    calls = []
    def fetch(account, start, end):
        calls.append(account['platform'])
        return {'spend_raw':'92.166' if account['platform'] == 'meta' else '143.47953',
                'currency':'TWD','since':str(start),'until':str(end)}
    results = collect_accounts(s, fetch, START, END)
    assert sorted(calls) == ['google','meta']  # Legacy duplicate records do not duplicate cost.
    rows, total = summary_totals(s, results, START, END)
    assert rows['meta']['funds']['TWD'] == 100 and rows['google']['funds']['TWD'] == 200
    assert rows['meta']['accounts'] == 1
    assert total['funds'] == Decimal('300') and total['spent'] == Decimal('235.64553')
    assert default_since(s, END) == date(2025, 1, 1)


def test_header_failure_and_different_currencies_never_hide_unknowns_or_convert():
    s = settings()
    def fetch(account, start, end):
        if account['platform'] == 'meta':
            raise AppError('Meta 讀取失敗')
        return {'spend_raw':'100','currency':'TWD','since':str(start),'until':str(end)}
    results = collect_accounts(s, fetch, START, END)
    rows, total = summary_totals(s, results, START, END)
    assert rows['meta']['spent'] is None and total is None
    assert rows['meta']['funds']['TWD'] == 100
    results[('meta','123')] = {'spend_raw':'100','currency':'USD'}
    rows, total = summary_totals(s, results, START, END)
    assert rows['meta']['spent']['USD'] == 100 and total is None


@pytest.mark.parametrize('patch', [{'spend_raw':'NaN'},{'spend_raw':'-1'},{'until':'2026-11-21'},{'currency':''}])
def test_invalid_account_cost_remains_unknown(patch):
    s = settings()
    result = {'spend_raw':'100','currency':'TWD','since':str(START),'until':str(END),**patch}
    results = collect_accounts(s, lambda *args:result, START, END)
    assert all(r.get('error') for r in results.values())
