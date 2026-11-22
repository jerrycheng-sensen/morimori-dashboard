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
