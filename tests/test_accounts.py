import copy

import pytest
from streamlit.testing.v1 import AppTest
from pathlib import Path
from mori.accounts import account_label, delete_account, save_account
from mori.core import AppError, default_settings


def config():
    s = default_settings()
    s['accounts'] = [
        {'key':'a', 'name':'Google', 'platform':'google', 'account_id':'4251349845', 'google_action_ids':[]},
        {'key':'b', 'name':'Google', 'platform':'google', 'account_id':'4251349845', 'google_action_ids':['7904692700']},
        {'key':'m', 'name':'Meta', 'platform':'meta', 'account_id':'955367110809428', 'meta_action_type':''},
    ]
    return s


def test_edit_legacy_duplicate_preserves_key_order_and_other_fields():
    s = config(); before = copy.deepcopy(s)
    updated = save_account(s, {**s['accounts'][0], 'google_action_ids':['7904692700']})
    assert [a['key'] for a in updated['accounts']] == ['a','b','m']
    assert updated['accounts'][0]['google_action_ids'] == ['7904692700']
    assert updated['accounts'][1:] == s['accounts'][1:]
    assert s == before
    assert account_label(s['accounts'][0]) != account_label(s['accounts'][1])


@pytest.mark.parametrize('platform,aid', [('google','425-134-9845'),('meta','act_955367110809428')])
def test_duplicate_creation_rejected_after_normalizing(platform, aid):
    with pytest.raises(AppError, match='已存在'):
        save_account(config(), {'key':'new','name':'Duplicate','platform':platform,'account_id':aid})


def test_delete_or_transfer_dependencies_without_losing_rules():
    s = config()
    s['rules'] = [{'id':'r','name':'CPA','account_key':'a','level':'campaign','period_days':1,
                   'minimum_spend':1000,'cpa_threshold':50}]
    before = copy.deepcopy(s)
    with pytest.raises(AppError, match='移轉'):
        delete_account(s, 'a')
    with pytest.raises(AppError):
        delete_account(s, 'a', 'm')
    with pytest.raises(AppError):
        save_account(s, {**s['accounts'][0], 'account_id':'9999999999'})
    result = delete_account(s, 'a', 'b')
    assert [a['key'] for a in result['accounts']] == ['b','m']
    assert result['rules'] == [{**s['rules'][0], 'account_key':'b'}]
    assert result['schedule'] == s['schedule']
    assert s == before


def test_app_can_edit_meta_select_duplicate_google_and_delete_it(monkeypatch):
    monkeypatch.setenv('DEMO_MODE', 'true')
    app = AppTest.from_file(str(Path(__file__).parents[1] / 'app.py'), default_timeout=15).run()
    app.session_state['demo_settings'] = config()
    app.sidebar.radio[0].set_value('帳號與串接').run()
    assert not app.exception
    # Existing selector is explicit; duplicate names remain distinguishable.
    select = next(x for x in app.selectbox if x.label == '選擇要編輯的帳號')
    select.set_value('m').run()
    next(x for x in app.text_input if x.label.startswith('訂位事件代碼')).set_value('offsite_conversion.fb_pixel_purchase')
    next(x for x in app.button if x.label == '更新此帳號').click().run()
    assert not app.exception
    assert len(app.session_state['demo_settings']['accounts']) == 3
    assert app.session_state['demo_settings']['accounts'][2]['meta_action_type'] == 'offsite_conversion.fb_pixel_purchase'
    next(x for x in app.selectbox if x.label == '選擇要編輯的帳號').set_value('a').run()
    assert next(x for x in app.text_input if x.label.startswith('訂位轉換動作 ID')).value == ''
    next(x for x in app.checkbox if x.label == '確認刪除上述帳號設定').check().run()
    next(x for x in app.button if x.label == '刪除此帳號設定').click().run()
    assert not app.exception
    assert [a['key'] for a in app.session_state['demo_settings']['accounts']] == ['b','m']
