from decimal import Decimal
from mori.money_display import money_text, money_html, money_metric, plan_platform


def test_platform_precision_is_only_presentation_and_preserves_raw_amount():
    raw = Decimal('143479.535')
    assert money_text(raw, 'meta') == '$143,480'
    assert money_text(raw, 'google') == '$143,479.54'
    assert money_text(raw) == '$143,479.54'
    assert raw == Decimal('143479.535')
    assert money_text(Decimal('-0.1'), 'meta') == '$0'
    assert money_text(Decimal('-23.615'), 'google') == '$-23.62'
    assert money_text(None, 'meta') == '—'


def test_google_and_combined_fraction_has_separate_markup_meta_has_none():
    assert money_html('92166', 'meta') == '$92,166'
    assert money_html('143479.53', 'google') == '$143,479<span class="mori-money-fraction">.53</span>'
    assert '.00</span>' in money_html('538333')
    assert 'fraction' not in money_html('236000', 'meta')


def test_plan_platform_uses_account_identity_not_name():
    settings = {'accounts':[{'key':'m','platform':'meta'},{'key':'g','platform':'google'}],
                'projects':[{'id':'1','name':'Google字樣的Meta案','account_key':'m'},
                            {'id':'2','name':'Meta字樣的Google案','account_key':'g'}]}
    assert plan_platform(settings, '1') == 'meta'
    assert plan_platform(settings, '2') == 'google'


def test_money_metrics_have_one_symbol_and_no_currency_prefix():
    class Target:
        def markdown(self, content, **kwargs):
            self.html = content
    target = Target()
    money_metric(target, '花費', 100, 'google', prefix='TWD ')
    assert 'TWD' not in target.html
    assert '<div class="mori-money-value">$100' in target.html
    assert '$$' not in target.html
    money_metric(target, '花費', None, 'meta', prefix='TWD ')
    assert '<div class="mori-money-value">—</div>' in target.html


def test_sortable_table_formats_money_without_changing_values_or_counts():
    import pandas as pd
    from mori.money_display import styled_money_frame
    frame = pd.DataFrame({'花費': [1234.5, 1234.5], '點擊': [12, 34]})
    styled = styled_money_frame(frame, {'花費'}, ['meta', 'google'])
    html = styled.to_html()
    assert '$1,235' in html and '$1,234.50' in html
    assert styled.data.equals(frame) and frame['花費'].tolist() == [1234.5, 1234.5]
    raw = styled_money_frame(pd.DataFrame({'差額': ['0.000001']}), {'差額'}, raw=True)
    assert '$0.000001' in raw.to_html()
