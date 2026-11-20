"""Project budget cards with independent activity and platform advertising dates."""
from __future__ import annotations

import html
import json
import uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st

from mori.budgets import (collect_spend, configuration_key, plan_summary, save_group,
                          save_plan, time_progress)
from mori.core import AppError, TAIPEI


def render_budgets(settings, fetch, persist):
    today = datetime.now(TAIPEI).date()
    groups = {g['id']: g for g in settings.get('project_groups', [])}
    accounts = {a['key']: a for a in settings['accounts']}
    plans = settings['projects']
    st.caption('專案走期、各平台廣告走期分開管理；花費累計完整廣告走期，含預熱，資料截至昨天（台灣時間）。')
    overview, edit = st.tabs(['預算總覽', '新增／編輯設定'])
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
        if not groups and not plans:
            st.info('先到「新增／編輯設定」建立專案，再分別加入 Meta、Google 投放計畫。')
        for gid, group in groups.items():
            if mode != '全部' and group['status'] != mode:
                continue
            children = [p for p in plans if p.get('group_id') == gid]
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
                    st.info('各平台廣告走期已結束。下方保留實際花費比例及結餘，不會自動補滿到 100%。')
                if not children:
                    st.caption('尚未加入平台投放計畫。請到設定頁加入 Meta 或 Google。')
                for plan in children:
                    render_plan(plan, accounts, results.get(plan['id']), today)
        ungrouped = [p for p in plans if not p.get('group_id') and (mode == '全部' or p['status'] == mode)]
        if ungrouped:
            st.subheader('既有平台計畫｜尚未歸入專案')
            st.caption('既有資料及異常規則連結均保留。可在設定頁編輯此計畫，指定所屬專案。')
            for plan in ungrouped:
                with st.container(border=True):
                    render_plan(plan, accounts, results.get(plan['id']), today)
        st.caption('進度＝實際花費 ÷ 平台投放預算。金額不另加稅與服務費，不等於儲值餘額。不同專案篩選可能重疊，因此不加總為全帳號花費。走期狀態依設定日期判斷，不代表平台即時開關狀態。')
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
            return f"{parent}｜{'Meta' if account['platform'] == 'meta' else 'Google Ads'}｜{p['name']}"
        plan_id = st.selectbox('選擇平台投放計畫', ['new'] + [p['id'] for p in plans],
                              format_func=lambda k: '＋新增平台計畫' if k == 'new' else label(k), key='budget_plan_editor')
        plan = next((p for p in plans if p['id'] == plan_id), {})
        # Keep existing ungrouped records editable without silently reassigning them.
        group_options = [''] + list(groups)
        with st.form('budget_plan_' + plan_id):
            owner = st.selectbox('所屬專案', group_options,
                                 index=group_options.index(plan.get('group_id', '')),
                                 format_func=lambda k: groups[k]['name'] if k else '尚未歸入專案（保留既有設定）', key='budget_plan_owner_' + plan_id)
            name = st.text_input('平台計畫名稱', plan.get('name', ''), placeholder='例如：感謝祭｜Meta（含預熱）')
            account_key = st.selectbox('廣告帳號', list(accounts),
                                      index=list(accounts).index(plan['account_key']) if plan else 0,
                                      format_func=lambda k: accounts[k]['name'], key='budget_plan_account_' + plan_id)
            a, b = st.columns(2)
            ad_start = a.date_input('廣告開始日（可含預熱）', date.fromisoformat(plan['start']) if plan else today)
            ad_end = b.date_input('廣告結束日', date.fromisoformat(plan['end']) if plan else today)
            budget = st.number_input('平台投放預算（與廣告帳號同幣別，不另加稅／服務費）', min_value=0., value=float(plan.get('budget', 0)), step=1000.)
            st.caption('0 代表預算尚未設定，總覽會顯示「未設定」，不會計算花費百分比。')
            options = ['campaign_name', 'adset_name', 'ad_name']
            field = st.selectbox('名稱歸類欄位', options, index=options.index(plan.get('match_field', 'campaign_name')),
                                 format_func=lambda k: {'campaign_name': '行銷活動名稱（Meta／Google）', 'adset_name': '廣告組合名稱（僅 Meta）', 'ad_name': '廣告名稱（僅 Meta）'}[k])
            keyword = st.text_input('名稱包含（必填）', plan.get('keyword', ''), placeholder='例如：感謝祭')
            st.caption('Google 請用行銷活動名稱，涵蓋搜尋與 PMax。先核對實際歸類明細，確認沒有漏算或混入其他專案。')
            status = st.selectbox('平台計畫狀態', ['進行中', '已結案'], index=int(plan.get('status') == '已結案'))
            st.caption('廣告結束日期會停止之後資料日的異常檢查，隔天仍會檢查最後一天；手動結案則立即停止檢查。')
            if st.form_submit_button('儲存平台計畫'):
                try:
                    if not owner and not plan:
                        raise AppError('請先建立並選擇所屬專案，再新增平台計畫。')
                    updated = save_plan(settings, {'id': plan.get('id', uuid.uuid4().hex), 'name': name.strip(),
                                                  'account_key': account_key, 'group_id': owner, 'start': str(ad_start),
                                                  'end': str(ad_end), 'budget': budget, 'match_field': field,
                                                  'keyword': keyword.strip(), 'status': status})
                    st.session_state.pending_budget_plan = next(p['id'] for p in updated['projects'] if p['id'] not in {x['id'] for x in plans}) if not plan else plan['id']
                    persist(updated, notice='平台計畫已儲存。回到預算總覽更新完整廣告走期花費。')
                except (AppError, ValueError) as exc:
                    st.error(str(exc))
        st.download_button('匯出設定備份（不含權杖）', json.dumps(settings, ensure_ascii=False, indent=2),
                           'mori-settings.json', on_click='ignore')


