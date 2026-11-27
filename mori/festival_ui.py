"""Decision-first model workspace; presentation never changes the fitted data."""
import copy
import html
from datetime import datetime
from decimal import Decimal

import pandas as pd
import streamlit as st

from mori.core import AppError, TAIPEI
from mori.money_display import money_metric, money_table, money_html, styled_money_frame
from mori.festival_model import SNAPSHOT_PATH, refresh_snapshot, source_signature, projection
from mori.project_types import baseline_groups
from mori.design_system import (stylesheet, page_header, section_heading, insight_card,
                                history_card, empty_state)


def model_settings(settings, persist):
    config=settings.get('festival_model',{})
    with st.popover('模型設定',icon=':material/tune:',width='stretch'):
        st.markdown('**加碼成本與自動更新**')
        st.caption('上限的判斷標準：每多取得一個訂位，最多願意多花多少錢？')
        with st.form('festival_model_config'):
            target=st.number_input('可接受的加碼訂位成本',min_value=0.,value=float(config.get('target_cpa',0)),icon=':material/attach_money:',help='填 0 暫不判定預算上限；仍可查看甜蜜點與曲線。')
            enabled=st.checkbox('啟用每日自動更新',value=config.get('enabled',True))
            if st.form_submit_button('儲存模型設定',type='primary',width='stretch'):
                updated=copy.deepcopy(settings)
                updated['festival_model']={'target_cpa':str(target),'enabled':enabled}
                persist(updated,notice='檔期模型設定已儲存。',keep_budget_view=True)
        st.caption('每日台灣時間 09:15 更新，GitHub 排程可能延遲。只依廣告走期取數，不必開啟網站，也不需要標記結案。')


def response_chart(fit, selected, reference, result):
    """A precise chart with labelled decision markers, never decorative fake data."""
    st.markdown(section_heading('投入多少，訂位成本怎麼變？','切換指標，查看加碼後的效益變化。'),unsafe_allow_html=True)
    indicator=st.radio('曲線指標',['預估平台回報訂位','平均 CPA','邊際 CPA'],index=1,horizontal=True,key='festival_curve',label_visibility='collapsed')
    key={'預估平台回報訂位':'bookings','平均 CPA':'cpa','邊際 CPA':'marginal_cpa'}[indicator]
    chart=pd.DataFrame([{'budget':p['budget'],'value':p[key]} for p in result['curve']])
    value_format=',.1f' if key=='bookings' else '$,.2f'
    encoding={'x':{'field':'budget','type':'quantitative','title':'整檔廣告投入','axis':{'format':'$,.0f','tickCount':5,'labelPadding':12,'titlePadding':16}},
              'y':{'field':'value','type':'quantitative','title':indicator,'scale':{'zero':True},'axis':{'format':',.0f' if key=='bookings' else '$,.0f','tickCount':4,'titlePadding':16}},
              'tooltip':[{'field':'budget','title':'整檔投入','type':'quantitative','format':'$,.2f'},{'field':'value','title':indicator,'type':'quantitative','format':value_format}]}
    layers=[{'mark':{'type':'area','color':'#17421e','opacity':.055},'encoding':encoding},
            {'mark':{'type':'line','color':'#17421e','strokeWidth':3},'encoding':encoding}]
    markers=[]
    if result['sweet']: markers.append({'budget':result['sweet']['budget'],'label':'CPA 甜蜜點','color':'#a48652'})
    if result['upper']: markers.append({'budget':result['upper']['budget'],'label':'加碼上限','color':'#8c5d49'})
    if markers:
        layers.append({'data':{'values':markers},'mark':{'type':'rule','strokeDash':[5,5],'strokeWidth':1.5},
            'encoding':{'x':{'field':'budget','type':'quantitative'},'color':{'field':'color','scale':None,'legend':None},'tooltip':[{'field':'label','title':'判斷點'},{'field':'budget','title':'整檔投入','format':'$,.2f'}]}})
    st.vega_lite_chart(chart,{'height':310,'layer':layers,'config':{'font':'Microsoft JhengHei','background':'transparent','view':{'stroke':None},
        'axis':{'domain':False,'ticks':False,'gridColor':'#edf1e9','labelColor':'#71806b','titleColor':'#62705b','labelFontSize':11,'titleFontSize':12},'legend':{'labelColor':'#62705b'}}},width='stretch')
    legend='　 · 　'.join(('霧金虛線：CPA 甜蜜點' if m['label']=='CPA 甜蜜點' else '棕色虛線：加碼上限') for m in markers)
    st.caption((legend+'｜' if legend else '')+'曲線為模型估計，只顯示已觀察的投放強度範圍。')


