import pandas as pd
import pytest

from mori.dashboard import filter_rows, summary_table, totals, trend_data


def rows():
    return pd.DataFrame([
        dict(account_key='m', platform='meta', date='2026-11-16', campaign_id='1', campaign_name='開幕 [A]',
             ad_name='永華店', channel='META', currency='TWD', spend=120., conversions=2., impressions=1000., clicks=10.),
        dict(account_key='g', platform='google', date='2026-11-16', campaign_id='1', campaign_name='開幕 [A]',
             ad_name='永華店', channel='SEARCH', currency='TWD', spend=60., conversions=1.5, impressions=500., clicks=5.)])


def test_summary_keeps_platforms_and_fractional_attribution_separate():
    result = summary_table(rows(), {'m': 'Meta帳號', 'g': 'Google帳號'})
    assert len(result) == 2
    meta = result[result['平台'] == 'Meta'].iloc[0]
    google = result[result['平台'] == 'Google Ads'].iloc[0]
    assert meta['訂位'] == 2 and meta['CPA'] == 60
    assert google['訂位'] == 1.5 and google['CPA'] == 40


def test_missing_conversion_does_not_become_zero_or_partial_total():
    data = rows()
    data.loc[1, 'conversions'] = None
    assert totals(data)['bookings'] is None
    assert totals(data)['cpa'] is None
    assert pd.isna(trend_data(data, 'conversions').iloc[0]['value'])
    assert totals(data)['spend'] == 180


def test_project_and_search_filters_are_literal_and_account_scoped():
    data = rows()
    project = {'account_key': 'm', 'match_field': 'ad_name', 'keyword': '永華'}
    result = filter_rows(data, project, '[A]', ['META', 'SEARCH'])
    assert result.account_key.tolist() == ['m']
    assert filter_rows(data, query='[').shape[0] == 2
    assert filter_rows(data, channels=[]).empty
    assert filter_rows(data, {**project, 'match_field': 'missing'}).empty
