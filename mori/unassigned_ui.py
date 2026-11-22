"""Plain-language review and explicit assignment; checks run on demand."""
import hashlib
import json
from decimal import Decimal

import pandas as pd
import streamlit as st

from mori.account_funding import account_identity
from mori.budgets import configuration_key
from mori.budget_ledger import plan_label
from mori.core import AppError
from mori.money_display import money_table
from mori.unassigned import scan, assign, undo, reclassify


def pending_units(rows):
    grouped = {}
    for row in rows:
        key = (tuple(row['physical']), tuple(sorted(row['unit'].items())))
        if key not in grouped:
            grouped[key] = {**row, 'amount': Decimal(0)}
        item = grouped[key]
        item['amount'] += Decimal(row['amount'])
        item['since'] = min(item['since'], row['since'])
        item['until'] = max(item['until'], row['until'])
    return list(grouped.values())


def audit_key(settings, start, end):
    return hashlib.sha256(json.dumps([configuration_key(settings), str(start), str(end)]).encode()).hexdigest()


def render_unassigned(settings, fetch, persist, start, end):
    key = audit_key(settings, start, end)
    if st.button('檢查未歸案花費', key='unassigned_scan', disabled=fetch is None or not settings['accounts']):
        try:
            with st.spinner('逐一核對廣告與專案，包含未投放中的舊廣告…'):
                result = scan(settings, fetch, start, end)
            st.session_state.unassigned_view = {'key': key, 'result': result}
        except AppError as exc:
            st.error(str(exc))
    cached = st.session_state.get('unassigned_view', {})
    if cached.get('key') != key:
        st.info('按「檢查未歸案花費」，列出有花費、卻還沒加入專案的廣告。')
    else:
        result = cached['result']
        st.caption('檢查時間：' + result['at'][:19].replace('T', ' ') + '（台灣時間）・含今日平台已回報的花費')
        for error in result['errors']:
            st.error(error)
        items = pending_units(result['pending'])
        if items:
            st.warning(f'發現 {len(items)} 則廣告／素材群組有花費尚未歸案。')
            rows = []
            for item in items:
                row = item['row'] if 'row' in item else item
                # Scan entries carry a copy of the platform row, not inferred names.
                rows.append({'平台': 'Meta' if item['platform'] == 'meta' else 'Google Ads',
                             '廣告帳號': item['account_name'], '廣告活動': row.get('campaign_name', ''),
                             '廣告／素材群組': row.get('asset_group_name') or row.get('ad_name') or 'ID ' + item['unit']['id'],
                             'ID': item['unit']['id'], '開始日': item['since'], '結束日': item['until'],
                             '待歸案花費': item['amount'], '幣別': item['currency']})
            money_table(st, pd.DataFrame(rows), [r['platform'] for r in items], {'待歸案花費'})
            st.caption('只列查詢期間內、未符合任何專案的花費。PMax 以整個素材群組歸案，不能拆分單一素材。Meta 分段查詢金額可能受平台四捨五入影響；儲存後以專案整段走期重新讀取。')
            index = st.selectbox('選擇要歸案的廣告', range(len(items)),
                                 format_func=lambda i: rows[i]['平台'] + '｜' + rows[i]['廣告／素材群組'] + '｜ID ' + items[i]['unit']['id'], key='unassigned_unit')
            item = items[index]
            accounts = {a['key']: a for a in settings['accounts']}
            options = [p['id'] for p in settings['projects'] if p.get('group_id') and account_identity(accounts[p['account_key']]) == tuple(item['physical'])]
            if not options:
                st.info('此帳號尚未建立專案投放計畫，請先到「新增／編輯設定」建立。')
            else:
                target = st.selectbox('歸入哪個專案', options, format_func=lambda pid: plan_label(settings, pid), key='unassigned_target')
                plan = next(p for p in settings['projects'] if p['id'] == target)
                st.caption(f"本次只歸入該計畫的廣告走期：{plan['start']} ～ {plan['end']}。其他日期的花費仍會留在待歸案清單。")
                with st.form('unassigned_assign_' + item['key'] + '_' + target):
                    st.caption('歸案後，這則廣告／素材群組在所選計畫廣告走期內的花費都會計入；未來符合走期的花費也會自動計入，不會修改廣告平台設定或專案預算。')
                    confirm = st.checkbox('已確認廣告內容、所屬專案與投放日期', key='unassigned_confirm_' + item['key'] + '_' + target)
                    if st.form_submit_button('確認歸案', type='primary', disabled=persist is None):
                        try:
                            if not confirm:
                                raise AppError('請先確認廣告內容、所屬專案與投放日期。')
                            with st.spinner('再次檢查花費與重複歸案…'):
                                updated = assign(settings, fetch, item, target, end)
                            st.session_state.unassigned_view = {'key': audit_key(updated, start, end), 'result': reclassify(result, updated)}
                            persist(updated, notice='廣告已歸入專案，預算總覽將重新讀取花費。')
                        except AppError as exc:
                            st.error(str(exc))
        elif not result['errors'] and not result['conflicts']:
            st.success('這次取得的廣告花費，都已找到所屬專案。')
        if result['conflicts']:
            st.error('有廣告同時符合多個專案，請到「新增／編輯設定」縮小認列條件或調整廣告日期。')
            for row in pending_units(result['conflicts']):
                st.write(row['account_name'] + '｜ID ' + row['unit']['id'] + '｜' + row['since'] + ' ～ ' + row['until'])
            st.caption('重複歸案不算作待歸案；上方清單不會把它再分配一次。')
            for row in result['conflicts']:
                st.caption('ID ' + row['unit']['id'] + '：' + '、'.join(plan_label(settings, pid) for pid in row['owners']))
    assigned = [(p['id'], u) for p in settings['projects'] for u in p.get('assigned_units', [])]
    if assigned:
        with st.expander('查看／撤銷手動歸案'):
            selected = st.selectbox('已手動歸案的廣告', range(len(assigned)), key='unassigned_undo_item',
                                    format_func=lambda i: plan_label(settings, assigned[i][0]) + '｜ID ' + assigned[i][1]['id'])
            pid, unit = assigned[selected]
            st.caption('填錯可撤銷手動歸案；會保留操作紀錄。重新檢查後，仍未符合其他條件的花費會回到待歸案清單。')
            if st.button('撤銷這筆手動歸案', disabled=persist is None, key='unassigned_undo'):
                updated = undo(settings, pid, unit)
                if cached.get('key') == key:
                    st.session_state.unassigned_view = {'key': audit_key(updated, start, end), 'result': reclassify(cached['result'], updated)}
                persist(updated, notice='已撤銷手動歸案，預算總覽將重新讀取。')
