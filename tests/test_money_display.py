from decimal import Decimal
from mori.money_display import money_text, money_html, money_metric, plan_platform


def test_platform_precision_is_only_presentation_and_preserves_raw_amount():
    raw = Decimal('143479.535')
    assert money_text(raw, 'meta') == '143,480'
    assert money_text(raw, 'google') == '143,479.54'
    assert money_text(raw) == '143,479.54'
    assert raw == Decimal('143479.535')
    assert money_text(Decimal('-0.1'), 'meta') == '0'
    assert money_text(Decimal('-23.615'), 'google') == '-23.62'
    assert money_text(None, 'meta') == '—'


def test_google_and_combined_fraction_has_separate_markup_meta_has_none():
    assert money_html('92166', 'meta') == '92,166'
    assert money_html('143479.53', 'google') == '143,479<span class="mori-money-fraction">.53</span>'
    assert '.00</span>' in money_html('538333')
    assert 'fraction' not in money_html('236000', 'meta')


def test_plan_platform_uses_account_identity_not_name():
    settings = {'accounts':[{'key':'m','platform':'meta'},{'key':'g','platform':'google'}],
                'projects':[{'id':'1','name':'Google字樣的Meta案','account_key':'m'},
                            {'id':'2','name':'Meta字樣的Google案','account_key':'g'}]}
    assert plan_platform(settings, '1') == 'meta'
    assert plan_platform(settings, '2') == 'google'
