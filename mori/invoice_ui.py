"""Invoice registration and per-platform evidence status, using native controls."""
import html
import uuid
from datetime import datetime
from decimal import Decimal

import pandas as pd
import streamlit as st

from mori.core import AppError, TAIPEI
from mori.money_display import money_text, money_html, money_note, money_metric, money_table, plan_platform, soften_decimals
from mori.budget_ledger import balance
from mori.invoices import (active_records, checked_file, invoice_summary, register_invoice, void_invoice, invoice_quote, invoice_order_reference, link_invoice_order)


def funding_badge(settings, plan_id, platform=''):
    value = invoice_summary(settings, plan_id)
    kind = 'running' if value['count'] else 'preparing'
    return f'<span class="mori-status {kind}"><span class="status-scope">{html.escape(platform or "儲值")}</span>{value["status"]}</span>'


def proof_caption(settings, plan_id):
    value = invoice_summary(settings, plan_id)
    amounts = '／'.join(f'{money_text(amount, plan_platform(settings, plan_id))}' for cur, amount in sorted(value['totals'].items()))
    money_note(st, f'已保存 {value["count"]} 筆有效發票' + (f'｜本計畫認列 {amounts}' if amounts else '｜尚未上傳發票證明'))


def step_heading(number, title, description):
    st.markdown(f'<div class="invoice-step"><span>{number}</span><div><h2>{title}</h2><p>{description}</p></div></div>', unsafe_allow_html=True)


def render_invoices(settings, documents, persist):
    st.markdown(INVOICE_STYLES, unsafe_allow_html=True)
    with st.container(key='invoice_workspace'):
        _render_invoices(settings, documents, persist)


