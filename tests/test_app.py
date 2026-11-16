from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "app.py")


def test_live_app_without_password_opens_dashboard(monkeypatch):
    from unittest.mock import patch
    from mori.storage import GitHubStore
    from mori.core import default_settings
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    with patch.object(GitHubStore, "settings", return_value=(default_settings(), None)), patch.object(GitHubStore, "runtime", return_value=({"runs":[],"pending":[]}, None)), patch("mori.vault.resolve_credentials", return_value={}):
        app = AppTest.from_file(APP, default_timeout=15)
        app.secrets.update({"STATE_REPO":"owner/private", "STATE_TOKEN":"test-only"})
        app.run()
        assert not app.exception
        assert app.sidebar.radio
        assert not any(x.label == "管理密碼" for x in app.text_input)
        assert not any(x.label == "登出" for x in app.button)


def test_demo_all_pages_and_data_display(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    app = AppTest.from_file(APP, default_timeout=15).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert app.dataframe
    assert any("示範" in element.value for element in app.warning)
    for page in ["專案預算", "異常規則", "通知排程", "執行紀錄", "帳號與串接", "API 與權杖設定"]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page


def test_rule_save_selects_saved_rule_and_updates_in_place(monkeypatch):
    monkeypatch.setenv('DEMO_MODE', 'true')
    app = AppTest.from_file(APP, default_timeout=15).run()
    app.sidebar.radio[0].set_value('異常規則').run()
    next(x for x in app.text_input if x.label == '規則名稱').set_value('永華店開幕')
    next(x for x in app.checkbox if x.label == '啟用規則').check()
    next(x for x in app.text_input if x.label == '廣告名稱包含').set_value('永華店開幕')
    next(x for x in app.button if x.label == '儲存規則').click().run()
    assert not app.exception
    rules = app.session_state['demo_settings']['rules']
    assert len(rules) == 2
    saved = rules[-1]
    assert saved['enabled'] and saved['ad_filter'] == '永華店開幕'
    assert app.selectbox(key='rule_editor_choice').value == saved['id']
    assert any('永華店開幕' in x.value.to_string() for x in app.dataframe)
    next(x for x in app.text_input if x.label == '規則名稱').set_value('永華店開幕更新')
    next(x for x in app.button if x.label == '儲存規則').click().run()
    assert not app.exception
    assert len(app.session_state['demo_settings']['rules']) == 2
    assert app.session_state['demo_settings']['rules'][-1]['name'] == '永華店開幕更新'


def test_rule_delete_requires_confirmation_and_new_button_opens_empty_form(monkeypatch):
    monkeypatch.setenv('DEMO_MODE', 'true')
    app = AppTest.from_file(APP, default_timeout=15).run()
    app.sidebar.radio[0].set_value('異常規則').run()
    app.selectbox(key='rule_editor_choice').set_value('demo-rule').run()
    assert next(x for x in app.button if x.label == '刪除此規則').disabled
    next(x for x in app.checkbox if x.label == '確認刪除這筆已儲存規則').check().run()
    next(x for x in app.button if x.label == '刪除此規則').click().run()
    assert not app.exception
    assert app.session_state['demo_settings']['rules'] == []
    next(x for x in app.button if x.label == '＋新增規則').click().run()
    assert not app.exception
    assert app.selectbox(key='rule_editor_choice').value == '新增規則'
    assert next(x for x in app.text_input if x.label == '規則名稱').value == ''
