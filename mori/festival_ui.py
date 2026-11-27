"""Current all-festival model and independently sourced retention capacity."""
import copy
import html
import statistics
from datetime import datetime,timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from mori.core import AppError,TAIPEI
from mori.money_display import money_metric,money_table,money_html,money_text,styled_money_frame
from mori.festival_model import (SNAPSHOT_PATH,refresh_snapshot,source_signature,current_projection,
                                build_models,observed_candidate)
from mori.project_types import festival_groups
from mori.retention_capacity import capacity_projection,source_catalog
from mori.design_system import stylesheet,page_header,section_heading,insight_card,history_card,empty_state


def font_check():
    components.html('''<style>@font-face{font-family:MoriLocalProbe;src:local("Microsoft JhengHei"),local("Microsoft JhengHei UI");}body{margin:0;font:16px "Microsoft JhengHei",sans-serif;color:#52634e;line-height:1.7}</style><div id="status">正在檢查本機字體…</div><script>document.fonts.load('16px MoriLocalProbe').then(f=>{document.getElementById('status').textContent=f.length?'本機已載入：微軟正黑體':'此裝置未提供微軟正黑體，目前使用系統替代字體。';}).catch(()=>{document.getElementById('status').textContent='此裝置未提供微軟正黑體，目前使用系統替代字體。';});</script>''',height=65)


def model_settings(settings,persist,scope,snapshot,factory):
    config=settings.get('festival_model',{})
    with st.popover('舊客量體來源',icon=':material/hub:',width='stretch'):
        st.markdown('**選擇計算來源，由模型推估預算。**')
        st.caption('這裡選廣告來源，不填預算上限。再行銷與品牌搜尋是舊客需求的代理指標，不等於確認過的舊客身分。')
        existing=config.get('capacity_scopes',{}).get(scope,{})
        selections={}
        for platform,label in [('meta','Meta 再行銷'),('google','Google 品牌搜尋')]:
            accounts={a['key']:a for a in settings['accounts'] if a['platform']==platform}
            if not accounts:
                st.info(label+'：尚未連接帳號。');continue
            old=existing.get(platform,{})
            keys=list(accounts);preferred=old.get('account_key')
            key=st.selectbox(label+'帳號',keys,index=keys.index(preferred) if preferred in keys else 0,format_func=lambda k:accounts[k]['name'],key=f'cap_account_{scope}_{platform}')
            cachekey='capacity_catalog_'+key
            catalog=st.session_state.get(cachekey,snapshot.get('source_catalogs',{}).get(key,{}))
            if st.button('讀取'+label+'來源清單',key=f'cap_catalog_{scope}_{platform}'):
                try:
                    catalog={'rows':source_catalog(factory(accounts[key]),accounts[key])};st.session_state[cachekey]=catalog
                except AppError as exc: st.warning(str(exc))
            if catalog.get('error'): st.warning(catalog['error'])
            entries={r['id']:r for r in catalog.get('rows',[])}
            defaults=old.get('ids',[]) if old.get('account_key')==key else []
            for identifier in defaults: entries.setdefault(identifier,{'id':identifier,'name':'已儲存來源'})
            def source_label(identifier):
                row=entries[identifier]
                return (row.get('campaign_name','')+'｜' if row.get('campaign_name') else '')+row.get('name','')+' · '+identifier
            chosen=st.multiselect(label+'廣告來源',list(entries),default=defaults,format_func=source_label,key=f'cap_sources_{scope}_{platform}')
            if chosen: selections[platform]={'account_key':key,'ids':chosen}
        enabled=st.checkbox('啟用自動更新',value=config.get('enabled',True),key='festival_enabled')
        if st.button('儲存來源並於下次更新計算',key='festival_save_sources',type='primary',width='stretch'):
            updated=copy.deepcopy(settings);new=updated.setdefault('festival_model',{})
            new.pop('target_cpa',None);new['enabled']=enabled
            new.setdefault('capacity_scopes',{})[scope]=selections
            persist(updated,notice='舊客廣告來源已儲存；請更新模型讀取量體。',keep_budget_view=True)
        st.caption('Meta 來源會核對自訂受眾與擴展設定；不同受眾不直接相加。Google 來源會核對品牌關鍵字、地區與重複變體。API 缺值時會保留缺口，不當成零。')
        with st.expander('本機字體檢查'): font_check()


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
    if result.get('candidate') and not result['sweet']: markers.append({'budget':result['candidate']['budget'],'label':'當下較佳投入','color':'#8c5d49'})
    if markers:
        layers.append({'data':{'values':markers},'mark':{'type':'rule','strokeDash':[5,5],'strokeWidth':1.5},
            'encoding':{'x':{'field':'budget','type':'quantitative'},'color':{'field':'color','scale':None,'legend':None},'tooltip':[{'field':'label','title':'判斷點'},{'field':'budget','title':'整檔投入','format':'$,.2f'}]}})
    st.vega_lite_chart(chart,{'height':380,'layer':layers,'config':{'font':'Microsoft JhengHei','background':'transparent','view':{'stroke':None},
        'axis':{'domain':False,'ticks':False,'gridColor':'#edf1e9','labelColor':'#71806b','titleColor':'#62705b','labelFontSize':16,'titleFontSize':17},'legend':{'labelColor':'#62705b'}}},width='stretch')
    legend='　 · 　'.join(('霧金虛線：CPA 甜蜜點' if m['label']=='CPA 甜蜜點' else '棕色虛線：當下較佳投入（尚待驗證）') for m in markers)
    st.caption((legend+'｜' if legend else '')+'曲線為模型估計，只顯示已觀察的投放強度範圍。')


