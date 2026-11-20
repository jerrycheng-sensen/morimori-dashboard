import copy
from datetime import date, datetime

import pytest

from mori.budgets import (collect_spend, plan_summary, save_group, save_plan,
                          spend_window, time_progress, period_state)
from mori.core import AppError, TAIPEI, default_settings, rule_window, validate_settings


def sample():
    s = default_settings()
    s['accounts'] = [{'key': 'm', 'platform': 'meta', 'name': 'Meta', 'account_id': '1'},
                     {'key': 'g', 'platform': 'google', 'name': 'Google', 'account_id': '2'}]
    s = save_group(s, {'id': 'f', 'name': '感謝祭', 'start': '2026-10-01', 'end': '2026-11-30', 'status': '進行中'})
    plan = {'id': 'meta', 'name': 'Meta預熱', 'account_key': 'm', 'group_id': 'f', 'start': '2026-09-29',
            'end': '2026-11-18', 'status': '進行中', 'budget': 100, 'keyword': '感謝祭', 'match_field': 'campaign_name'}
    s = save_plan(s, plan)
    s = save_plan(s, {**plan, 'id': 'google', 'name': 'Google', 'account_key': 'g', 'start': '2026-10-01'})
    return s


def test_platform_ad_dates_include_preheat_and_remain_independent_of_project_dates():
    s = sample()
    windows = {}
    def fetch(account, start, end):
        windows[account['key']] = (str(start), str(end))
        return {'currency': 'TWD', 'timezone': 'Asia/Taipei', 'rows': [
            {'campaign_name': '感謝祭', 'spend': 96, 'currency': 'TWD'},
            {'campaign_name': 'other', 'spend': 500, 'currency': 'TWD'}]}
    result = collect_spend(s['projects'], {a['key']: a for a in s['accounts']}, fetch, date(2026, 11, 20))
    assert windows == {'m': ('2026-09-29', '2026-11-18'), 'g': ('2026-10-01', '2026-11-18')}
    summary = plan_summary(s['projects'][0], result['meta'], date(2026, 11, 20))
    assert summary['spend'] == 96 and summary['ratio'] == .96 and summary['remaining'] == 4
    assert summary['time_ratio'] == 1 and summary['state'] == '廣告走期已結束'


def test_failure_unknown_budget_and_overspend_are_not_disguised_as_zero_or_complete():
    plan = sample()['projects'][0]
    assert plan_summary(plan, {'error': 'API'}, date(2026, 11, 20))['spend'] is None
    unknown = plan_summary({**plan, 'budget': 0}, {'spend': 96, 'currency': 'TWD'}, date(2026, 11, 20))
    assert unknown['ratio'] is None and unknown['spend'] == 96
    over = plan_summary(plan, {'spend': 110, 'currency': 'TWD'}, date(2026, 11, 20))
    assert over['ratio'] == 1.1 and over['remaining'] == -10
    def fail(*_):
        raise AppError('offline')
    r = collect_spend([plan], {'m': {}}, fail, date(2026, 11, 20))
    assert r['meta'] == {'error': 'offline'}


def test_future_plan_does_not_call_api_and_today_is_included():
    plan = sample()['projects'][0]
    def forbidden(*_):
        raise AssertionError('future plan must not fetch')
    r = collect_spend([plan], {'m': {}}, forbidden, date(2026, 9, 28))
    assert r['meta']['not_started']
    assert plan_summary(plan, r['meta'], date(2026, 9, 28))['spend'] is None
    assert spend_window(plan, date(2026, 10, 2)) == (date(2026, 9, 29), date(2026, 10, 2))
    assert time_progress('2026-11-18', '2026-11-18', date(2026, 11, 18)) == 1


