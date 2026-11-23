from decimal import Decimal as D

from mori.budget_visuals import totals_progress


def test_progress_exact_decimal_and_known_zero_spend():
    html = totals_progress({'TWD': D('92386')}, {'TWD': D('92166')}, {'TWD': D('220')})
    assert '已使用 99.8%' in html
    assert 'width:99.762%' in html
    assert '已使用 0.0%' in totals_progress({'TWD': D('10')}, {'TWD': D('0')}, {'TWD': D('10')})


def test_progress_retains_overrun_but_caps_track():
    html = totals_progress({'TWD': D('100')}, {'TWD': D('125.5')}, {'TWD': D('-25.5')})
    assert '125.5%' in html and '已超支' in html
    assert 'width:100.000%' in html


def test_progress_never_turns_missing_or_unset_data_into_zero():
    for budget, spent, remaining in [({'TWD': D('100')}, None, None),
                                      ({'TWD': D('0')}, {'TWD': D('0')}, {}),
                                      ({'?meta:123': D('10')}, {'?meta:123': D('1')}, {}),
                                      ({'TWD': D('100')}, {'USD': D('1')}, {}),
                                      ({'TWD': D('100')}, {'TWD': D('1')}, None)]:
        html = totals_progress(budget, spent, remaining)
        assert '待資料完整' in html
        assert 'width:' not in html


def test_progress_keeps_currencies_separate():
    html = totals_progress({'TWD': D('100'), 'USD': D('20')},
                           {'TWD': D('50'), 'USD': D('15')}, {'TWD': D('50'), 'USD': D('5')})
    assert 'TWD' in html and 'USD' in html and '50.0%' in html and '75.0%' in html


def test_removed_ads_only_explain_included_paid_verified_meta_rows():
    from copy import deepcopy
    from mori.budget_visuals import removed_ad_rows, removed_ad_count
    plans = [{'id': 'p', 'account_key': 'm', 'name': '林口'}]
    accounts = {'m': {'platform': 'meta', 'name': 'Meta 帳號'}}
    deleted = {'ad_id': '6994622466785', 'ad_name': '林口新開幕🔥/素材B',
               'current_status': 'ARCHIVED', 'names_verified': True,
               'spend_raw': '33.01', 'spend': 33, 'currency': 'TWD',
               'names_checked_at': '2026-11-23T14:00:00'}
    rows = [deleted, dict(deleted), dict(deleted, ad_id='2', current_status='DELETED'),
            dict(deleted, ad_id='3', current_status='PAUSED'),
            dict(deleted, ad_id='4', spend_raw='0'),
            dict(deleted, ad_id='5', names_verified=False),
            dict(deleted, ad_id='6', spend_raw='NaN'),
            dict(deleted, ad_id='7', spend_raw='-1')]
    results = {'p': {'rows': rows, 'since': '2026-04-29', 'until': '2026-07-27'}}
    before = deepcopy(results)
    items = removed_ad_rows(plans, accounts, results)
    assert removed_ad_count(items) == 2
    assert [r['API 狀態'] for r in items] == ['已封存', '已刪除']
    assert items[0]['已計入花費'] == D('33.01')
    assert items[0]['花費查詢起日'] == '2026-04-29'
    assert results == before
    assert not removed_ad_rows(plans, accounts, {'p': dict(results['p'], error='讀取失敗')})
    assert not removed_ad_rows(plans, {'m': {'platform': 'google'}}, results)
    assert not removed_ad_rows(plans, accounts, {})


def test_removed_ad_periods_remain_separate_but_badge_counts_unique_ads():
    from mori.budget_visuals import removed_ad_rows, removed_ad_count
    plans = [{'id': p, 'account_key': 'm', 'name': p} for p in ['a', 'b']]
    accounts = {'m': {'platform': 'meta', 'name': 'Meta'}}
    results = {p: {'rows': [{'ad_id': '1', 'current_status': 'DELETED', 'spend_raw': '33'}],
                   'since': '2026-04-29', 'until': '2026-05-28'} for p in ['a', 'b']}
    items = removed_ad_rows(plans, accounts, results)
    assert len(items) == 2
    assert removed_ad_count(items) == 1


def test_removed_ad_notice_ui_is_conditional_and_escapes_names():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
from decimal import Decimal
from mori.budget_ui import project_header, render_removed_ad_notice
show = st.checkbox('測試受影響專案')
items = [{'廣告帳號': 'Meta', '廣告 ID': '6994622466785',
          '廣告名稱': '<script>alert(1)</script>', 'API 狀態': '已封存',
          '已計入花費': Decimal('33')}] if show else []
st.markdown(project_header('林口', '已結案', '已結案', len(items)), unsafe_allow_html=True)
render_removed_ad_notice(items)
''').run()
    assert not app.exception
    assert not app.expander
    assert '含已刪除／封存廣告' not in '\n'.join(x.value for x in app.markdown)
    app.checkbox[0].check().run()
    assert not app.exception
    assert app.expander[0].label == '查看已刪除／封存廣告明細（1 則）'
    html = '\n'.join(x.value for x in app.markdown)
    assert '含已刪除／封存廣告 1 則' in html
    assert '6994622466785' in html and '<td>33</td>' in html
    assert '&lt;script&gt;' in html and '<script>' not in html
    assert any('不需再加一次' in x.value for x in app.caption)