def render_plan(plan, accounts, result, today):
    account = accounts[plan['account_key']]
    platform = 'Meta' if account['platform'] == 'meta' else 'Google Ads'
    data = plan_summary(plan, result, today)
    st.markdown(f"#### {platform}｜{html.escape(plan['name'])}")
    st.caption(f"廣告走期　{plan['start']} ～ {plan['end']}　｜　{data['state']}")
    if result and result.get('error'):
        st.error(account['name'] + '：' + result['error'])
    a, b, c, d = st.columns(4)
    currency = data['currency'] or '帳號幣別'
    a.metric('平台預算', f"{data['budget']:,.2f}" if data['budget'] > 0 else '未設定')
    b.metric('累計花費', f"{data['spend']:,.2f}" if data['spend'] is not None else '—')
    c.metric('超支金額' if data['remaining'] is not None and data['remaining'] < 0 else '剩餘預算',
             f"{abs(data['remaining']):,.2f}" if data['remaining'] is not None and data['budget'] > 0 else '—')
    d.metric('花費進度', f"{data['ratio']:.1%}" if data['ratio'] is not None else '—')
    if data['ratio'] is not None:
        ratio, time_ratio = data['ratio'], data['time_ratio']
        color = '#c34236' if ratio > 1 else '#17421E'
        # Marker compares like-for-like: both include only completed data days.
        st.markdown(f'<div style="position:relative;height:12px;background:#e2e9df;border-radius:10px;margin:12px 0 8px">'
                    f'<div style="width:{max(0,min(100,ratio*100)):.3f}%;height:100%;background:{color};border-radius:10px"></div>'
                    f'<span style="position:absolute;left:{time_ratio*100:.3f}%;top:-3px;height:18px;width:2px;background:#869381;transform:translateX(-2px)"></span></div>', unsafe_allow_html=True)
        st.caption(f'花費 {ratio:.1%}｜灰線：截至資料日的廣告時間進度 {time_ratio:.1%}（平均投放參考，非硬性目標）')
        if ratio > 1:
            st.warning('已超過此平台預算，百分比保留實際值。')
    if result and result.get('until'):
        st.caption(f"{currency}｜資料區間 {result['since']} ～ {result['until']}｜帳號時區 {result.get('timezone') or '未回傳'}")
        with st.expander('核對實際歸類的廣告與花費'):
            rows = result['rows']
            if rows:
                df = pd.DataFrame(rows)
                columns = [k for k in ['date', 'campaign_name', 'adset_name', 'ad_name', 'spend', 'currency'] if k in df]
                st.dataframe(df[columns].rename(columns={'date': '日期', 'campaign_name': '活動', 'adset_name': '廣告組合',
                                                        'ad_name': '廣告', 'spend': '花費', 'currency': '幣別'}), hide_index=True, width='stretch')
            else:
                st.info('API 成功回傳，但此走期與名稱條件沒有符合的廣告。請核對篩選條件。')
    elif result and result.get('not_started'):
        st.caption('廣告尚未開始，尚未查詢花費。')
    else:
        st.caption('尚未取得實際花費；進度與結餘暫不計算。')
