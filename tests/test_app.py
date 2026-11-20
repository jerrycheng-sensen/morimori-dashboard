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


def test_live_navigation_reuses_reads_and_only_execution_page_loads_runtime(monkeypatch):
    from unittest.mock import patch
    from mori.storage import GitHubStore
    from mori.core import default_settings
    monkeypatch.delenv('DEMO_MODE', raising=False)
    with patch.object(GitHubStore, 'settings', return_value=(default_settings(), 's')) as settings_read, \
         patch.object(GitHubStore, 'read', return_value=({}, None)) as vault_read, \
         patch.object(GitHubStore, 'runtime', return_value=({'runs': [], 'pending': []}, None)) as runtime_read:
        app = AppTest.from_file(APP, default_timeout=15)
        app.secrets.update({'STATE_REPO': 'owner/private', 'STATE_TOKEN': 'test-only', 'CREDENTIALS_KEY': ''})
        app.run()
        for page in ['通知排程', '專案預算', '異常規則', '帳號與串接']:
            app.sidebar.radio[0].set_value(page).run()
            assert not app.exception
        assert settings_read.call_count == 1
        assert vault_read.call_count == 1
        assert runtime_read.call_count == 0
        app.sidebar.radio[0].set_value('執行紀錄').run()
        assert runtime_read.call_count == 1
        next(x for x in app.button if x.label == '重新整理紀錄').click().run()
        assert runtime_read.call_count == 2
        next(x for x in app.sidebar.button if x.label == '重新載入設定').click().run()
        assert settings_read.call_count == 2
        assert vault_read.call_count == 2
        assert not app.exception


def test_budget_group_and_two_platform_plans_save_and_render_separate_progress(monkeypatch):
    from datetime import date
    monkeypatch.setenv('DEMO_MODE', 'true')
    app = AppTest.from_file(APP, default_timeout=15).run()
    app.sidebar.radio[0].set_value('專案預算').run()
    app.button(key='budget_nav_edit').click().run()
    next(x for x in app.text_input if x.label == '專案名稱').set_value('感謝祭')
    next(x for x in app.date_input if x.label == '專案開始日').set_value(date(2026,10,1))
    next(x for x in app.date_input if x.label == '專案結束日').set_value(date(2026,11,30))
    next(x for x in app.button if x.label == '儲存專案資料').click().run()
    assert not app.exception
    group = app.session_state['demo_settings']['project_groups'][0]
    next(x for x in app.selectbox if x.label == '所屬專案').select(group['id'])
    next(x for x in app.text_input if x.label == '平台計畫名稱').set_value('Meta含預熱')
    next(x for x in app.text_input if x.label == '名稱包含（必填）').set_value('示範')
    next(x for x in app.date_input if x.label == '廣告開始日（可含預熱）').set_value(date(2026,9,29))
    next(x for x in app.date_input if x.label == '廣告結束日').set_value(date(2026,11,18))
    next(x for x in app.number_input if x.label.startswith('平台投放預算')).set_value(100000.)
    next(x for x in app.button if x.label == '儲存平台計畫').click().run()
    assert not app.exception
    assert len(app.session_state['demo_settings']['projects']) == 1, [e.value for e in app.error]
    next(x for x in app.button if x.label == '＋新增平台計畫').click().run()
    next(x for x in app.selectbox if x.label == '所屬專案').select(group['id'])
    next(x for x in app.text_input if x.label == '名稱包含（必填）').set_value('示範')
    next(x for x in app.date_input if x.label == '廣告結束日').set_value(date(2026,11,18))
    next(x for x in app.text_input if x.label == '平台計畫名稱').set_value('Google')
    next(x for x in app.selectbox if x.label == '廣告帳號').select('demo_google').run()
    next(x for x in app.selectbox if x.label == '所屬專案').select(group['id'])
    next(x for x in app.text_input if x.label == '平台計畫名稱').set_value('Google')
    next(x for x in app.date_input if x.label == '廣告結束日').set_value(date(2026,11,18))
    next(x for x in app.text_input if x.label == '包含文字／廣告 ID 1').set_value('示範')
    next(x for x in app.date_input if x.label == '廣告開始日（可含預熱）').set_value(date(2026,10,1))
    next(x for x in app.button if x.label == '儲存平台計畫').click().run()
    assert not app.exception
    assert len(app.session_state['demo_settings']['projects']) == 2, [e.value for e in app.error]
    app.button(key='budget_nav_overview').click().run()
    next(x for x in app.button if x.label == '重新讀取').click().run()
    assert not app.exception
    assert len(app.session_state['budget_view']['results']) == 2
    assert sum(x.label == '花費進度' for x in app.metric) == 2
    saved = app.session_state['demo_settings']['projects'][0]
    app.button(key='budget_nav_edit').click().run()
    app.selectbox(key='budget_plan_editor').select(saved['id']).run()
    next(x for x in app.text_input if x.label == '平台計畫名稱').set_value('Meta已更新')
    next(x for x in app.button if x.label == '儲存平台計畫').click().run()
    assert not app.exception
    assert len(app.session_state['demo_settings']['projects']) == 2
    assert app.session_state['demo_settings']['projects'][0]['name'] == 'Meta已更新'


