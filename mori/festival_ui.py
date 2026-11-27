"""Whole-festival model UI, independent from overview query dates and close flags."""
import copy
import html
from datetime import datetime
from decimal import Decimal

import pandas as pd
import streamlit as st

from mori.core import AppError, TAIPEI
from mori.money_display import money_metric, money_table
from mori.festival_model import SNAPSHOT_PATH, refresh_snapshot, source_signature, projection
from mori.project_types import baseline_groups


def render_festival_model(settings, store, factory, persist):
    st.markdown('<div class="overview-hero"><div class="overview-eyebrow">FESTIVAL · INVESTMENT MODEL</div><h1>整檔投入，找到有效範圍。</h1><p>足球燒肉應援祭 × 感謝祭第5彈｜只使用廣告數據</p></div>',unsafe_allow_html=True)
    try:
        groups=baseline_groups(settings)
        signature=source_signature(settings)
    except AppError as exc:
        st.info(str(exc)+'。請先在專案預算核對專案名稱與分類。')
        return
    if store is None:
        st.info('私人模型儲存尚未就緒，暫時無法保存自動更新結果。')
        return
    settings_config=settings.get('festival_model',{})
    with st.expander('模型設定與更新方式'):
        with st.form('festival_model_config'):
            target=st.number_input('每多取得一個訂位，最多願意多花多少錢？（填 0 暫不判定上限）',min_value=0.,value=float(settings_config.get('target_cpa',0)),icon=':material/attach_money:')
            enabled=st.checkbox('啟用每日自動更新',value=settings_config.get('enabled',True))
            if st.form_submit_button('儲存模型設定'):
                updated=copy.deepcopy(settings)
                updated['festival_model']={'target_cpa':str(target),'enabled':enabled}
                persist(updated,notice='檔期模型設定已儲存。',keep_budget_view=True)
        st.write('後台每日台灣時間 09:15 排程抓取兩檔完整廣告走期；GitHub 排程可能延遲。無須開啟網站，也不依賴專案結案。')
        st.write('感謝祭若廣告走期到 11/18，就讀到 11/18；11/30 的活動檔期不會延長廣告取數。歷史日期的歸因回補仍會重讀。')
    try:
        snapshot,_=store.read(SNAPSHOT_PATH,{})
        refresh=st.button('立即更新兩檔模型',key='festival_refresh',type='primary',icon=':material/refresh:')
        # Initial model opening gets a first snapshot; later visits use saved data.
        if not snapshot and not refresh and not settings_config.get('enabled',True):
            st.info('自動更新已停用，可按立即更新建立快照。')
            return
        if refresh or not snapshot:
            with st.spinner('核對兩檔完整廣告走期、訂位認列與模型…'):
                snapshot=refresh_snapshot(store,settings,factory,force=refresh)
        if snapshot.get('last_error'):
            st.warning('最近一次更新未完成，保留上次結果：'+snapshot['last_error'])
        if not snapshot.get('projects'):
            st.info('尚無完整兩檔資料，暫不顯示預算建議。')
            return
        if snapshot.get('source_signature') != signature:
            st.info('認列條件或廣告計畫已變更；上次模型暫不使用，請立即更新或等待下一次排程。')
            return
    except AppError as exc:
        st.error(str(exc))
        return
    at=datetime.fromisoformat(snapshot['updated_at']).astimezone(TAIPEI).strftime('%Y/%m/%d %H:%M')
    st.caption('資料更新 '+at+'（台灣時間）｜模型排除今天與最近 3 天，避免近期回補干擾；3 天不代表平台結算完成。')
    table=[]
    for p in snapshot['projects']:
        table.append({'檔期':p['name'],'廣告走期':p['ad_start']+' — '+p['ad_end'],
                      '讀取至':p['read_through'],'最後有花費日':p['last_paid_date'] or '—',
                      '調整後預算':p['budget'],'整段花費':p['spend'],
                      '平台回報訂位':p['bookings'],
                      '整檔 CPA':Decimal(p['spend'])/Decimal(p['bookings']) if Decimal(p['bookings']) else None})
    money_table(st,pd.DataFrame(table),['combined']*len(table),{'調整後預算','整段花費','整檔 CPA'})
    st.caption('金額為廣告費，不含服務費與稅。平台回報訂位合計可能重複歸因，不等於去重人數、到店或營運收入。已包含專案內各類廣告，不只挑轉換活動。')
    fit=snapshot['fit']
    st.divider()
    st.subheader('檔期預算的甜蜜點與上限')
    if fit.get('status')!='estimated':
        for col,label in zip(st.columns(2),['檔期預算甜蜜點','檔期預算上限']):
            money_metric(col,label,None,empty='資料待驗證')
        st.info(fit.get('reason','尚無可信的擬合結果。'))
    else:
        projects={p['id']:p for p in snapshot['projects']}
        selected=st.selectbox('以哪一檔的規模與廣告天數推估',list(projects),format_func=lambda k:projects[k]['name'],key='festival_reference')
        reference=projects[selected]
        st.caption('以該檔已設定的廣告走期 '+str(reference['duration_days'])+' 天為基準，使用兩檔共同反應形狀與此檔的轉換規模。')
        result=projection(fit,selected,reference['duration_days'],float(settings_config.get('target_cpa',0)))
        a,b=st.columns(2)
        money_metric(a,'檔期預算甜蜜點（模型估計）',result['sweet']['budget'] if result['sweet'] else None,empty='尚未辨識最低點')
        money_metric(b,'檔期預算上限（模型估計）',result['upper']['budget'] if result['upper'] else None,empty='尚未辨識上限')
        if result['sweet']:
            money_metric(st,'甜蜜點的預估訂位 CPA',result['sweet']['cpa'])
        else:
            st.info('最低 CPA 落在已觀察花費範圍邊界，或曲線未形成內部最低點；不把邊界強稱甜蜜點。')
        if not result['upper']:
            st.info('尚未設定可接受邊際 CPA，或歷史投入範圍內未出現門檻交會；不外推一個確定上限。')
        indicator=st.radio('曲線指標',['預估平台回報訂位','平均 CPA','邊際 CPA'],horizontal=True,key='festival_curve')
        key={'預估平台回報訂位':'bookings','平均 CPA':'cpa','邊際 CPA':'marginal_cpa'}[indicator]
        chart=pd.DataFrame([{'檔期總花費（模型情境）':point['budget'],'估計值':point[key]} for point in result['curve']])
        st.vega_lite_chart(chart,{'height':300,'mark':{'type':'line','color':'#17421E','strokeWidth':3},
            'encoding':{'x':{'field':'檔期總花費（模型情境）','type':'quantitative','axis':{'format':'$,.0f'}},
                        'y':{'field':'估計值','type':'quantitative','title':indicator,'axis':{'format':',.0f' if key=='bookings' else '$,.2f'}},
                        'tooltip':[{'field':'檔期總花費（模型情境）','format':'$,.2f'},{'field':'估計值','format':',.2f'}]},
            'config':{'font':'Microsoft JhengHei','background':'transparent','view':{'stroke':None}}},width='stretch')
    with st.expander('模型方法、回測與認列核對'):
        st.write('以兩檔完整廣告專案逐日資料共同擬合 Hill 飽和曲線，各檔有獨立轉換規模。最後 25% 日期先留作回測；誤差過高、缺少投放強度變化或樣本不足時，不顯示預算建議。此為自建觀察模型，並非 Google Meridian。')
        st.write('預算甜蜜點＝模型範圍內平均 CPA 的內部最低點；預算上限＝效益遞減側的邊際 CPA 跨過可接受成本的交會點。只在已觀察日花費強度範圍內推估，未觀察到交會就顯示未知。')
        st.write('將每日花費強度換算成整檔預算，假設天數、平台分配、受眾、素材、優惠及競價環境可比；未控制這些混雜及延遲效應。模型結果是待驗證估計，不是加預算必然增加的訂位，也不是投資獲利率。')
        st.write(fit.get('reason',''))
        if fit.get('checks'): st.dataframe(pd.DataFrame(fit['checks']),hide_index=True)
        for p in snapshot['projects']:
            st.write(p['name']+'｜逐日花費與整段花費差額（保留原始 API 口徑）')
            money_metric(st,'花費核對差額',p['cost_difference'])
            st.caption('整檔表使用整段花費；擬合使用逐日花費。差異不會被悄悄分攤或抹平。')
            st.dataframe(pd.DataFrame(p['audit']),hide_index=True,width='stretch')
            st.dataframe(pd.DataFrame(p['rows']),hide_index=True,width='stretch')
