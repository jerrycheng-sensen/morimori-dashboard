from copy import deepcopy
from datetime import date,datetime
from decimal import Decimal
from mori.design_system import page_header,insight_card,history_card
from mori.festival_model import source_signature,fit_projects
from mori.invoices import DemoInvoiceStore
from mori.core import TAIPEI


def test_dynamic_presentation_escapes_names_and_preserves_money_conventions():
    name='<img src=x onerror=alert(1)>'
    assert '<img' not in page_header(name,name) and '&lt;img' in page_header(name,name)
    card=insight_card(name,Decimal('12345.67'),name,focus=True)
    assert '<img' not in card and '$12,345<span class="mori-money-fraction">.67</span>' in card
    p={'name':name,'ad_start':'2026-10-01','ad_end':'2026-11-18','spend':'12345.67','bookings':'10'}
    before=deepcopy(p)
    assert '&lt;img' in history_card(p,'01') and p==before


def test_model_controls_are_local_until_settings_save():
    from streamlit.testing.v1 import AppTest
    from test_festival_model import settings,synthetic
    from mori.festival_model import collect_projects
    from test_festival_model import Provider
    s=settings();before=deepcopy(s)
    projects=collect_projects(s,lambda _:Provider(),datetime(2026,11,27,tzinfo=TAIPEI))
    for p,data in zip(projects,synthetic()): p['rows']=data['rows']
    snapshot={'source_signature':source_signature(s),'updated_at':'2026-11-27T09:15:00+08:00','projects':projects,'fit':fit_projects(projects,date(2026,11,23))}
    app=AppTest.from_string('''
import streamlit as st
from mori.festival_ui import render_festival_model
from mori.invoices import DemoInvoiceStore
store=DemoInvoiceStore();store.write('festival-model.json',st.session_state.snapshot,None)
def persist(updated,**kw): st.session_state.saved=updated
def no_fetch(*a): raise AssertionError('檢視不能重新查 API')
render_festival_model(st.session_state.config,store,no_fetch,persist)
''',default_timeout=15)
    app.session_state.config=s;app.session_state.snapshot=snapshot
    app.run()
    assert not app.exception
    assert all(not e.proto.expanded for e in app.expander)
    app.selectbox(key='festival_reference').select('1').run()
    app.radio(key='festival_curve').set_value('邊際 CPA').run()
    assert not app.exception and 'saved' not in app.session_state
    assert not any('成本' in e.label for e in app.number_input)
    app.checkbox(key='festival_enabled').uncheck()
    app.button(key='festival_save_sources').click().run()
    assert not app.exception and app.session_state.saved['festival_model']['enabled'] is False
    assert 'target_cpa' not in app.session_state.saved['festival_model']
    assert app.session_state.saved['projects']==before['projects']
    assert app.session_state.config==before and app.session_state.snapshot==snapshot
