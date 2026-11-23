import copy
from datetime import datetime, date

import pytest

from mori.budget_ledger import (adjustment, balance, protect_history, reverse,
                                transfer, validate_ledger, correct_transfer, transfer_amount)
from mori.budgets import plan_summary, save_plan
from mori.core import AppError, TAIPEI, default_settings, validate_settings

NOW = datetime(2026, 11, 20, 10, tzinfo=TAIPEI)


def fixture():
    s = default_settings()
    s['accounts'] = [{'key': 'm', 'name': 'Meta', 'platform': 'meta', 'account_id': '1'}]
    s['project_groups'] = [dict(id='linkou', name='林口開幕', start='2026-05-11', end='2026-06-30', status='已結案'),
                           dict(id='festival', name='感謝祭', start='2026-10-01', end='2026-11-30', status='進行中')]
    base = dict(account_key='m', keyword='案', start='2026-05-11', end='2026-11-18', status='進行中')
    s['projects'] = [dict(base, id='a', name='林口Meta', group_id='linkou', budget=60000),
                     dict(base, id='b', name='感謝祭Meta', group_id='festival', budget=56000)]
    results = {key: dict(currency='TWD', spend=value, until='2026-11-18') for key, value in [('a',23614), ('b',50000)]}
    return s, results


def posted():
    s,r = fixture()
    return transfer(s,'a','b',36386,'2026-11-20','北部加強',r,'t1',NOW), r


def test_paired_transfer_conserves_money_and_preserves_original_budget_and_direction():
    s,r = posted()
    assert balance(s,'a')['adjusted'] == 23614
    assert balance(s,'b')['adjusted'] == 92386
    assert sum(balance(s,k)['adjusted'] for k in ['a','b']) == 116000
    assert [p['budget'] for p in s['projects']] == [60000,56000]
    record = s['budget_transactions'][0]
    assert '林口開幕' in record['source_label'] and '感謝祭' in record['target_label']
    assert record['reason'] == '北部加強'
    assert plan_summary(s['projects'][1],r['b'],date(2026,11,20),s)['budget'] == 92386


def test_reverse_restores_both_budgets_without_deleting_original_and_cannot_repeat():
    s,r = posted()
    undone = reverse(s,'t1','誤植沖回',r,'r1',NOW)
    assert len(undone['budget_transactions']) == 2
    assert balance(undone,'a')['adjusted'] == 60000 and balance(undone,'b')['adjusted'] == 56000
    assert undone['budget_transactions'][1]['source_label'] == s['budget_transactions'][0]['target_label']
    with pytest.raises(AppError,match='再次沖回'):
        reverse(undone,'t1','again',r,now=NOW)
    r['b']['spend'] = 60000
    with pytest.raises(AppError,match='小於已發生花費'):
        reverse(s,'t1','spent',r,now=NOW)


def test_insufficient_failed_mismatched_currency_duplicate_and_future_transfers_rejected():
    s,r = fixture()
    with pytest.raises(AppError,match='超過來源'):
        transfer(s,'a','b',36386.01,'2026-11-20','用途',r,now=NOW)
    with pytest.raises(AppError,match='不能相同'):
        transfer(s,'a','a',1,'2026-11-20','用途',r,now=NOW)
    with pytest.raises(AppError,match='成功讀取'):
        transfer(s,'a','b',1,'2026-11-20','用途',{'a':{'error':'offline'}},now=NOW)
    r2=copy.deepcopy(r);r2['b']['currency']='USD'
    with pytest.raises(AppError,match='幣別不同'):
        transfer(s,'a','b',1,'2026-11-20','用途',r2,now=NOW)
    with pytest.raises(AppError,match='未來'):
        transfer(s,'a','b',1,'2026-11-21','用途',r,now=NOW)
    saved=transfer(s,'a','b',1,'2026-11-20','用途',r,'one',NOW)
    with pytest.raises(AppError,match='重複送出'):
        transfer(saved,'a','b',1,'2026-11-20','用途',r,'one',NOW)


def test_micro_costs_retained_for_available_balance_check():
    s,r=fixture();r['a']['spend']=23614.000001
    with pytest.raises(AppError,match='超過來源'):
        transfer(s,'a','b',36386,'2026-11-20','用途',r,now=NOW)
    saved=transfer(s,'a','b',36385.99,'2026-11-20','用途',r,now=NOW)
    assert balance(saved,'a')['adjusted'] == 23614.01


def test_append_only_and_original_budget_lock_with_rename_audit_snapshot():
    s,r=posted()
    changed=copy.deepcopy(s);changed['budget_transactions'][0]['amount']=1
    with pytest.raises(AppError,match='不可覆寫'):
        protect_history(s,changed)
    with pytest.raises(AppError,match='原始預算'):
        save_plan(s,{**s['projects'][0],'budget':50000})
    renamed=save_plan(s,{**s['projects'][0],'name':'林口改名'})
    assert renamed['budget_transactions'][0]['source_label'] == s['budget_transactions'][0]['source_label']
    invalid=copy.deepcopy(s);invalid['projects']=invalid['projects'][1:]
    with pytest.raises(AppError,match='計畫不存在'):
        validate_settings(invalid)


def test_adjustment_reversal_and_invalid_reversal_effects():
    s,r=fixture()
    added=adjustment(s,'b',1000,'2026-11-20','追加',r,'add',NOW)
    assert balance(added,'b')['adjusted'] == 57000
    restored=reverse(added,'add','沖回追加',r,'undo',NOW)
    assert balance(restored,'b')['adjusted'] == 56000
    wrong=copy.deepcopy(restored);wrong['budget_transactions'][1]['effects']['b']=-1
    with pytest.raises(AppError,match='完整抵銷'):
        validate_ledger(wrong)
    with pytest.raises(AppError,match='小於已發生花費'):
        adjustment(s,'b',-7000,'2026-11-20','減列',r,now=NOW)