def test_existing_plan_id_rules_and_unknown_fields_survive_linking():
    s = sample()
    p = s['projects'][0]
    p.pop('group_id')
    p['extra'] = 'retain'
    rule = {'id': 'r', 'name': 'CPA', 'account_key': 'm', 'project_id': p['id'], 'enabled': True,
            'level': 'ad', 'period_days': 1, 'minimum_spend': 50, 'cpa_threshold': 50}
    s['rules'] = [rule]
    updated = save_plan(s, {**p, 'group_id': 'f'})
    assert updated['projects'][0]['id'] == p['id'] and updated['projects'][0]['extra'] == 'retain'
    assert updated['rules'][0] == rule
    assert rule_window(rule, updated, datetime(2026, 11, 19, 9, tzinfo=TAIPEI))[2] == '生效中'
    assert rule_window(rule, updated, datetime(2026, 11, 20, 9, tzinfo=TAIPEI))[2] == '已到期'
    updated['project_groups'][0]['status'] = '已結案'
    assert rule_window(rule, updated, datetime(2026, 11, 19, 9, tzinfo=TAIPEI))[2] == '專案已結案'


def test_duplicate_budget_account_and_linked_rule_account_change_rejected():
    s = sample()
    with pytest.raises(AppError, match='只能有一筆'):
        save_plan(s, {**s['projects'][0], 'id': 'duplicate'})
    s['rules'] = [{'id': 'r', 'project_id': 'meta'}]
    with pytest.raises(AppError, match='異常規則'):
        save_plan(s, {**s['projects'][0], 'account_key': 'g'})
    old = default_settings()
    assert validate_settings(old) == old  # no forced rewrite of legacy settings


def test_project_rollup_uses_adjusted_allocations_and_never_totals_missing_or_mixed_currency():
    from mori.budgets import group_summary
    s = sample()
    s['projects'][0]['budget'] = 56000
    s['projects'][1]['budget'] = 144000
    s['budget_transactions'] = [{'id':'tx', 'kind':'transfer', 'source_id':'external',
        'target_id':'meta', 'amount':36386, 'effective_on':'2026-10-01'}]
    today = date(2026,11,20)
    results = {'meta':{'spend':92168,'currency':'TWD'},
               'google':{'spend':143479.53,'currency':'TWD'}}
    value = group_summary(s['projects'], results, today, s)
    assert value['budget'] == 236386
    assert value['spend'] == pytest.approx(235647.53)
    assert value['remaining'] == pytest.approx(738.47)
    assert value['ratio'] == pytest.approx(235647.53/236386)
    failed = group_summary(s['projects'], {**results,'google':{'error':'offline'}}, today, s)
    assert failed['spend'] is None and failed['budget'] is None and failed['remaining'] is None
    mixed = group_summary(s['projects'], {**results,'google':{'spend':100,'currency':'USD'}}, today, s)
    assert mixed['spend'] is None and '不同幣別' in mixed['reason']
    s['projects'][1]['budget'] = 0
    unset = group_summary(s['projects'], results, today, s)
    assert unset['spend'] == pytest.approx(235647.53) and unset['budget'] is None and unset['ratio'] is None


def test_budget_refresh_policy_initial_and_manual_without_timed_expiry():
    from datetime import timedelta
    from mori.budgets import refresh_due, configuration_key
    s = sample()
    now = datetime(2026,11,20,9,0,tzinfo=TAIPEI)
    view = {'key':configuration_key(s),'at':now.isoformat(), 'date':str(now.date())}
    assert refresh_due(s, None, now)
    assert not refresh_due(s, view, now + timedelta(seconds=59))
    assert not refresh_due(s, view, now + timedelta(hours=2))
    assert refresh_due(s, view, now, force=True)
    updated = copy.deepcopy(s)
    updated['projects'][0]['keyword'] = '新條件'
    assert refresh_due(updated, view, now)
    assert refresh_due(s, view, now + timedelta(days=1))
    assert refresh_due(s, {**view,'at':'invalid'}, now)
    assert not refresh_due({**s,'projects':[]}, None, now, force=True)


