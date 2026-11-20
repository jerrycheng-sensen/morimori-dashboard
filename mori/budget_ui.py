"""Project budget cards with independent activity and platform advertising dates."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st

from mori.budgets import (collect_spend, configuration_key, plan_summary, save_group,
                          save_plan, time_progress, group_summary)
from mori.core import AppError, TAIPEI
from mori.budget_ledger import balance, impacts
from mori.budget_ledger_ui import records, render_ledger


def render_budgets(settings, fetch, persist):
    today = datetime.now(TAIPEI).date()
    groups = {g['id']: g for g in settings.get('project_groups', [])}
    accounts = {a['key']: a for a in settings['accounts']}
    plans = settings['projects']
    st.caption('專案走期、各平台廣告走期分開管理；花費累計完整廣告走期，含預熱，資料截至昨天（台灣時間）。')
    overview, edit, ledger = st.tabs(['預算總覽', '新增／編輯設定', '預算調動與紀錄'])
    with overview:
        left, right = st.columns([3, 1])
        mode = left.radio('顯示專案', ['全部', '進行中', '已結案'], horizontal=True, key='budget_state_filter')
        if right.button('更新完整廣告走期花費', type='primary', disabled=not bool(plans)):
            # Each account provider owns its connection; writes/LINE are never invoked.
            with st.spinner('依各平台完整廣告走期讀取花費…'):
                results = collect_spend(plans, accounts, fetch, today)
            st.session_state.budget_view = {'key': configuration_key(settings), 'results': results,
                                            'at': datetime.now(TAIPEI).isoformat(), 'date': str(today)}
        view = st.session_state.get('budget_view')
        fresh = view and view['key'] == configuration_key(settings) and view['date'] == str(today)
        results = view['results'] if fresh else {}
        if fresh:
            stamp = datetime.fromisoformat(view['at']).strftime('%Y/%m/%d %H:%M')
            st.caption(f'最近更新：{stamp}（台灣時間）｜平台回補或調整後可再次更新，已結束計畫也能重查。')
        elif plans:
            st.info('按「更新完整廣告走期花費」載入預算進度；未查詢或讀取失敗不會顯示為零花費。')
        money_filter = st.selectbox('預算狀況', ['全部', '已超支', '廣告結束有結餘'], key='budget_money_filter')
        def visible(plan):
            if money_filter == '全部':
                return True
            summary = plan_summary(plan, results.get(plan['id']), today, settings)
            if summary['remaining'] is None:
                return False
            return summary['remaining'] < 0 if money_filter == '已超支' else (summary['budget'] > 0 and summary['remaining'] > 0 and today > date.fromisoformat(plan['end']))
        if not groups and not plans:
            st.info('先到「新增／編輯設定」建立專案，再分別加入 Meta、Google 投放計畫。')
        for gid, group in groups.items():
            if mode != '全部' and group['status'] != mode:
                continue
            children = [p for p in plans if p.get('group_id') == gid]
            if money_filter != '全部' and not any(visible(p) for p in children):
                continue
            with st.container(border=True):
                title, badge = st.columns([3, 1])
                title.subheader(group['name'])
                if group['status'] == '已結案':
                    state = '已結案'
                elif today < date.fromisoformat(group['start']):
                    state = '活動尚未開始'
                elif today > date.fromisoformat(group['end']):
                    state = '活動走期已結束'
                else:
                    state = '活動走期內'
                badge.markdown('**' + state + '**')
                st.caption(f"專案走期　{group['start']} ～ {group['end']}")
                elapsed = time_progress(group['start'], group['end'], today)
                st.progress(elapsed, text=f'專案時間進度 {elapsed:.0%}（含今天，與花費分開計算）')
                if children and all(today > date.fromisoformat(p['end']) for p in children):
                    st.caption('各平台投放已結束，保留實際花費與結餘。')
                if not children:
                    st.caption('尚未加入平台投放計畫。請到設定頁加入 Meta 或 Google。')
                if children:
                    render_group_totals(children, results, today, settings)
                    if money_filter != '全部':
                        st.caption('以下保留本專案所有平台，方便比較；預算狀況篩選用來挑出專案。')
                    ordered = sorted(children, key=lambda p: (accounts[p['account_key']]['platform'] != 'meta', p['account_key']))
                    # One envelope and one project title. Native columns stack on mobile.
                    for offset in range(0, len(ordered), 2):
                        columns = st.columns(min(2, len(ordered) - offset), gap='medium')
                        for col, plan in zip(columns, ordered[offset:offset+2]):
                            with col:
                                with st.container(border=True):
                                    render_plan(plan, accounts, results.get(plan['id']), today, settings, compact=True)
        ungrouped = [p for p in plans if not p.get('group_id') and (mode == '全部' or p['status'] == mode) and visible(p)]
        if ungrouped:
            st.subheader('既有平台計畫｜尚未歸入專案')
            st.caption('既有資料及異常規則連結均保留。可在設定頁編輯此計畫，指定所屬專案。')
            for plan in ungrouped:
                with st.container(border=True):
                    render_plan(plan, accounts, results.get(plan['id']), today, settings)
        st.caption('進度＝實際花費 ÷ 調整後可用預算。金額不另加稅與服務費，不等於儲值餘額。不同專案篩選可能重疊，因此不加總為全帳號花費。走期狀態依設定日期判斷，不代表平台即時開關狀態。')
    with edit:
        if not accounts:
            st.info('請先到「帳號與串接」新增廣告帳號。')
            return
        st.subheader('1. 專案資料')
        pending_group = st.session_state.pop('pending_budget_group', None)
        if pending_group in groups:
            st.session_state.budget_group_editor = pending_group
        group_id = st.selectbox('選擇專案', ['new'] + list(groups),
                               format_func=lambda k: '＋新增專案' if k == 'new' else groups[k]['name'], key='budget_group_editor')
        group = groups.get(group_id, {})
        with st.form('budget_group_' + group_id):
            name = st.text_input('專案名稱', group.get('name', ''), placeholder='例如：感謝祭')
            a, b = st.columns(2)
            start = a.date_input('專案開始日', date.fromisoformat(group['start']) if group else today)
            end = b.date_input('專案結束日', date.fromisoformat(group['end']) if group else today)
            status = st.selectbox('專案狀態', ['進行中', '已結案'], index=int(group.get('status') == '已結案'))
            st.caption('這裡填完整活動走期。例如感謝祭 10/1～11/30；Meta 的 9/29 預熱另外填在平台廣告走期。專案手動結案會停止所屬計畫的異常檢查。')
            if st.form_submit_button('儲存專案資料'):
                try:
                    updated = save_group(settings, {'id': group.get('id', uuid.uuid4().hex), 'name': name.strip(),
                                                    'start': str(start), 'end': str(end), 'status': status})
                    st.session_state.pending_budget_group = next(g['id'] for g in updated['project_groups'] if g['id'] not in groups) if not group else group['id']
                    persist(updated, notice='專案資料已儲存。接著在下方新增各平台投放計畫。')
                except (AppError, ValueError) as exc:
                    st.error(str(exc))
        st.subheader('2. Meta／Google 投放計畫')
        pending_plan = st.session_state.pop('pending_budget_plan', None)
        if pending_plan and any(p['id'] == pending_plan for p in plans):
            st.session_state.budget_plan_editor = pending_plan
        if st.button('＋新增平台計畫'):
            st.session_state.budget_plan_editor = 'new'
        def label(k):
            p = next(x for x in plans if x['id'] == k)
            parent = groups.get(p.get('group_id'), {}).get('name', '尚未歸入專案')
            account = accounts[p['account_key']]
            return f"{parent}｜{'Meta' if account['platform'] == 'meta' else 'Google Ads'}｜{account['name']}"
        plan_id = st.selectbox('選擇平台投放計畫', ['new'] + [p['id'] for p in plans],
                              format_func=lambda k: '＋新增平台計畫' if k == 'new' else label(k), key='budget_plan_editor')
        plan = next((p for p in plans if p['id'] == plan_id), {})
        # Keep existing ungrouped records editable without silently reassigning them.
        group_options = [''] + list(groups)
        account_key = st.selectbox('廣告帳號', list(accounts),
                          index=list(accounts).index(plan['account_key']) if plan else 0,
                          format_func=lambda k: accounts[k]['name'], key='budget_plan_account_' + plan_id)
        google_plan = accounts[account_key]['platform'] == 'google'
        with st.form('budget_plan_' + plan_id):
            owner = st.selectbox('所屬專案', group_options,
                                 index=group_options.index(plan.get('group_id', '')),
                                 format_func=lambda k: groups[k]['name'] if k else '尚未歸入專案（保留既有設定）', key='budget_plan_owner_' + plan_id)
            name = st.text_input('平台計畫名稱', plan.get('name', ''), placeholder='例如：含預熱（可留白）', help='專案名稱由上方專案資料管理；這裡只作為設定與紀錄識別，總覽不會重複顯示。留白時自動使用平台名稱。')
            a, b = st.columns(2)
            ad_start = a.date_input('廣告開始日（可含預熱）', date.fromisoformat(plan['start']) if plan else today)
            ad_end = b.date_input('廣告結束日', date.fromisoformat(plan['end']) if plan else today)
            locked_budget = any(plan.get('id') in impacts(t) for t in settings.get('budget_transactions', []))
            budget = st.number_input('平台投放預算（與廣告帳號同幣別，不另加稅／服務費）', min_value=0., value=float(plan.get('budget', 0)), step=1000., disabled=locked_budget)
            if locked_budget:
                st.caption('已有異動紀錄，原始預算已保留；請到「預算調動與紀錄」辦理追加／減列。')
            st.caption('0 代表預算尚未設定，總覽會顯示「未設定」，不會計算花費百分比。')
            from mori.project_matching import FIELDS, conditions
            if google_plan:
                st.markdown('**Google 廣告認列條件**')
                st.caption('一般 Google 廣告：廣告活動 → 廣告群組 → 廣告；PMax：廣告活動 → 素材群組。標題、說明、路徑依各格式提供的內容比對。')
                st.caption('廣告 ID 是 API 回傳的數字編號；選擇廣告條件時，須填完整 ID 並完全相符。可先用文案預覽，在明細查看 ID；不必先找 ID 才能設定。')
                st.caption('只計入上述廣告走期；同一廣告符合多個條件只算一次。廣告以 ID 辨識，不需要廣告名稱。')
                mode = st.selectbox('條件組合', ['all', 'any'], index=int(plan.get('match_mode', 'all') == 'any'),
                                    format_func=lambda x: '全部條件都符合（AND）' if x == 'all' else '符合任一條件（OR）')
                existing = conditions(plan)
                options = [k for k in FIELDS if k != 'ad_name']
                matching = []
                for i in range(6):
                    condition = existing[i] if i < len(existing) else {}
                    left, right = st.columns([1, 2])
                    selected = condition.get('field', 'campaign_name')
                    field_i = left.selectbox(f'認列欄位 {i+1}', options, index=options.index(selected) if selected in options else 0,
                                            format_func=lambda k: FIELDS[k], key=f'budget_field_{plan_id}_{i}')
                    text_i = right.text_input(f'包含文字／廣告 ID {i+1}', condition.get('text', ''),
                                              placeholder='例如：感謝祭；多個文字擇一可填 桃園|新竹', key=f'budget_text_{plan_id}_{i}')
                    if text_i.strip():
                        matching.append({'field': field_i, 'text': text_i.strip()})
                st.caption('空白條件不使用。標題含短標題與長標題；未提供的欄位不會虛構。PMax 命中素材群組文案時，認列的是該素材群組整筆花費，請勿將不同專案素材混放同一群組。')
                st.caption('文案依 API 目前設定比對，無法還原歷史文案；若曾改稿，請核對廣告 ID 與走期。')
                field, keyword = (matching[0]['field'], matching[0]['text']) if matching else ('campaign_name', '')
            else:
                options = ['campaign_name', 'adset_name', 'ad_name']
                field = st.selectbox('名稱歸類欄位', options, index=options.index(plan.get('match_field', 'campaign_name')) if plan.get('match_field', 'campaign_name') in options else 0,
                                     format_func=lambda k: {'campaign_name': '行銷活動名稱（Meta）', 'adset_name': '廣告組合名稱（僅 Meta）', 'ad_name': '廣告名稱（僅 Meta）'}[k])
                keyword = st.text_input('名稱包含（必填）', plan.get('keyword', ''), placeholder='例如：感謝祭')
                matching, mode = [], 'all'
            status = st.selectbox('平台計畫狀態', ['進行中', '已結案'], index=int(plan.get('status') == '已結案'))
            st.caption('廣告結束日期會停止之後資料日的異常檢查，隔天仍會檢查最後一天；手動結案則立即停止檢查。')
            if google_plan and st.form_submit_button('預覽認列廣告（不儲存）'):
                try:
                    from mori.project_matching import validate_matching
                    draft = {**plan, 'id': plan.get('id', '_preview'), 'name': name.strip(),
                             'account_key': account_key, 'start': str(ad_start), 'end': str(ad_end),
                             'match_field': field, 'keyword': keyword.strip(), 'match_conditions': matching, 'match_mode': mode}
                    validate_matching(draft, 'google')
                    if ad_end < ad_start:
                        raise AppError('廣告結束日不可早於開始日。')
                    with st.spinner('讀取 Google 廣告並核對認列條件…'):
                        preview = collect_spend([p for p in plans if p['id'] != draft['id']] + [draft], accounts, fetch, today)[draft['id']]
                    if preview.get('error'):
                        raise AppError(preview['error'])
                    if preview.get('not_started'):
                        st.info('廣告尚未開始，尚無完整資料日可以預覽。')
                    else:
                        st.success(f"預覽花費 {preview['currency']} {preview['spend']:,.2f}；尚未儲存設定。")
                        for warning in preview.get('warnings', []):
                            st.warning(warning)
                        if preview['rows']:
                            st.dataframe(pd.DataFrame(preview['rows']), hide_index=True, width='stretch')
                        else:
                            st.info('沒有符合條件的廣告，請檢查走期與文字。')
                except (AppError, ValueError) as exc:
                    st.error(str(exc))
            if st.form_submit_button('儲存平台計畫'):
                try:
                    if not owner and not plan:
                        raise AppError('請先建立並選擇所屬專案，再新增平台計畫。')
                    updated = save_plan(settings, {'id': plan.get('id', uuid.uuid4().hex), 'name': name.strip() or ('Google Ads' if google_plan else 'Meta'),
                                                  'account_key': account_key, 'group_id': owner, 'start': str(ad_start),
                                                  'end': str(ad_end), 'budget': budget, 'match_field': field,
                                                  'keyword': keyword.strip(), 'status': status,
                                                  'match_conditions': matching, 'match_mode': mode})
                    st.session_state.pending_budget_plan = next(p['id'] for p in updated['projects'] if p['id'] not in {x['id'] for x in plans}) if not plan else plan['id']
                    persist(updated, notice='平台計畫已儲存。回到預算總覽更新完整廣告走期花費。')
                except (AppError, ValueError) as exc:
                    st.error(str(exc))
        st.download_button('匯出設定備份（不含權杖）', json.dumps(settings, ensure_ascii=False, indent=2),
                           'mori-settings.json', on_click='ignore')

    with ledger:
        render_ledger(settings, fetch, persist)


def render_group_totals(plans, results, today, settings):
    data = group_summary(plans, results, today, settings)
    a, b, c, d = st.columns(4)
    money = lambda v: f'{v:,.2f}' if v is not None else '—'
    a.metric('可用總預算', money(data['budget']))
    b.metric('累計總花費', money(data['spend']))
    c.metric('專案超支' if data['remaining'] is not None and data['remaining'] < 0 else '專案結餘',
             money(abs(data['remaining'])) if data['remaining'] is not None else '—')
    d.metric('整體花費進度', f"{data['ratio']:.1%}" if data['ratio'] is not None else '—')
    if data['reason']:
        st.caption(data['reason'])
    else:
        st.caption(f"{data['currency']}｜以下平台金額的專案合計，已包含預算轉入／轉出。")


def render_plan(plan, accounts, result, today, settings, compact=False):
    account = accounts[plan['account_key']]
    platform = 'Meta' if account['platform'] == 'meta' else 'Google Ads'
    data = plan_summary(plan, result, today, settings)
    # Project title belongs to the outer envelope; plan name stays in the details.
    st.markdown('#### ' + platform)
    st.caption(f"廣告走期　{plan['start']} ～ {plan['end']}　｜　{data['state']}")
    if not plan.get('group_id'):
        st.caption('平台計畫：' + plan['name'])
    warnings = (result or {}).get('warnings', [])
    if any('未提供全部' in w for w in warnings):
        st.warning('部分廣告缺少選定的文案欄位；請展開下方明細核對未納入的花費。')
    if result and result.get('error'):
        st.error(account['name'] + '：' + result['error'])
    funds = balance(settings, plan['id'], today)
    if compact:
        a, b = st.columns(2)
        c, d = st.columns(2)
    else:
        a, b, c, d = st.columns(4)
    initialized = funds['original'] > 0 or any(plan['id'] in impacts(t) for t in settings.get('budget_transactions', []))
    a.metric('可用預算', f"{data['budget']:,.2f}" if initialized else '未設定')
    b.metric('累計花費', f"{data['spend']:,.2f}" if data['spend'] is not None else '—')
    c.metric('超支金額' if data['remaining'] is not None and data['remaining'] < 0 else '剩餘預算',
             f"{abs(data['remaining']):,.2f}" if data['remaining'] is not None and initialized else '—')
    d.metric('花費進度', f"{data['ratio']:.1%}" if data['ratio'] is not None else '—')
    if data['ratio'] is not None:
        ratio = data['ratio']
        color = '#c34236' if ratio > 1 else '#17421E'
        st.markdown(f'<div style="height:8px;background:#e2e9df;border-radius:10px;margin:12px 0 8px" role="img" aria-label="花費進度 {ratio:.1%}">'
                    f'<div style="width:{max(0,min(100,ratio*100)):.3f}%;height:100%;background:{color};border-radius:10px"></div></div>', unsafe_allow_html=True)
        st.caption(f'花費 {ratio:.1%}・廣告走期進度 {data["time_ratio"]:.0%}（截至資料日）')
        if ratio > 1:
            st.warning('已超過此平台預算。')
    history = records(settings, plan['id'])
    with st.expander('預算組成與調動紀錄'):
        st.caption(f"原始 {funds['original']:,.2f} ＋ 轉入 {funds['incoming']:,.2f} － 轉出 {funds['outgoing']:,.2f} ＋ 追加／減列 {funds['adjustment']:,.2f} ＝ 可用 {funds['adjusted']:,.2f}")
        if not history.empty:
            st.dataframe(history, hide_index=True, width='stretch')
        else:
            st.caption('尚無預算異動。')
    detail_title = '認列說明與廣告明細' + (f'（{len(warnings)} 項提醒）' if warnings else '')
    with st.expander(detail_title):
        st.caption(f"廣告帳號：{account['name']}｜原平台計畫名稱：{plan['name']}")
        for warning in warnings:
            st.warning(warning)
        if result and result.get('until'):
            st.caption(f"{data['currency'] or '帳號幣別'}｜資料 {result['since']} ～ {result['until']}｜時區 {result.get('timezone') or '未回傳'}")
            rows = result['rows']
            if rows:
                df = pd.DataFrame(rows)
                columns = [k for k in ['date', 'channel', 'ad_type', 'attribution_unit', 'campaign_name', 'adset_name', 'ad_id', 'ad_name', 'asset_group_name', 'asset_group_id', 'headlines', 'descriptions', 'paths', 'spend', 'currency'] if k in df]
                st.dataframe(df[columns].rename(columns={'date': '日期', 'campaign_name': '廣告活動' if account['platform'] == 'google' else '行銷活動', 'adset_name': '廣告群組' if account['platform'] == 'google' else '廣告組合',
                                                        'ad_name': '廣告', 'asset_group_name': '素材群組', 'asset_group_id': '素材群組 ID', 'ad_type': '廣告格式', 'attribution_unit': '花費認列單位', 'channel': '類型', 'ad_id': '廣告 ID', 'headlines': '目前標題', 'descriptions': '目前說明', 'paths': '目前路徑', 'spend': '花費', 'currency': '幣別'}), hide_index=True, width='stretch')
            else:
                st.info('此走期與條件沒有符合的廣告。請核對篩選條件。')
        elif result and result.get('not_started'):
            st.caption('廣告尚未開始，尚未查詢花費。')
        else:
            st.caption('尚未取得實際花費；進度與結餘暫不計算。')