def test_correct_transfer_preserves_history_conserves_total_and_allows_real_overrun():
    s,r=posted(); original=copy.deepcopy(s)
    r['a']['spend']=25872; r['b']['spend']=92166
    fixed=correct_transfer(s,'t1',34128,'補列歷史花費，修正轉出結餘',r,'fix',NOW,expected_amount=36386)
    assert fixed['budget_transactions'][0]==original['budget_transactions'][0]
    assert s==original and len(fixed['budget_transactions'])==2
    protect_history(s,fixed)
    assert balance(fixed,'a')['adjusted']==25872
    assert balance(fixed,'b')['adjusted']==90128
    assert balance(fixed,'a')['outgoing']==34128 and balance(fixed,'a')['incoming']==0
    assert balance(fixed,'b')['incoming']==34128
    assert sum(balance(fixed,k)['adjusted'] for k in ('a','b'))==116000
    assert plan_summary(fixed['projects'][1],r['b'],date(2026,11,20),fixed)['remaining']==-2038
    assert r['a']['spend']==25872 and r['b']['spend']==92166
    assert balance(fixed,'a',date(2026,11,19))['adjusted']==60000


def test_repeated_correction_and_cancel_use_current_total_without_double_application():
    s,r=posted()
    fixed=correct_transfer(s,'t1',34128,'第一次',r,'fix1',NOW)
    again=correct_transfer(fixed,'t1',34000,'第二次',r,'fix2',NOW,expected_amount=34128)
    assert transfer_amount(again,'t1')==34000 and balance(again,'a')['outgoing']==34000
    with pytest.raises(AppError,match='已被修正'):
        correct_transfer(again,'t1',33000,'舊畫面',r,now=NOW,expected_amount=36386)
    cancelled=correct_transfer(again,'t1',0,'取消原轉移',r,'fix3',NOW)
    assert balance(cancelled,'a')['adjusted']==60000 and balance(cancelled,'b')['adjusted']==56000
    with pytest.raises(AppError,match='已有修正'):
        reverse(again,'t1','不可沖回舊金額',r,now=NOW)


@pytest.mark.parametrize('patch', [
    {'effects':{'a':2259,'b':-2258}}, {'previous_amount':36000}, {'source_id':'b'},
    {'target_id':'a'}, {'currency':'USD'}, {'corrects':'missing'},
    {'effective_on':'2026-11-19'}, {'amount':-1},
])
def test_transfer_correction_rejects_tampered_history(patch):
    s,r=posted(); fixed=correct_transfer(s,'t1',34128,'修正',r,'fix',NOW)
    fixed['budget_transactions'][-1].update(patch)
    with pytest.raises(AppError):
        validate_ledger(fixed)


def test_correction_checks_read_currency_amount_and_reversed_records():
    s,r=posted()
    with pytest.raises(AppError,match='成功讀取'):
        correct_transfer(s,'t1',34128,'修正',{'a':{'error':'offline'}},now=NOW)
    wrong=copy.deepcopy(r);wrong['b']['currency']='USD'
    with pytest.raises(AppError,match='幣別'):
        correct_transfer(s,'t1',34128,'修正',wrong,now=NOW)
    for amount in (-1,36386):
        with pytest.raises(AppError):correct_transfer(s,'t1',amount,'修正',r,now=NOW)
    with pytest.raises(AppError,match='小於零'):
        correct_transfer(s,'t1',70000,'轉出超過全部預算',r,now=NOW)
    undone=reverse(s,'t1','沖回',r,'undo',NOW)
    with pytest.raises(AppError,match='尚未沖回'):
        correct_transfer(undone,'t1',34128,'修正',r,now=NOW)


def test_transfer_correction_ui_previews_and_saves_once_without_mutating_costs(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import mori.budget_ledger_ui as ui
    s,r=posted();r['a']['spend']=25872;r['b']['spend']=92166
    calls=[]
    def collect(*args):
        calls.append(True)
        return copy.deepcopy(r)
    monkeypatch.setattr(ui,'collect_spend',collect)
    app=AppTest.from_string("""
import streamlit as st
from mori.budget_ledger_ui import render_ledger

def persist(value, **kwargs):
    st.session_state['settings']=value
render_ledger(st.session_state['settings'], None, persist)
""",default_timeout=15)
    app.session_state['settings']=s
    app.session_state['budget_view']={'key':'fixture','date':'2026-11-20','results':r}
    app.run()
    app.radio(key='budget_tx_kind').set_value('修正轉移金額').run()
    assert not app.exception and not calls
    next(x for x in app.number_input if x.label=='正確的轉移總額').set_value(34128.).run()
    captions=' '.join(x.value for x in list(app.caption) + list(app.markdown))
    assert '90,128' in captions and '-2,038' in captions and not calls
    next(x for x in app.text_input if x.label=='異動原因／用途').set_value('林口補認列歷史花費，修正轉出額')
    next(x for x in app.checkbox if x.label.startswith('已核對相關專案')).check()
    next(x for x in app.button if x.label=='確認儲存預算異動').click().run()
    assert not app.exception and len(calls)==1
    fixed=app.session_state['settings']
    assert len(fixed['budget_transactions'])==2 and balance(fixed,'b')['adjusted']==90128
    app.run()
    assert len(app.session_state['settings']['budget_transactions'])==2
    assert r['b']['spend']==92166