def test_identical_account_windows_fetch_once_and_still_filter_projects_independently():
    calls = []
    p = sample()['projects'][0]
    plans = [p, {**p,'id':'second','keyword':'開幕'}]
    def fetch(account, start, end):
        calls.append((account['key'],start,end))
        return {'currency':'TWD','rows':[{'campaign_name':'感謝祭','spend':100,'currency':'TWD'},
                                       {'campaign_name':'開幕','spend':200,'currency':'TWD'}]}
    result = collect_spend(plans, {'m':{'key':'m','platform':'meta'}}, fetch, date(2026,11,20))
    assert len(calls) == 1
    assert result[p['id']]['spend'] == 100 and result['second']['spend'] == 200



def test_live_budget_includes_first_and_last_ad_day_and_caps_ended_plans():
    p = sample()['projects'][0]
    windows = []
    def fetch(account,start,end):
        windows.append((start,end))
        return {'currency':'TWD','rows':[{'campaign_name':'感謝祭','spend':99,'currency':'TWD'}]}
    accounts = {'m':{'platform':'meta'}}
    first = collect_spend([p],accounts,fetch,date(2026,9,29))['meta']
    assert windows[-1] == (date(2026,9,29),date(2026,9,29))
    assert first['includes_today'] and first['spend'] == 99
    last = collect_spend([p],accounts,fetch,date(2026,11,18))['meta']
    assert windows[-1][1] == date(2026,11,18) and last['includes_today']
    assert plan_summary(p,last,date(2026,11,18))['remaining'] == 1
    ended = collect_spend([p],accounts,fetch,date(2026,11,20))['meta']
    assert windows[-1][1] == date(2026,11,18) and not ended['includes_today']



def test_period_and_advertising_states_are_independent_and_include_date_boundaries():
    from mori.budgets import period_state, advertising_state
    today = date(2026,11,20)
    assert period_state('2026-10-01','2026-11-30',today) == '進行中'
    ended = {'start':'2026-09-29','end':'2026-11-18','status':'已結案'}
    assert advertising_state([ended],today) == '已結案'
    assert period_state('2026-11-21','2026-12-01',today) == '準備中'
    assert period_state('2026-11-20','2026-11-20',today) == '進行中'
    assert period_state('2026-11-01','2026-11-19',today) == '已結案'
    assert advertising_state([ended, {'start':'2026-11-21','end':'2026-12-01'}],today) == '準備中'
    assert advertising_state([ended, {'start':'2026-11-20','end':'2026-12-01'}],today) == '進行中'


def test_budget_sums_original_decimal_cost_without_per_row_rounding():
    s = sample()
    def fetch(account, start, end):
        return {'currency': 'TWD', 'spend_basis': 'meta_ad_whole_period', 'rows': [
            {'campaign_name': '感謝祭', 'spend': .1, 'spend_raw': '0.10', 'currency': 'TWD'},
            {'campaign_name': '感謝祭', 'spend': .2, 'spend_raw': '0.20', 'currency': 'TWD'},
            {'campaign_name': 'other', 'spend': 99, 'currency': 'TWD'}]}
    r = collect_spend([s['projects'][0]], {'m': s['accounts'][0]}, fetch, date(2026,11,20))['meta']
    assert r['spend_raw'] == '0.30' and r['spend'] == .3
    assert r['spend_basis'] == 'meta_ad_whole_period'


@pytest.mark.parametrize('scope', ['project_groups', 'projects'])
def test_preparing_management_status_roundtrips_and_pauses_rules(scope):
    s = sample()
    rule = {'id': 'r', 'account_key': 'm', 'project_id': 'meta', 'enabled': True, 'period_days': 1}
    now = datetime(2026, 11, 19, 9, tzinfo=TAIPEI)
    s[scope][0]['status'] = '準備中'
    saved = validate_settings(s)
    assert saved[scope][0]['status'] == '準備中'
    assert rule_window(rule, saved, now)[2] == '專案準備中'
    # Manual management doesn't change date-based project navigation or spend windows.
    assert period_state(saved['project_groups'][0]['start'], saved['project_groups'][0]['end'], now.date()) == '進行中'
    assert spend_window(saved['projects'][0], now.date()) == (date(2026, 9, 29), date(2026, 11, 18))
    saved[scope][0]['status'] = '進行中'
    assert rule_window(rule, saved, now)[2] == '生效中'
