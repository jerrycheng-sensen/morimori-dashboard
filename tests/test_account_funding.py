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


def budget_settings():
    s = default_settings()
    s['accounts'] = [{'key':'m','platform':'meta','account_id':'123','name':'Meta','currency':'TWD'},
                     {'key':'g','platform':'google','account_id':'456','name':'Google','currency':'TWD'}]
    s['project_groups'] = [{'id':'f','name':'感謝祭'}]
    base = {'group_id':'f','start':'2026-09-29','end':'2026-11-18','name':'平台計畫'}
    s['projects'] = [{**base,'id':'m','account_key':'m','budget':100},
                     {**base,'id':'g','account_key':'g','budget':200}]
    return s


def test_project_budgets_show_without_invoices_and_count_projects_once():
    from mori.account_funding import project_budget_totals
    s = budget_settings()
    result = project_budget_totals(s, {}, END)
    assert result['totals']['TWD'] == Decimal('300')
    assert result['missing_projects'] == 1 and len(result['pending']) == 2
    s['project_invoices'] = [{'id':'i1','plan_id':'m','currency':'TWD','allocated_amount':'50'}]
    result = project_budget_totals(s, {}, END)
    assert result['totals']['TWD'] == 300  # Invoice amount never replaces budget.
    assert result['missing_projects'] == 1 and [r['plan_id'] for r in result['pending']] == ['g']
    s['invoice_voids'] = [{'invoice_id':'i1'}]
    assert len(project_budget_totals(s, {}, END)['pending']) == 2


def test_budget_transfer_is_neutral_and_adjustments_are_counted():
    from mori.account_funding import project_budget_totals
    s = budget_settings()
    s['budget_transactions'] = [{'id':'t','kind':'transfer','amount':30,'source_id':'m','target_id':'g','effective_on':'2026-11-01'},
                                {'id':'a','kind':'adjustment','amount':20,'target_id':'m','effective_on':'2026-11-02'}]
    result = project_budget_totals(s, {}, END)
    assert result['totals']['TWD'] == Decimal('320')
    assert result['platforms']['meta']['totals']['TWD'] == 90
    assert result['platforms']['google']['totals']['TWD'] == 230
    s['accounts'][0].pop('currency')
    result = project_budget_totals(s, {('meta','123'):{'error':'API error'}}, END)
    assert result['platforms']['meta']['totals']['?meta:123'] == 90
    assert result['totals']['TWD'] == 230  # Never assign the other account's currency.


def test_project_kpis_use_same_scope_instead_of_unrelated_account_spend():
    from mori.account_funding import project_kpis
    s = budget_settings()
    results = {'m': {'spend_raw':'90.01','spend':90.01,'currency':'TWD'},
               'g': {'spend_raw':'120.02','spend':120.02,'currency':'TWD'}}
    accounts = {('meta','123'):{'currency':'TWD','spend_raw':'9999'},
                ('google','456'):{'currency':'TWD','spend_raw':'9999'}}
    v = project_kpis(s, results, accounts, END)
    assert v['combined']['budget']['TWD'] == 300
    assert v['combined']['spent']['TWD'] == Decimal('210.03')
    assert v['combined']['remaining']['TWD'] == Decimal('89.97')
    results['m']['spend_raw'] = '250.00'
    v = project_kpis(s, results, accounts, END)
    assert v['combined']['remaining']['TWD'] == Decimal('-70.02')


def test_project_kpis_unknown_unset_and_future_are_distinct():
    from mori.account_funding import project_kpis
    s = budget_settings()
    results = {'m': {'error':'API讀取失敗'}, 'g': {'spend':100, 'currency':'TWD'}}
    v = project_kpis(s, results, {}, END)
    assert v['combined']['remaining'] is None and v['combined']['spent'] is None
    assert v['combined']['budget']['TWD'] == 300
    assert v['platforms']['google']['remaining']['TWD'] == 100
    s['projects'][0]['start'] = '2027-01-01'
    v = project_kpis(s, results, {}, END)
    assert v['combined']['spent']['TWD'] == 100
    assert v['combined']['remaining']['TWD'] == 200
    s['projects'][1]['budget'] = 0
    assert project_kpis(s, results, {}, END)['combined']['remaining'] is None


def test_project_kpis_do_not_double_count_overlapping_meta_ads():
    from mori.account_funding import project_kpis
    s = budget_settings()
    s['projects'][1]['account_key'] = 'm'
    row = {'campaign_id':'c', 'ad_id':'same-ad', 'spend':10}
    results = {key:{'spend':10,'currency':'TWD','since':'2026-09-29','until':'2026-11-18','rows':[row]}
               for key in ('m','g')}
    v = project_kpis(s, results, {}, END)
    assert v['combined']['remaining'] is None and v['combined']['spent'] is None
    assert any('重疊' in error for error in v['platforms']['meta']['errors'])
    results['g']['since'] = '2026-11-19'
    results['g']['until'] = '2026-11-22'
    v = project_kpis(s, results, {}, END)
    assert v['combined']['spent']['TWD'] == 20
    assert v['combined']['remaining']['TWD'] == 280
