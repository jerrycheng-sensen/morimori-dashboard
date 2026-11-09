from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "app.py")


def test_live_app_without_password_stops_before_any_api(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    app = AppTest.from_file(APP).run()
    assert not app.exception
    assert "APP_PASSWORD" in app.info[0].value
    assert not app.sidebar.radio


def test_password_gate(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass1")
    app = AppTest.from_file(APP).run()
    assert not app.exception
    assert app.text_input[0].label == "管理密碼"
    assert not app.sidebar.radio
    app.text_input[0].set_value("wrong")
    app.button[0].click().run()
    assert app.error[0].value == "密碼不正確。"


def test_demo_all_pages_and_data_display(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    app = AppTest.from_file(APP, default_timeout=15).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert app.dataframe
    assert any("示範" in element.value for element in app.warning)
    for page in ["專案預算", "異常規則", "通知排程", "執行紀錄", "帳號與串接"]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page


def test_password_under_ten_characters_is_rejected(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "short1234")
    app = AppTest.from_file(APP).run()
    assert not app.exception
    assert "至少 10 個字元" in app.info[0].value
    assert not app.text_input
