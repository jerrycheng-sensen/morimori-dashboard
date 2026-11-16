from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
from streamlit.testing.v1 import AppTest
from mori.storage import GitHubStore


def test_masked_form_saves_applies_and_platform_fields_switch():
    saved = {}
    def read(self, path, default=None):
        return saved.get(path, default), ('sha' if path in saved else None)
    def write(self, path, data, sha, **kwargs):
        saved[path] = data
        return 'sha'
    at = AppTest.from_file(str(Path(__file__).parents[1] / 'app.py'), default_timeout=20)
    at.secrets.update({'APP_PASSWORD': 'test-password-12345', 'STATE_REPO': 'owner/private',
                       'STATE_TOKEN': 'test-bootstrap', 'CREDENTIALS_KEY': Fernet.generate_key().decode()})
    with patch.object(GitHubStore, 'read', read), patch.object(GitHubStore, 'write', write):
        at.run()
        at.text_input[0].set_value('test-password-12345')
        at.button[0].click().run()
        at.radio[0].set_value('API 與權杖設定').run()
        assert not at.exception
        assert not any(w.label == 'Meta API 版本' for w in at.text_input)
        assert any('系統預設，免填' in d.value.to_string() for d in at.dataframe)
        token_field = next(w for w in at.text_input if w.label == 'Meta 廣告讀取權杖')
        assert token_field.proto.type == token_field.proto.PASSWORD
        token_field.set_value('secret-only-in-memory')
        next(b for b in at.button if b.label == '加密儲存並套用').click().run()
        assert not at.exception
        assert 'credentials.encrypted.json' in saved
        assert 'secret-only-in-memory' not in str(saved)
        token_field = next(w for w in at.text_input if w.label == 'Meta 廣告讀取權杖')
        assert token_field.value == ''
        assert any('加密表單' in d.value.to_string() for d in at.dataframe)
        at.radio[0].set_value('帳號與串接').run()
        assert not any('訂位轉換動作 ID' in w.label for w in at.text_input)
        at.selectbox(key='account_platform_新增帳號').set_value('google').run()
        assert not at.exception
        assert any('訂位轉換動作 ID' in w.label for w in at.text_input)
        assert not any('訂位事件代碼' in w.label for w in at.text_input)


def test_first_use_generates_one_stable_key_and_unlocks_after_deployment_setup():
    def panel():
        from mori.connection_ui import connection_panel
        connection_panel(None, {}, lambda key: "", [], False)
    at = AppTest.from_function(panel, default_timeout=15).run()
    assert not at.exception
    assert next(b for b in at.button if b.label == '加密儲存並套用').disabled
    at.button(key='generate_vault_key').click().run()
    assert not at.exception
    assert 'CREDENTIALS_KEY' in at.code[0].value
    first = at.code[0].value
    at.button(key='generate_vault_key').click().run()
    assert at.code[0].value == first