def _render_invoices(settings, documents, persist):
    today = datetime.now(TAIPEI).date()
    accounts = {a['key']: a for a in settings['accounts']}
    groups = {g['id']: g for g in settings.get('project_groups', [])}
    plans = settings['projects']
    st.markdown('<div class="mori-editor-intro"><strong>儲值與發票</strong><p>把訂單、發票與廣告預算放在一起，核對更清楚。</p></div>', unsafe_allow_html=True)
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
    pending_plan = st.session_state.pop('pending_invoice_plan', None)
    if pending_plan in {p['id'] for p in plans}:
        st.session_state.invoice_plan = pending_plan
    step_heading('01', '選擇專案', '先確認這張發票要登錄到哪個專案與平台。')
    plan_id = st.selectbox('發票所屬專案與平台', [p['id'] for p in plans], format_func=label, key='invoice_plan')
    platform = plan_platform(settings, plan_id)
    selected = next(p for p in plans if p['id'] == plan_id)
    summary = invoice_summary(settings, plan_id)
    with st.container(border=True, key='invoice_selected_context'):
        st.markdown(f'<div class="invoice-context-title">{html.escape(groups.get(selected.get("group_id"), {}).get("name", selected["name"]))}</div>', unsafe_allow_html=True)
        st.markdown(funding_badge(settings, plan_id, 'Meta' if platform == 'meta' else 'Google Ads'), unsafe_allow_html=True)
        context = st.columns(2)
        money_metric(context[0], '專案原始廣告預算', balance(settings, plan_id, today)['original'], platform)
        total = next(iter(summary['totals'].values()), Decimal(0)) if len(summary['totals']) <= 1 else None
        money_metric(context[1], '已登錄發票的廣告金額', total, platform)
        if len(summary['totals']) > 1:
            money_note(st, '不同幣別分開認列：' + '；'.join(cur + ' ' + money_text(amount, platform) for cur, amount in sorted(summary['totals'].items())))
        st.write(f'有效發票 {summary["count"]} 筆 · 儲值廠商：精立數位')
    st.divider()
    if documents is None:
        st.error('附件儲存尚未就緒：需設定有效 CREDENTIALS_KEY 與私人資料儲存庫，才能上傳或下載。')
    scope = 'invoice_amount_' + plan_id
    original_budget = balance(settings, plan_id, today)['original']
    with st.container(border=True, key='invoice_calculator'):
        step_heading('02', '確認本次金額', '輸入未稅廣告費，自動算出服務費、稅額與發票總額。')
        money_note(st, '原始平台預算：' + money_text(original_budget, platform) + '（未稅、不含服務費）。借入／轉入預算不會自動當成新儲值。')
        base = st.number_input('本次廣告可用金額（未稅、不含服務費）', min_value=0., value=float(original_budget),
                               step=1000., format='%.0f' if platform == 'meta' else '%.2f',
                               icon=':material/attach_money:', key=scope + '_base')
        st.caption('可修改為本次實際儲值或分攤的廣告費；這個金額才會認列到專案，服務費與稅不算可投放預算。')
        basis = 'ad_plus_service' if platform == 'meta' else 'ad'
        st.write('Meta：服務費 3%，廣告費＋服務費一起計稅 5%。' if platform == 'meta' else 'Google Ads：無服務費，廣告費計稅 5%。')
        with st.expander('調整計稅與進位方式'):
            if platform == 'meta':
                basis = st.radio('Meta 稅額計算基礎（請依發票確認）', ['ad_plus_service', 'ad'], index=0,
                                 format_func=lambda value: '廣告費＋服務費，一起計算 5% 稅' if value == 'ad_plus_service' else '只有廣告費計算 5% 稅',
                                 key=scope + '_basis')
            rounding = st.selectbox('服務費與稅額的進位方式', ['whole', 'cents'],
                                    format_func=lambda value: '各項四捨五入至整元' if value == 'whole' else '各項四捨五入至小數 2 位', key=scope + '_rounding')
        quote = None
        if base > 0 and basis:
            quote = invoice_quote(platform, base, basis, rounding)
            a, b, c, d = st.columns(4)
            display_platform = 'meta' if platform == 'meta' and rounding == 'whole' else 'google'
            money_metric(a, '廣告可用金額', base, platform)
            money_metric(b, '服務費（3%）' if platform == 'meta' else '服務費（0%）', quote['service_amount'], display_platform)
            money_metric(c, '稅額（5%）', quote['tax_amount'], display_platform)
            money_metric(d, '預估發票總額', quote['total'], display_platform)
            st.caption('稅額＝' + ('（廣告費＋已進位的服務費）' if quote['tax_basis'] == 'ad_plus_service' else '廣告費') + '× 5%；總額＝廣告費＋服務費＋稅。依你提供的費率試算，實際仍以發票為準。')
        elif platform == 'meta' and not basis:
            st.info('請先選擇 Meta 稅額計算基礎，再帶入發票欄位。')
        if st.button('套用到下方發票欄位', key=scope + '_apply', disabled=quote is None, type='primary'):
            st.session_state[scope + '_face'] = float(quote['total'])
            st.session_state[scope + '_allocated'] = float(quote['ad_amount'])
            st.session_state[scope + '_applied'] = quote
            st.success('已帶入：發票總額含服務費與稅；專案認列只有廣告費。尚未儲存發票。')
    if st.session_state.get(scope + '_applied'):
        st.caption('下方欄位沿用上次套用的試算；修改上方金額後，請再次按套用。')
        if st.button('取消套用，改為手動登錄', key=scope + '_manual'):
            st.session_state.pop(scope + '_applied', None)
    st.session_state.setdefault(scope + '_face', 0.)
    st.session_state.setdefault(scope + '_allocated', 0.)
    with st.form('invoice_add_' + plan_id, clear_on_submit=False):
        step_heading('03', '登錄訂單與發票', '核對金額 → 上傳發票 → 按下儲存，完成本次登錄。')
        a, b = st.columns(2)
        order_number = a.text_input('精立數位訂單編號', max_chars=100, placeholder='請填訂單查詢頁的訂單編號', key=scope + '_order')
        number = b.text_input('發票號碼／憑證編號', max_chars=100)
        st.write('儲值廠商：精立數位。訂單編號與發票號碼分開記錄，方便日後核對。')
        a, b = st.columns(2)
        issued = a.date_input('發票日期', today, max_value=today)
        registered = b.date_input('儲值登錄日期', today, max_value=today)
        currency = 'TWD'
        a, b = st.columns(2)
        face = a.number_input('發票票面總金額', min_value=0., step=1000., icon=':material/attach_money:', format='%.0f' if platform == 'meta' and st.session_state.get(scope + '_applied', {}).get('rounding') != 'cents' else '%.2f', key=scope + '_face')
        allocated = b.number_input('本專案認列金額（與平台預算同口徑）', min_value=0., step=1000., icon=':material/attach_money:', format='%.0f' if platform == 'meta' else '%.2f', key=scope + '_allocated')
        st.write('發票總額含服務費與稅；專案認列只計廣告可用金額。')
        uploaded = st.file_uploader('發票證明（必填，每檔最多 5 MB）', type=['pdf', 'png', 'jpg', 'jpeg'], key='invoice_file_' + plan_id)
        st.caption('支援 PDF、PNG、JPG。上傳後，請按下方儲存才會完成登錄。')
        with st.expander('備註與其他設定（分攤發票、金額差異時填寫）'):
            note = st.text_area('備註／用途／金額口徑', max_chars=2000)
            currency = st.text_input('幣別（須與此廣告帳號一致）', 'TWD', max_chars=3)
            st.write('一張發票可分攤多個專案；各案認列合計不可超過票面金額。實際票面與試算不同時，請填寫差異原因。')
        st.markdown('<div class="invoice-save-note">儲存後：發票連結到此專案，並更新已儲值狀態。服務費與稅不會加進廣告預算。</div>', unsafe_allow_html=True)
        if st.form_submit_button('儲存發票與儲值紀錄', type='primary', width='stretch', disabled=documents is None):
            try:
                if uploaded is None:
                    raise AppError('請先上傳發票證明；未上傳不能登錄為已儲值。')
                if not order_number.strip():
                    raise AppError('請填寫精立數位訂單編號。')
                reported = results.get(plan_id, {}).get('currency')
                if reported and currency.strip().upper() != reported:
                    raise AppError('登錄幣別與平台回報的帳號幣別不一致，請修正後再儲存。')
                content = uploaded.getvalue()
                metadata = checked_file(uploaded.name, content)
                operation = uuid.uuid4().hex
                # Validate amounts/duplicates/bindings before any document write.
                draft_file = {**metadata, 'document_id': operation, 'parts': 1}
                updated = register_invoice(settings, plan_id, number, issued, registered, currency, face, allocated, note, draft_file, operation, charge_quote=st.session_state.get(scope + '_applied'), supplier_order_number=order_number)
                with st.spinner('加密保存發票附件…'):
                    saved = documents.save(uploaded.name, content)
                updated['project_invoices'][-1]['file'] = saved
                persist(updated, notice='發票與儲值紀錄已儲存，預算總覽已連動。', keep_budget_view=True)
            except (AppError, ValueError) as exc:
                st.error(str(exc).replace('$', r'\$'))
    st.divider()
    step_heading('04', '已登錄發票', '展開查看訂單、金額與附件；舊發票也能在這裡補填訂單編號。')
    voids = {v['invoice_id']: v for v in settings.get('invoice_voids', [])}
    records = [r for r in settings.get('project_invoices', []) if r['plan_id'] == plan_id]
    if not records:
        st.info('這個專案／平台尚未登錄發票，完成上方三個步驟即可新增。')
    for row in reversed(records):
        voided = row['id'] in voids
        reference = invoice_order_reference(settings, row)
        with st.expander(f"{'已作廢' if voided else '有效'}｜{row['invoice_number']}｜訂單 {reference['order_number'] or '未填寫'}｜{row['issued_on']}"):
            st.write('精立數位訂單編號：' + (reference['order_number'] or '尚未填寫'))
            invoice_platform = 'google' if row.get('charge_quote', {}).get('rounding') == 'cents' else platform
            money_note(st, f"票面金額：{money_text(row['face_amount'], invoice_platform)}；本專案認列：{money_text(row['allocated_amount'], platform)}")
            if row.get('charge_quote'):
                charges = row['charge_quote']
                money_note(st, '服務費：' + money_text(charges['service_amount'], invoice_platform) + '；稅額：' + money_text(charges['tax_amount'], invoice_platform) + '；試算總額：' + money_text(charges['total'], invoice_platform) + '；實際票面與試算差額：' + money_text(row['invoice_difference'], invoice_platform))
            for change in settings.get('invoice_order_links', []):
                if change['invoice_id'] == row['id']:
                    st.caption('訂單編號更正紀錄：' + change['order_number'] + ' · ' + change['created_at'])
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
                with st.form('invoice_order_' + row['id']):
                    amended_order = st.text_input('補填／更正精立數位訂單編號', value=reference['order_number'], max_chars=100)
                    if st.form_submit_button('儲存訂單編號'):
                        try:
                            persist(link_invoice_order(settings, row['id'], amended_order), notice='訂單編號已儲存；發票與預算金額未變更。', keep_budget_view=True)
                        except AppError as exc:
                            st.error(str(exc))
                st.caption('以下僅供金額或附件登錄錯誤時使用；補填訂單編號不需作廢。')
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

    st.divider()
    with st.expander('查看全部專案的儲值與發票總表'):
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
        money_table(st, pd.DataFrame(all_rows), [accounts[p['account_key']]['platform'] for p in plans], set())
        st.caption('花費沿用預算總覽的讀取結果；更新請至預算總覽按重新讀取。不同專案可能重疊，不加總為全帳號花費。')
    with st.expander('儲值狀態、發票保存與金額說明'):
        st.write('「已儲值」代表此專案／平台已上傳有效發票；不代表平台已核實付款或入帳。發票認列不會增加專案預算，也不等於帳號餘額。')
        st.write('附件加密保存在私人資料儲存庫。能使用此網站的人也能操作發票，請透過網站分享權限管理。系統不會自動辨識發票或核實付款。')