def test_budget_transfer_ui_posts_once_and_updates_both_cards(monkeypatch):
    from mori.core import default_settings
    from mori.budget_ledger import balance
    monkeypatch.setenv('DEMO_MODE', 'true')
    s = default_settings()
    s['accounts'] = [{'key':'demo_meta','platform':'meta','name':'Meta示範','account_id':'1','meta_action_type':'purchase'}]
    s['project_groups'] = [{'id':'source','name':'來源案','start':'2026-11-01','end':'2026-11-18','status':'進行中'},
                           {'id':'target','name':'接收案','start':'2026-11-01','end':'2026-11-30','status':'進行中'}]
    base = {'account_key':'demo_meta','keyword':'示範','start':'2026-11-18','end':'2026-11-18','status':'進行中'}
    s['projects'] = [{**base,'id':'a','name':'來源Meta','group_id':'source','budget':60000.},
                     {**base,'id':'b','name':'接收Meta','group_id':'target','budget':56000.}]
    app = AppTest.from_file(APP, default_timeout=15)
    app.session_state['demo_settings'] = s
    app.run()
    app.sidebar.radio[0].set_value('專案預算').run()
    next(x for x in app.button if x.label == '重新讀取').click().run()
    app.button(key='budget_nav_ledger').click().run()
    next(x for x in app.number_input if x.label == '轉移金額').set_value(36386.)
    next(x for x in app.text_input if x.label == '異動原因／用途').set_value('北部加強')
    next(x for x in app.checkbox if x.label.startswith('已核對相關專案')).check()
    next(x for x in app.button if x.label == '確認儲存預算異動').click().run()
    assert not app.exception
    updated = app.session_state['demo_settings']
    assert len(updated['budget_transactions']) == 1, [x.value for x in app.error]
    assert balance(updated,'a')['adjusted'] == 23614
    assert balance(updated,'b')['adjusted'] == 92386
    assert any('來源案' in x.value.to_string() and '接收案' in x.value.to_string() for x in app.dataframe)
    assert app.session_state['budget_view']['results']['a']['spend'] == 1200
    app.button(key='budget_nav_overview').click().run()
    assert any(x.label == '可用預算' and x.value == '92,386.00' for x in app.metric)
    app.button(key='budget_nav_edit').click().run()
    assert next(x for x in app.number_input if x.label.startswith('平台投放預算')).disabled is False  # new-plan editor
    # Reversal appends a second record and returns both balances.
    app.button(key='budget_nav_ledger').click().run()
    next(x for x in app.radio if x.label == '異動方式').set_value('沖回紀錄').run()
    next(x for x in app.text_input if x.label == '異動原因／用途').set_value('測試沖回')
    next(x for x in app.checkbox if x.label.startswith('已核對相關專案')).check()
    next(x for x in app.button if x.label == '確認儲存預算異動').click().run()
    assert not app.exception
    updated = app.session_state['demo_settings']
    assert len(updated['budget_transactions']) == 2
    assert balance(updated,'a')['adjusted'] == 60000 and balance(updated,'b')['adjusted'] == 56000