def _reference(snapshot,models,selected,days):
    projects=snapshot['projects']
    if selected!='all':
        project=next(p for p in projects if p['id']==selected)
        fit=models['individual'][selected]
        return project,fit,current_projection(fit,project,days)
    reference={'id':'all','name':'全部檔期集合模型','duration_days':days,'rows':[]}
    fit=models['aggregate']['fit'];result=current_projection(fit,reference,days)
    if not result.get('candidate'):
        candidates=[current_projection(models['individual'][p['id']],p,days).get('candidate') for p in projects]
        candidates=sorted([c for c in candidates if c],key=lambda c:c['cpa'])
        if candidates: result['candidate']={**candidates[len(candidates)//2],'basis':'pooled_observation'}
    return reference,fit,result


def render_festival_model(settings,store,factory,persist):
    st.html(stylesheet())
    with st.container(key='festival_workspace'):
        st.markdown(page_header('檔期投放決策','集合全部檔期，估計舊客承接上限與當下較佳投入。','MORI / CAMPAIGN INTELLIGENCE'),unsafe_allow_html=True)
        try:
            groups=festival_groups(settings);signature=source_signature(settings)
        except AppError as exc:
            st.info(str(exc));return
        if store is None:
            st.markdown(empty_state('模型儲存尚未就緒','連線恢復後才能保存自動更新結果。'),unsafe_allow_html=True);return
        config=settings.get('festival_model',{})
        try: snapshot,_=store.read(SNAPSHOT_PATH,{})
        except AppError as exc: st.error(str(exc));return
        old_projects=snapshot.get('projects',[])
        valid=['all']+[p['id'] for p in old_projects]
        if st.session_state.get('festival_reference') not in valid: st.session_state.festival_reference='all'
        with st.container(key='festival_toolbar'):
            choose,horizon,source,update=st.columns([2.4,.85,1.1,1.05],vertical_alignment='bottom')
            selected=choose.selectbox('模型範圍',valid,format_func=lambda k:'全部檔期集合模型' if k=='all' else next(p['name'] for p in old_projects if p['id']==k),key='festival_reference')
            default_days=round(statistics.median(p['duration_days'] for p in old_projects)) if old_projects else 60
            if selected!='all': default_days=next(p['duration_days'] for p in old_projects if p['id']==selected)
            days=int(horizon.number_input('推估廣告天數',min_value=1,max_value=365,value=max(1,min(365,default_days)),key='festival_days_'+selected))
            with source: model_settings(settings,persist,selected,snapshot,factory)
            refresh=update.button('更新模型',key='festival_refresh',type='primary',icon=':material/refresh:',width='stretch')
        try:
            stale=bool(snapshot.get('version')) and (snapshot.get('source_signature')!=signature or not snapshot.get('updated_at') or datetime.now(TAIPEI)-datetime.fromisoformat(snapshot['updated_at'])>timedelta(hours=1))
            if refresh or (config.get('enabled',True) and (not snapshot or stale)):
                with st.spinner('正在更新全部檔期、舊客量體與當下模型…'): snapshot=refresh_snapshot(store,settings,factory,force=refresh)
            if snapshot.get('last_error'): st.warning('最近一次更新未完成，保留上次資料：'+snapshot['last_error'])
            if snapshot.get('source_signature')!=signature:
                if snapshot.get('projects'): st.info('這是上次資料；檔期或來源已變更。更新成功前不沿用舊建議。')
                else: st.info('尚無完整的檔期資料，請更新模型。')
                return
            projects=snapshot.get('projects',[])
            if not projects:
                st.markdown(empty_state('尚無可用的廣告資料','尚未開始投放的檔期不會被當成零成果。'),unsafe_allow_html=True);return
            # New projects become selectable on the next native rerun; never mutate a rendered widget.
            if selected!='all' and selected not in {p['id'] for p in projects}: selected='all'
        except AppError as exc: st.error(str(exc));return
        models=snapshot.get('models') or build_models(projects,snapshot.get('mature_through','9999-12-31'))
        reference,fit,result=_reference(snapshot,models,selected,days)
        capacity=capacity_projection(snapshot.get('capacities',{}).get(selected,{}),days)
        at=datetime.fromisoformat(snapshot['updated_at']).astimezone(TAIPEI).strftime('%m/%d %H:%M')
        st.markdown('<div class="mori-live-status"><span class="mori-status-inline">'+str(len(projects))+' 檔資料 · 可擬合 '+str(len(models['aggregate']['included_ids']))+' 檔 · '+('集合體模型' if selected=='all' else html.escape(reference['name']))+'</span><span>更新 '+at+' · 讀取至 '+max(p['read_through'] for p in projects)+'</span></div>',unsafe_allow_html=True)
        candidate=result.get('candidate');basis=candidate.get('basis') if candidate else None
        label={'model_interior':'模型估計','model_boundary':'邊界暫估','historical_observation':'歷史觀察','pooled_observation':'歷史中位參考'}.get(basis,'資料累積中')
        left,right,third=st.columns([1.25,1.15,1])
        note='Meta 再行銷＋Google 品牌搜尋，以目前可承接量體推估。'
        if capacity['status']=='estimated': note='量體範圍 '+money_text(capacity['lower'])+' — '+money_text(capacity['upper'])+'；不是獲利保證。'
        left.markdown(insight_card('舊客保底預算上限',capacity['upper'],note,focus=True,empty='量體來源待核對',tag='量體推估'),unsafe_allow_html=True)
        candidate_note='模型最低點、範圍邊界與歷史觀察會清楚區分。'
        if candidate and candidate.get('since'): candidate_note='歷史觀察 '+candidate['since']+' — '+candidate['until']+'；按所選天數換算，不是未來保證。'
        right.markdown(insight_card('當下較佳檔期投入',candidate['budget'] if candidate else None,candidate_note,empty='目前尚無有效訂位',tag=label),unsafe_allow_html=True)
        third.markdown(insight_card('對應訂位 CPA',candidate['cpa'] if candidate else None,'對應中間投入金額；不是整檔實際平均 CPA。',empty='尚無可計算訂位',tag=label),unsafe_allow_html=True)
        st.markdown('<div class="model-diagnosis"><strong>現在怎麼判斷</strong><p>'+html.escape(result['diagnosis'])+'</p></div>',unsafe_allow_html=True)
        with st.container(key='festival_chart'):
            if result['curve']: response_chart(fit,selected,reference,result)
            else:
                st.markdown(section_heading('當下已觀察到的投放','模型尚未通過驗證時，先看實際花費與訂位，不畫假預測。'),unsafe_allow_html=True)
                observations=[]
                for p in projects if selected=='all' else [reference]:
                    for row in p['rows']:
                        if Decimal(row['spend'])>0: observations.append({'檔期':p['name'],'日花費':float(row['spend']),'平台回報訂位':float(row['bookings']),'日期':row['date']})
                if observations:
                    st.vega_lite_chart(pd.DataFrame(observations),{'height':360,'mark':{'type':'circle','size':75,'opacity':.65},'encoding':{'x':{'field':'日花費','type':'quantitative','axis':{'format':'$,.0f'}},'y':{'field':'平台回報訂位','type':'quantitative'},'color':{'field':'檔期','type':'nominal'},'tooltip':[{'field':'檔期'},{'field':'日期'},{'field':'日花費','format':'$,.2f'},{'field':'平台回報訂位'}]},'config':{'font':'Microsoft JhengHei','axis':{'labelFontSize':16,'titleFontSize':17},'view':{'stroke':None},'background':'transparent'}},width='stretch')
                else: st.info('已有廣告資料，但目前尚無花費觀測點。')
        st.markdown(section_heading('舊客量體上限，怎麼算出來？','只用已核對來源；單一平台讀取失敗，不以部分金額冒充雙平台上限。'),unsafe_allow_html=True)
        for platform,column in zip(('meta','google'),st.columns(2)):
            row=capacity['platforms'][platform]
            with column,st.container(border=True):
                st.subheader('Meta 再行銷' if platform=='meta' else 'Google 品牌搜尋')
                if row['status']=='estimated':
                    money_metric(st,'可承接廣告費上限',row['upper'],platform)
                    st.write(row['source']['basis'])
                    if platform=='meta': st.caption('目前母體 '+row['source']['audience_lower']+' — '+row['source']['audience_upper']+'；頻次與 CPM 校準 '+row['source']['since']+' — '+row['source']['until'])
                    else: st.caption('平均月搜尋量 '+row['source']['monthly_searches']+'；'+str(len(row['source']['keywords']))+' 個關鍵字；校準 '+row['source']['since']+' — '+row['source']['until'])
                else: st.info(row['reason'])
        st.caption('再行銷與品牌搜尋是舊客需求代理，不等於已確認舊客。新客4：舊客6是人數／訂位規劃比例，不能直接把舊客預算除以60%當成總預算；還需已辨識的新、舊客 CPA。')
        st.markdown(section_heading('各檔實績與模型狀態','集合體使用可驗證樣本；新檔或暫估檔不會消失，也不會拖垮其他已驗證檔期。'),unsafe_allow_html=True)
        for offset in range(0,len(projects),2):
            for column,p in zip(st.columns(2),projects[offset:offset+2]):
                column.markdown(history_card(p,('暫估' if models['individual'][p['id']]['status']!='estimated' else '可擬合')),unsafe_allow_html=True)
        with st.expander('查看集合體納入狀態與各檔診斷',icon=':material/analytics:'):
            st.dataframe(pd.DataFrame(models['aggregate']['diagnostics']).rename(columns={'name':'檔期','status':'模型狀態','reason':'原因'}),hide_index=True,width='stretch')
            st.write('集合體先將各檔日花費與訂位規模正規化，再等權學習反應形狀，最後換回歷史中位規模；不是把兩檔預算直接相加。')
            st.write('個別檔期各自擬合。資料包含今天的即時回報，曲線訓練避開今天及前三天；結案狀態不參與篩選，歷史回補仍持續更新。')
            st.write('若最低值落在資料邊界，呈現邊界暫估；若樣本或回測未通過，顯示較佳七日觀察區間。這些都不會偽裝成已驗證的全域最低點。')
        with st.expander('資料期間、金額與認列核對',icon=':material/table_chart:'):
            table=[{'檔期':p['name'],'廣告開始':p['ad_start'],'廣告結束':p['ad_end'],'讀取至':p['read_through'],'實際花費':p['spend'],'平台回報訂位':p['bookings'],'逐日與整段差額':p['cost_difference']} for p in projects]
            money_table(st,pd.DataFrame(table),['combined']*len(table),{'實際花費','逐日與整段差額'})
            st.caption('金額為未稅廣告費，不含服務費；平台訂位可能跨平台重複歸因，不等於實際去重訂位或到店人數。')
            for p in projects:
                st.markdown('**'+p['name'].replace('*','')+'**')
                st.dataframe(styled_money_frame(pd.DataFrame(p['audit']),{'daily_cost','whole_cost','difference'},raw=True),hide_index=True,width='stretch')