def decision_panel(fit, reference, result, target):
    sweet=result.get('sweet');upper=result.get('upper')
    if fit.get('status')!='estimated':
        title='資料還在累積，先保留判斷。'
        body='尚未通過樣本或回測條件，暫不提供預算金額。'
    elif sweet and upper:
        title='先看效率，再決定加碼界線。'
        body='甜蜜點對應最低平均 CPA；超過上限後，新增訂位成本會跨過你設定的門檻。'
    elif sweet:
        title='已找到最低 CPA，上限繼續觀察。'
        body='可先參考甜蜜點的投入範圍。'+('設定可接受的加碼訂位成本後，才會判斷上限。' if target<=0 else '目前觀察範圍內，尚未找到符合成本門檻的上限。')
    else:
        title='目前沒有足夠證據，指定一個最佳預算。'
        body='曲線尚未出現可辨識的內部最低點。最低花費的邊界，不會直接被當成甜蜜點。'
    rows=[('推估基準',str(reference['duration_days'])+' 天廣告走期'),('加碼成本門檻',money_html(target) if target>0 else '尚未設定')]
    content=''.join('<div class="mori-decision-row"><span>'+html.escape(label)+'</span><strong>'+value+'</strong></div>' for label,value in rows)
    return ('<aside class="mori-decision-panel"><div class="eyebrow">HOW TO READ / 判斷重點</div><h3>'+html.escape(title)+'</h3><p>'+html.escape(body)+
            '</p>'+content+'<p class="footnote">模型估計會隨資料更新；不代表加碼後必然取得相同成果。</p></aside>')