def test_budget_initial_load_only_until_manual_read_even_after_navigation_or_elapsed_time(monkeypatch):
    from datetime import datetime, timedelta
    from mori.core import default_settings, TAIPEI
    import mori.budget_ui as ui
    monkeypatch.setenv('DEMO_MODE','true')
    original = ui.collect_spend
    calls = []
    def spy(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(ui,'collect_spend',spy)
    s = default_settings()
    s['accounts'] = [{'key':'demo_meta','name':'Meta','platform':'meta','account_id':'1','meta_action_type':'purchase'}]
    s['project_groups'] = [{'id':'f','name':'感謝祭','start':'2026-10-01','end':'2026-11-30','status':'已結案'}]
    s['projects'] = [{'id':'p','name':'Meta','group_id':'f','account_key':'demo_meta','budget':56000,
                      'start':'2026-11-18','end':'2026-11-18','keyword':'示範','status':'已結案'}]
    app = AppTest.from_file(APP,default_timeout=15)
    app.session_state['demo_settings'] = s
    app.run()
    app.sidebar.radio[0].set_value('專案預算').run()
    assert not app.exception and len(calls) == 1
    assert app.session_state['budget_view']['results']['p']['spend'] == 1200
    assert any(x.label == '累計花費' and x.value == '1,200.00' for x in app.metric)
    # Fragment-only filters must not read the API on every click.
    app.selectbox(key='budget_state_filter').set_value('進行中').run()
    assert not app.exception and len(calls) == 1
    app.sidebar.radio[0].set_value('數據總覽').run()
    app.sidebar.radio[0].set_value('專案預算').run()
    assert not app.exception and len(calls) == 1
    view = dict(app.session_state['budget_view'])
    view['requested_at'] = (datetime.now(TAIPEI) - timedelta(seconds=61)).isoformat()
    app.session_state['budget_view'] = view
    app.run()
    assert not app.exception and len(calls) == 1
    next(x for x in app.button if x.label == '重新讀取').click().run()
    assert not app.exception and len(calls) == 2


def test_project_rail_switch_search_year_and_status_reuse_spend(monkeypatch):
    import mori.budget_ui as ui
    from mori.core import default_settings
    monkeypatch.setenv('DEMO_MODE', 'true')
    original = ui.collect_spend
    calls = []
    def spy(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(ui, 'collect_spend', spy)
    settings = default_settings()
    settings['accounts'] = [{'key': 'demo_meta', 'name': 'Meta', 'platform': 'meta', 'account_id': '1'}]
    settings['project_groups'] = [
        {'id': 'f', 'name': '感謝祭第5彈', 'start': '2026-10-01', 'end': '2026-11-30', 'status': '進行中'},
        {'id': 'l', 'name': '林口開幕', 'start': '2026-04-01', 'end': '2026-07-31', 'status': '已結案'},
        {'id': 'old', 'name': '去年專案', 'start': '2025-01-01', 'end': '2025-01-31', 'status': '已結案'}]
    settings['projects'] = [{'id': 'p', 'group_id': 'f', 'name': 'Meta', 'account_key': 'demo_meta',
                             'start': '2026-11-18', 'end': '2026-11-18', 'budget': 10000, 'keyword': '示範'}]
    app = AppTest.from_file(APP, default_timeout=15)
    app.session_state['demo_settings'] = settings
    app.run()
    app.sidebar.radio[0].set_value('專案預算').run()
    assert not app.exception and len(calls) == 1
    app.selectbox(key='budget_nav_year').set_value(2026).run()
    app.button(key='budget_project_group:l').click().run()
    assert not app.exception and app.session_state['budget_selected_project'] == 'group:l'
    headings = [x.value for x in app.markdown if 'class="project-name"' in x.value]
    assert len(headings) == 1 and '林口開幕' in headings[0]
    app.text_input(key='budget_nav_search').set_value('感謝祭').run()
    assert not app.exception and app.session_state['budget_selected_project'] == 'all'
    assert any('感謝祭第5彈' in x.value for x in app.markdown if 'class="project-name"' in x.value)
    app.text_input(key='budget_nav_search').set_value('無此專案').run()
    assert any('找不到符合' in x.value for x in app.info)
    app.text_input(key='budget_nav_search').set_value('').run()
    app.selectbox(key='budget_nav_year').set_value(2025).run()
    assert any('去年專案' in x.value for x in app.markdown if 'class="project-name"' in x.value)
    assert len(calls) == 1