INVOICE_STYLES = """<style>
.st-key-invoice_workspace {--invoice-line:#e6dfd2; --invoice-muted:#657167;}
.st-key-invoice_workspace [data-testid="stVerticalBlock"] {gap:1.15rem;}
.st-key-invoice_workspace p,.st-key-invoice_workspace label p,
.st-key-invoice_workspace [data-testid="stCaptionContainer"] p,
.st-key-invoice_workspace [data-testid="stExpander"] summary p {font-size:1rem!important;line-height:1.75!important;}
.st-key-invoice_workspace input,.st-key-invoice_workspace textarea,
.st-key-invoice_workspace [data-baseweb="select"] {font-size:1.05rem!important;}
.st-key-invoice_workspace button p {font-size:1.05rem!important;font-weight:650;}
.st-key-invoice_workspace input {min-height:48px;}
.st-key-invoice_workspace hr {margin:1.5rem 0;border-color:var(--invoice-line);}
.st-key-invoice_workspace [data-testid="stForm"],.st-key-invoice_calculator,
.st-key-invoice_selected_context {padding:2rem!important;border:1px solid var(--invoice-line)!important;border-radius:20px!important;background:#fffefa;}
.st-key-invoice_selected_context {background:linear-gradient(120deg,#fffefa,#f3efe6);}
.st-key-invoice_workspace [data-testid="stForm"] {box-shadow:0 10px 32px #243a2410;margin-bottom:1rem;}
.st-key-invoice_workspace [data-testid="stExpander"] {border-color:var(--invoice-line);border-radius:12px;}
.st-key-invoice_workspace [data-testid="stForm"] [data-testid="stForm"] {box-shadow:none;}
.st-key-invoice_workspace .mori-money-label{font-size:16px;}
.st-key-invoice_workspace .mori-money-value{font-size:clamp(26px,2.3vw,36px);}
.invoice-step {display:flex;align-items:flex-start;gap:18px;margin:14px 0 20px;}
.invoice-step>span {display:grid;place-items:center;flex:0 0 44px;height:44px;border-radius:14px;background:#17421E;color:#fffefa;font-size:16px;font-weight:700;}
.invoice-step h2 {margin:0!important;padding:0!important;font-size:26px!important;font-weight:750!important;color:#17421E;}
.invoice-step p {margin:6px 0 0;color:#657167;font-size:16px;}
.invoice-context-title {font-size:26px;font-weight:750;color:#17421E;}
.invoice-save-note {border-left:3px solid #b79a65;background:#f5f1e8;padding:14px 18px;color:#425745;border-radius:6px;font-size:16px;line-height:1.7;}
@media(max-width:760px){.st-key-invoice_workspace [data-testid="stForm"],.st-key-invoice_calculator,.st-key-invoice_selected_context{padding:1rem!important;}.invoice-step h2{font-size:22px!important;}}
</style>"""