def render_festival_model(settings, store, factory, persist):
    st.html(stylesheet())
    with st.container(key='festival_workspace'):
        st.markdown(page_header('檔期預算模型','用兩檔實際投放，找出最低 CPA 與加碼界線。','MORI / INVESTMENT MODEL'),unsafe_allow_html=True)
        try:
            baseline_groups(settings)
            signature=source_signature(settings)
        except AppError as exc:
            st.info(str(exc)+'。請先在專案預算核對專案名稱與分類。')
            return
        if store is None:
            st.markdown(empty_state('模型儲存尚未就緒','連線恢復後，才能保存與查看自動更新結果。'),unsafe_allow_html=True)
            return
        config=settings.get('festival_model',{})
        with st.container(key='festival_toolbar'):
            reference_control,settings_control,refresh_control=st.columns([2.6,1.05,1.05],vertical_alignment='bottom')
            with settings_control: model_settings(settings,persist)
            refresh=refresh_control.button('更新模型',key='festival_refresh',type='primary',icon=':material/refresh:',width='stretch')
        try:
            snapshot,_=store.read(SNAPSHOT_PATH,{})
            if not snapshot and not refresh and not config.get('enabled',True):
                st.markdown(empty_state('自動更新已暫停','按上方「更新模型」，建立第一份兩檔資料。'),unsafe_allow_html=True)
                return
            if refresh or not snapshot:
                with st.spinner('正在核對兩檔廣告數據與模型…'):
                    snapshot=refresh_snapshot(store,settings,factory,force=refresh)
            if snapshot.get('last_error'):
                st.warning('最近一次更新未完成，保留上次結果：'+snapshot['last_error'])
            if not snapshot.get('projects'):
                st.markdown(empty_state('尚無完整的兩檔資料','資料核對完成後，會在這裡呈現甜蜜點、上限與曲線。'),unsafe_allow_html=True)
                return
            if snapshot.get('source_signature')!=signature:
                st.info('認列條件或廣告計畫已變更；上次模型暫不使用，請更新模型或等待下一次排程。')
                return
        except AppError as exc:
            st.error(str(exc))
            return
        projects={p['id']:p for p in snapshot['projects']}
        selected=reference_control.selectbox('推估基準檔期',list(projects),format_func=lambda k:projects[k]['name'],key='festival_reference')
        reference=projects[selected]
        at=datetime.fromisoformat(snapshot['updated_at']).astimezone(TAIPEI).strftime('%m/%d %H:%M')
        enabled=config.get('enabled',True)
        st.markdown('<div class="mori-live-status"><span class="mori-status-inline'+('' if enabled else ' paused')+'">'+('每日自動更新' if enabled else '自動更新已暫停')+'</span><span>最近成功更新 '+html.escape(at)+' · 台灣時間</span></div>',unsafe_allow_html=True)
        fit=snapshot['fit'];target=float(config.get('target_cpa',0))
        result=projection(fit,selected,reference['duration_days'],target)
        sweet,upper=result['sweet'],result['upper']
        columns=st.columns([1.15,1.15,1])
        columns[0].markdown(insight_card('檔期預算甜蜜點',sweet['budget'] if sweet else None,'最低平均 CPA 對應的整檔投入。',focus=True,empty='尚未辨識最低點'),unsafe_allow_html=True)
        columns[1].markdown(insight_card('檔期預算上限',upper['budget'] if upper else None,'新增訂位成本跨過門檻前的投入界線。',empty='先設定成本門檻' if target<=0 else '尚未辨識上限'),unsafe_allow_html=True)
        columns[2].markdown(insight_card('甜蜜點的訂位 CPA',sweet['cpa'] if sweet else None,'與左側甜蜜點對應的預估成本。',empty='等待有效估計'),unsafe_allow_html=True)
        chart_column,read_column=st.columns([2.35,1],gap='large')
        with chart_column,st.container(key='festival_chart'):
            if fit.get('status')=='estimated': response_chart(fit,selected,reference,result)
            else:
                st.markdown(section_heading('先確認資料，再做預算判斷。'),unsafe_allow_html=True)
                st.markdown(empty_state('模型尚未通過驗證',fit.get('reason','尚無可用估計。')),unsafe_allow_html=True)
        read_column.markdown(decision_panel(fit,reference,result,target),unsafe_allow_html=True)
        st.markdown(section_heading('回到兩檔實際成績','以下是已認列的歷史數據，與上方模型估計分開查看。','HISTORY / 02'),unsafe_allow_html=True)
        for index,(column,p) in enumerate(zip(st.columns(2),snapshot['projects']),1):
            column.markdown(history_card(p,f'{index:02d}'),unsafe_allow_html=True)
        st.caption('金額為廣告費，不含服務費與稅。平台回報訂位可能重複歸因，不等於去重人數或到店人數。')
        with st.expander('資料期間與完整認列總表',icon=':material/table_chart:'):
            table=[]
            for p in snapshot['projects']:
                table.append({'檔期':p['name'],'廣告走期':p['ad_start']+' — '+p['ad_end'],'讀取至':p['read_through'],'最後有花費日':p['last_paid_date'] or '—',
                    '調整後預算':p['budget'],'整段花費':p['spend'],'平台回報訂位':p['bookings'],
                    '整檔 CPA':Decimal(p['spend'])/Decimal(p['bookings']) if Decimal(p['bookings']) else None})
            money_table(st,pd.DataFrame(table),['combined']*len(table),{'調整後預算','整段花費','整檔 CPA'})
            st.write('依各平台廣告走期取數，包含專案內各類廣告。感謝祭廣告若到 11/18，就讀到 11/18；活動到 11/30 不會延長廣告取數。結案後仍會重讀歷史回補。')
        with st.expander('模型方法、回測與數據核對',icon=':material/analytics:'):
            st.write('模型排除今天與最近 3 天，避免近期回補干擾；3 天不代表平台結算完成。成熟資料讀取至 '+snapshot.get('mature_through','—')+'。')
            st.write('兩檔逐日資料共同擬合 Hill 飽和曲線，各檔有獨立轉換規模；最後 25% 日期先留作回測。誤差過高、缺少投放強度變化或樣本不足時，不顯示預算建議。這是自建觀察模型，並非 Google Meridian。')
            st.write('甜蜜點＝已觀察範圍內平均 CPA 的內部最低點；上限＝效益遞減側的邊際 CPA 跨過可接受成本的交會點。未觀察到交會，就維持未知。')
            st.write('以每日花費強度換算整檔預算，假設天數、平台分配、受眾、素材、優惠及競價環境可比；未控制這些混雜及延遲效應。估計不是因果保證、去重訂位或營運投資報酬。')
            st.caption(fit.get('reason',''))
            if fit.get('checks'): st.dataframe(pd.DataFrame(fit['checks']).rename(columns={'id':'專案 ID','holdout_days':'回測天數','normalized_rmse':'標準化回測誤差'}),hide_index=True)
            for p in snapshot['projects']:
                st.markdown('**'+p['name'].replace('*','')+'**')
                money_metric(st,'逐日與整段花費核對差額',p['cost_difference'])
                st.caption('歷史總表採整段花費，曲線擬合採逐日花費；差異保留，不分攤抹平。下表保留原始金額精度，供追查。')
                st.dataframe(styled_money_frame(pd.DataFrame(p['audit']),{'daily_cost','whole_cost','difference'},raw=True),hide_index=True,width='stretch')
                st.dataframe(styled_money_frame(pd.DataFrame(p['rows']),{'spend'},raw=True),hide_index=True,width='stretch')
