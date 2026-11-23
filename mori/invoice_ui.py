"""Invoice registration and per-platform evidence status, using native controls."""
import html
import uuid
from datetime import datetime
from decimal import Decimal

import pandas as pd
import streamlit as st

from mori.core import AppError, TAIPEI
from mori.money_display import money_text, money_html, money_note, money_table, plan_platform, soften_decimals
from mori.budget_ledger import balance
from mori.invoices import (active_records, checked_file, invoice_summary, register_invoice, void_invoice)


def funding_badge(settings, plan_id, platform=''):
    value = invoice_summary(settings, plan_id)
    kind = 'running' if value['count'] else 'preparing'
    return f'<span class="mori-status {kind}"><span class="status-scope">{html.escape(platform or "儲值")}</span>{value["status"]}</span>'


def proof_caption(settings, plan_id):
    value = invoice_summary(settings, plan_id)
    amounts = '／'.join(f'{money_text(amount, plan_platform(settings, plan_id))}' for cur, amount in sorted(value['totals'].items()))
    money_note(st, f'已保存 {value["count"]} 筆有效發票' + (f'｜本計畫認列 {amounts}' if amounts else '｜尚未上傳發票證明'))


def render_invoices(settings, documents, persist):
    today = datetime.now(TAIPEI).date()
    accounts = {a['key']: a for a in settings['accounts']}
    groups = {g['id']: g for g in settings.get('project_groups', [])}
    plans = settings['projects']
    st.markdown('<div class="mori-editor-intro"><strong>儲值與發票</strong><p>每個專案、每個平台分開記錄；有有效發票即標示已儲值。</p></div>', unsafe_allow_html=True)
    st.info('「已儲值」依發票附件登錄判定，不代表平台已核實付款或入帳。發票認列不會增加專案預算，也不等於帳號儲值餘額。')
    for column, platform in zip(st.columns(2), ('meta', 'google')):
        with column:
            with st.container(border=True):
                st.subheader('Meta' if platform == 'meta' else 'Google Ads')
                platform_plans = [p for p in plans if accounts[p['account_key']]['platform'] == platform]
                done = sum(bool(invoice_summary(settings, p['id'])['count']) for p in platform_plans)
                st.write(f'已儲值 **{done}** 個計畫　｜　未儲值 **{len(platform_plans)-done}** 個計畫')
                sums = {}
                for p in platform_plans:
                    for cur, amount in invoice_summary(settings, p['id'])['totals'].items():
                        sums[cur] = sums.get(cur, Decimal(0)) + amount
                money_note(st, '發票認列總額：' + ('；'.join(f'{money_text(amount, platform)}' for cur, amount in sorted(sums.items())) or '尚未登錄'))
    if not plans:
        st.info('請先到「新增／編輯設定」建立專案與平台計畫，再登錄發票。')
        return
    def label(pid):
        p = next(p for p in plans if p['id'] == pid)
        a = accounts[p['account_key']]
        return f"{groups.get(p.get('group_id'), {}).get('name', p['name'])}｜{'Meta' if a['platform'] == 'meta' else 'Google Ads'}｜{a['name']}"
    from mori.budgets import configuration_key
    view = st.session_state.get('budget_view', {})
    results = view.get('results', {}) if view.get('key') == configuration_key(settings) and view.get('date') == str(today) else {}
    all_rows = []
    for p in plans:
        summary = invoice_summary(settings, p['id'])
        result = results.get(p['id'], {})
        spend = result.get('spend') if not result.get('error') and not result.get('not_started') else None
        all_rows.append({'專案／平台': label(p['id']), '儲值狀態': summary['status'], '有效發票': summary['count'],
                         '本計畫發票認列': '；'.join(f"{money_text(v, accounts[p['account_key']]['platform'])}" for cur, v in sorted(summary['totals'].items())) or '—',
                         '調整後專案預算（帳號幣別）': money_text(balance(settings, p['id'], today)['adjusted'], accounts[p['account_key']]['platform']),
                         '已使用預算（平台回報花費）': f"{money_text(spend, accounts[p['account_key']]['platform'])}" if spend is not None else '尚未讀取／讀取失敗'})
    money_table(st, pd.DataFrame(all_rows), [accounts[p['account_key']]['platform'] for p in plans], set())
    st.caption('花費沿用預算總覽本次讀取結果；需要最新數字時，至「預算總覽」按重新讀取。不同專案可能重疊，不加總為全帳號花費。')
    st.subheader('選擇專案／平台，登錄或查看發票')
    pending_plan = st.session_state.pop('pending_invoice_plan', None)
    if pending_plan in {p['id'] for p in plans}:
        st.session_state.invoice_plan = pending_plan
    plan_id = st.selectbox('發票所屬專案與平台', [p['id'] for p in plans], format_func=label, key='invoice_plan')
    platform = plan_platform(settings, plan_id)
    st.markdown(funding_badge(settings, plan_id), unsafe_allow_html=True)
    proof_caption(settings, plan_id)
    st.caption('發票附件會加密保存於私人資料儲存庫；可存取本網站的人仍可使用此頁，請以網站分享權限限制授權人員。')
    if documents is None:
        st.error('附件儲存尚未就緒：需設定有效 CREDENTIALS_KEY 與私人資料儲存庫，才能上傳或下載。')
    with st.form('invoice_add_' + plan_id, clear_on_submit=False):
        st.markdown('### 新增一筆發票紀錄')
        number = st.text_input('發票號碼／憑證編號', max_chars=100)
        a, b = st.columns(2)
        issued = a.date_input('發票日期', today, max_value=today)
        registered = b.date_input('儲值登錄日期', today, max_value=today)
        currency = st.text_input('幣別（須與此廣告帳號一致）', 'TWD', max_chars=3, help='例如 TWD；依實際發票及帳號填寫，不同幣別分開呈現，不換匯。')
        a, b = st.columns(2)
        face = a.number_input('發票票面總金額', min_value=0., step=1000., icon=':material/attach_money:', format='%.0f' if platform == 'meta' else '%.2f')
        allocated = b.number_input('本專案認列金額（與平台預算同口徑）', min_value=0., step=1000., icon=':material/attach_money:', format='%.0f' if platform == 'meta' else '%.2f')
        st.caption('票面金額依發票原額填寫；本專案認列金額填可歸屬此計畫的金額。若一張發票分攤多案，各案認列合計不得超過票面金額。稅額／服務費請在備註說明。')
        note = st.text_area('備註／用途／金額口徑', max_chars=2000)
        uploaded = st.file_uploader('發票證明（必填，每檔最多 5 MB）', type=['pdf', 'png', 'jpg', 'jpeg'], key='invoice_file_' + plan_id)
        st.caption('每筆一份附件，可重複新增多筆發票。選取檔案後仍需按下儲存；不會自動辨識發票文字或核實付款。')
        if st.form_submit_button('儲存發票與儲值紀錄', type='primary', width='stretch', disabled=documents is None):
            try:
                if uploaded is None:
                    raise AppError('請先上傳發票證明；未上傳不能登錄為已儲值。')
                reported = results.get(plan_id, {}).get('currency')
                if reported and currency.strip().upper() != reported:
                    raise AppError('登錄幣別與平台回報的帳號幣別不一致，請修正後再儲存。')
                content = uploaded.getvalue()
                metadata = checked_file(uploaded.name, content)
                operation = uuid.uuid4().hex
                # Validate amounts/duplicates/bindings before any document write.
                draft_file = {**metadata, 'document_id': operation, 'parts': 1}
                updated = register_invoice(settings, plan_id, number, issued, registered, currency, face, allocated, note, draft_file, operation)
                with st.spinner('加密保存發票附件…'):
                    saved = documents.save(uploaded.name, content)
                updated['project_invoices'][-1]['file'] = saved
                persist(updated, notice='發票與儲值紀錄已儲存，預算總覽已連動。', keep_budget_view=True)
            except (AppError, ValueError) as exc:
                st.error(str(exc).replace('$', r'\$'))
    st.subheader('發票與更正紀錄')
    voids = {v['invoice_id']: v for v in settings.get('invoice_voids', [])}
    records = [r for r in settings.get('project_invoices', []) if r['plan_id'] == plan_id]
    if not records:
        st.caption('尚無紀錄。')
    for row in reversed(records):
        voided = row['id'] in voids
        with st.expander(f"{'已作廢' if voided else '有效'}｜{row['invoice_number']}｜{row['issued_on']}"):
            money_note(st, f"票面金額：{money_text(row['face_amount'], platform)}；本專案認列：{money_text(row['allocated_amount'], platform)}")
            st.write('檔案：' + row['file']['name'])
            st.caption(f"儲值登錄日 {row['registered_on']}｜建立 {row['created_at']}｜紀錄 {row['id']}")
            if row['note']:
                st.write(row['note'])
            if documents is not None and st.button('讀取附件', key='invoice_read_' + row['id']):
                try:
                    content = documents.load(row['file'])
                    st.download_button('下載發票附件', content, file_name=row['file']['name'], mime=row['file']['mime'],
                                       key='invoice_download_' + row['id'], on_click='ignore')
                except AppError as exc:
                    st.error(str(exc).replace('$', r'\$'))
            if voided:
                st.caption('作廢原因：' + voids[row['id']]['reason'])
            else:
                with st.form('invoice_void_' + row['id']):
                    reason = st.text_input('作廢原因（填錯時先作廢，再重新登錄）')
                    confirm = st.checkbox('確認作廢此發票認列，保留原始附件與歷史')
                    if st.form_submit_button('作廢此筆紀錄'):
                        try:
                            if not confirm:
                                raise AppError('請勾選確認作廢，才會更新此筆紀錄。')
                            persist(void_invoice(settings, row['id'], reason), notice='已作廢，儲值狀態已重新判定。', keep_budget_view=True)
                        except AppError as exc:
                            st.error(str(exc).replace('$', r'\$'))
