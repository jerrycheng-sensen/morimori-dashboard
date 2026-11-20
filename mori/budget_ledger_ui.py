"""Budget transfers, adjustments and traceable reversals inside project cards."""
from datetime import datetime
import uuid

import pandas as pd
import streamlit as st

from mori.budget_ledger import adjustment, balance, plan_label, reverse, transfer
from mori.budgets import collect_spend, configuration_key
from mori.core import AppError, TAIPEI


def records(settings, plan_id=None):
    from mori.budget_ledger import impacts
    entries = settings.get('budget_transactions', [])
    reversed_ids = {t.get('reverses') for t in entries if t['kind'] == 'reversal'}
    rows = []
    for t in reversed(entries):
        if plan_id and plan_id not in impacts(t):
            continue
        kind = {'transfer': '預算轉移', 'adjustment': '追加／減列', 'reversal': '沖回'}[t['kind']]
        rows.append({'異動編號': t['id'], '生效日': t['effective_on'], '建立時間': t['created_at'],
                     '類型': kind, '來源專案／平台': t.get('source_label', ''),
                     '接收專案／平台': t.get('target_label', ''), '金額': t['amount'], '幣別': t['currency'],
                     '本計畫增減': float(impacts(t).get(plan_id, 0)) if plan_id else None,
                     '用途／原因': t['reason'], '狀態': '已沖回' if t['id'] in reversed_ids else '已入帳',
                     '對應原紀錄': t.get('reverses', ''), '來源花費資料迄日': t.get('source_data_until') or ''})
    df = pd.DataFrame(rows)
    if not df.empty:
        first = ['生效日', '類型', '來源專案／平台', '接收專案／平台', '金額', '幣別', '用途／原因', '狀態']
        df = df[first + [c for c in df if c not in first]]
    return df


def render_ledger(settings, fetch, persist):
    plans = {p['id']: p for p in settings['projects']}
    accounts = {a['key']: a for a in settings['accounts']}
    today = datetime.now(TAIPEI).date()
    st.subheader('預算調動與異動紀錄')
    st.caption('內部預算分配記帳；不會修改 Meta／Google 日預算，也不代表儲值餘額或資金匯款。原始紀錄保留，錯誤以沖回處理。')
    entries = settings.get('budget_transactions', [])
    op = st.session_state.setdefault('budget_tx_operation', uuid.uuid4().hex)
    if any(t['id'] == op for t in entries):
        op = uuid.uuid4().hex
        st.session_state.budget_tx_operation = op
    if not plans:
        st.info('請先建立平台投放計畫，再進行預算異動。')
        return
    kind = st.radio('異動方式', ['轉移預算', '追加／減列', '沖回紀錄'], horizontal=True, key='budget_tx_kind')
    label = lambda key: plan_label(settings, key)
    source_id = target_id = entry_id = None
    if kind == '轉移預算':
        if len(plans) < 2:
            st.info('轉移至少需要兩個平台計畫。')
        else:
            c1, c2 = st.columns(2)
            source_id = c1.selectbox('從哪個專案／平台轉出', list(plans), format_func=label, key='budget_tx_source')
            target_id = c2.selectbox('轉入哪個專案／平台', [k for k in plans if k != source_id], format_func=label, key='budget_tx_target')
            a, b = st.columns(2)
            a.metric('來源調整後預算', f"{balance(settings, source_id)['adjusted']:,.2f}")
            b.metric('接收調整後預算', f"{balance(settings, target_id)['adjusted']:,.2f}")
    elif kind == '追加／減列':
        target_id = st.selectbox('異動的專案／平台', list(plans), format_func=label, key='budget_adjust_target')
    else:
        undone = {t.get('reverses') for t in entries}
        options = [t['id'] for t in entries if t['kind'] != 'reversal' and t['id'] not in undone]
        if options:
            def entry_label(key):
                t = next(t for t in entries if t['id'] == key)
                return f"{t['effective_on']}｜{t.get('source_label', '')} → {t.get('target_label', '')}｜{t['currency']} {t['amount']:,.2f}｜{t['reason']}"
            entry_id = st.selectbox('選擇要沖回的原紀錄', options, format_func=entry_label, key='budget_reverse_entry')
        else:
            st.info('目前沒有可沖回的異動。')
    ready = bool((source_id and target_id) or (kind == '追加／減列' and target_id) or entry_id)
    if ready:
        with st.form('budget_transaction_' + kind):
            amount = st.number_input('異動金額（追加為正、減列為負）' if kind == '追加／減列' else '轉移金額',
                                     min_value=None if kind == '追加／減列' else 0., value=0., step=100., format='%.2f') if kind != '沖回紀錄' else None
            effective = st.date_input('生效日期', today, max_value=today) if kind != '沖回紀錄' else today
            reason = st.text_input('異動原因／用途', placeholder='例如：林口結餘轉供感謝祭北部加強')
            confirmed = st.checkbox('已核對相關專案的廣告歸類；確認儲存這筆預算異動')
            st.caption('送出時會重新讀取相關計畫花費並檢核結餘。資料截至昨天；仍在投放的計畫可能另有今天尚未入帳的花費。')
            if st.form_submit_button('確認儲存預算異動'):
                try:
                    if not confirmed:
                        raise AppError('請先勾選已核對相關專案與廣告歸類。')
                    if kind == '沖回紀錄':
                        from mori.budget_ledger import impacts
                        old = next(t for t in entries if t['id'] == entry_id)
                        ids = list(impacts(old))
                    else:
                        ids = [k for k in [source_id, target_id] if k]
                    with st.spinner('核對花費並準備儲存預算異動…'):
                        results = collect_spend(list(plans.values()), accounts, fetch, today)
                        if kind == '轉移預算':
                            updated = transfer(settings, source_id, target_id, amount, effective, reason, results, op)
                        elif kind == '追加／減列':
                            updated = adjustment(settings, target_id, amount, effective, reason, results, op)
                        else:
                            updated = reverse(settings, entry_id, reason, results, op)
                        # Reuse fresh expense snapshots after both budgets update atomically.
                        view = st.session_state.get('budget_view')
                        if view and view['key'] == configuration_key(settings) and view['date'] == str(today):
                            view['results'].update(results)
                            view['at'] = datetime.now(TAIPEI).isoformat()
                        persist(updated, notice='預算異動已入帳，來源與接收計畫已同步更新。', keep_budget_view=True)
                except (AppError, ValueError) as exc:
                    st.error(str(exc))
    st.subheader('完整異動紀錄')
    selected = st.selectbox('依專案／平台查紀錄', ['all'] + list(plans),
                            format_func=lambda k: '全部紀錄' if k == 'all' else label(k), key='budget_ledger_filter')
    df = records(settings, None if selected == 'all' else selected)
    if df.empty:
        st.info('尚無預算異動紀錄。')
    else:
        st.dataframe(df, hide_index=True, width='stretch')
        st.download_button('下載預算異動紀錄 CSV', df.to_csv(index=False).encode('utf-8-sig'),
                           'mori-budget-ledger.csv', on_click='ignore')
