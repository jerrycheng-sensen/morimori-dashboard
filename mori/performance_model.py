"""Comparable metric views and observational spend-response analysis.

No causal optimum, customer identity, audience capacity or revenue is inferred.
All analysis reuses the current report snapshot and never changes ad budgets.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st

from mori.core import TAIPEI
from mori.money_display import money_metric, money_table, money_text

META_TYPES = {
    'OUTCOME_AWARENESS':'曝光', 'BRAND_AWARENESS':'曝光', 'REACH':'曝光', 'LOCAL_AWARENESS':'曝光',
    'OUTCOME_ENGAGEMENT':'互動', 'POST_ENGAGEMENT':'互動', 'PAGE_LIKES':'互動', 'EVENT_RESPONSES':'互動',
    'OUTCOME_TRAFFIC':'流量', 'LINK_CLICKS':'流量',
    'OUTCOME_SALES':'轉換', 'CONVERSIONS':'轉換', 'PRODUCT_CATALOG_SALES':'轉換',
    'OUTCOME_LEADS':'轉換', 'LEAD_GENERATION':'轉換',
}


def campaign_type(row):
    if row['platform'] == 'meta':
        return META_TYPES.get(row.get('campaign_objective'), '待分類／其他目標')
    return {'SEARCH':'搜尋','PERFORMANCE_MAX':'PMax'}.get(row.get('channel'), '其他類型')


def ratio(numerator, denominator):
    return numerator / denominator if numerator is not None and denominator and denominator > 0 else None


def known_sum(frame, field):
    if field not in frame or frame[field].isna().any():
        return None
    return sum((Decimal(str(v)) for v in frame[field]), Decimal(0))


def metric_bundle(frame):
    from mori.dashboard import totals
    metric = totals(frame)
    impressions = known_sum(frame,'impressions')
    clicks = known_sum(frame,'clicks')
    field = 'engagements' if set(frame.platform.unique()) == {'meta'} else 'interactions'
    interaction = known_sum(frame,field)
    return {**metric, 'impressions':impressions,'clicks':clicks,'interactions':interaction,
            'cpm':ratio(metric['spend']*1000,impressions), 'cpc':ratio(metric['spend'],clicks),
            'cpe':ratio(metric['spend'],interaction), 'ctr':ratio(clicks,impressions),
            'interaction_rate':ratio(interaction,impressions),
            'booking_click_rate':ratio(Decimal(str(metric['bookings'])) if metric['bookings'] is not None else None,clicks)}


def display_number(value):
    return '—' if value is None else f'{value:,.2f}'.rstrip('0').rstrip('.')


def display_rate(value):
    return '—' if value is None else f'{value*100:.2f}%'


def comparative_rows(frame, by_campaign=False):
    """Ratios use summed numerators/denominators, never average row rates."""
    frame = frame.copy()
    frame['activity_type'] = [campaign_type(row) for row in frame.to_dict('records')]
    group_fields = ['account_key','platform','currency','campaign_id','campaign_name','activity_type'] if by_campaign else ['platform','currency','activity_type']
    output = []
    for key, part in frame.groupby(group_fields,dropna=False):
        platform = part.platform.iloc[0]
        kind = part.activity_type.iloc[0]
        metric = metric_bundle(part)
        main = {'曝光':('CPM','cpm'),'互動':('每次貼文互動成本','cpe'),
                '流量':('連結 CPC','cpc'),'轉換':('訂位 CPA','cpa'),
                '搜尋':('訂位 CPA','cpa'),'PMax':('訂位 CPA','cpa')}.get(kind,('未分類',None))
        row = {'類型':kind, '幣別':part.currency.iloc[0], '活動數':part[['account_key','campaign_id']].drop_duplicates().shape[0],
               '主要觀察':main[0], '主要成本':metric.get(main[1]), '花費':metric['spend'],
               '曝光次數':display_number(metric['impressions']), '互動次數':display_number(metric['interactions']),
               '互動率':display_rate(metric['interaction_rate']), '點擊數':display_number(metric['clicks']),
               'CTR':display_rate(metric['ctr']), '平台回報訂位':display_number(metric['bookings']),
               '點擊訂位率':display_rate(metric['booking_click_rate']),
               'CPM':metric['cpm'],'互動成本':metric['cpe'],'CPC':metric['cpc'],'訂位 CPA':metric['cpa'], '_platform':platform}
        if by_campaign:
            row.update({'活動':str(part.campaign_name.iloc[0]),'活動 ID':str(part.campaign_id.iloc[0]),
                        '_account':part.account_key.iloc[0]})
        output.append(row)
    return output


def spend_response(frame, through, target_cpa=0, min_days=7, min_bookings=20):
    """Three observed daily spend bands within one account/campaign/currency.

    Adjacent-band slopes describe associations; no randomized/control evidence
    is available here, so an upper candidate can never be a confirmed optimum.
    """
    from mori.dashboard import totals
    identities = frame[['account_key','campaign_id','currency']].drop_duplicates()
    if len(identities) != 1:
        return {'status':'請先選擇同一帳號、同一活動及幣別。','bands':[],'upper':None,'best':None}
    mature = frame[frame.date.astype(str) <= str(through)]
    days = []
    for day, part in mature.groupby('date'):
        metric = totals(part)
        if metric['bookings'] is None or metric['bookings'] < 0:
            return {'status':'訂位資料缺漏或有負向調整，暫不推算。','bands':[],'upper':None,'best':None}
        if metric['spend'] < 0:
            return {'status':'花費有負向調整，暫不推算。','bands':[],'upper':None,'best':None}
        if metric['spend'] > 0:
            days.append({'date':str(day),'spend':metric['spend'],'bookings':Decimal(str(metric['bookings']))})
    if not days:
        return {'status':'尚無符合觀察期的完整投放資料。','bands':[],'upper':None,'best':None}
    daily = pd.DataFrame(days)
    labels = pd.qcut(daily.spend.astype(float),3,duplicates='drop')
    daily['band'] = labels
    bands = []
    for _, part in daily.groupby('band', observed=True):
        spend, bookings = sum(part.spend), sum(part.bookings)
        bands.append({'days':len(part),'bookings':bookings,'spend':spend,
                      'low':min(part.spend),'high':max(part.spend),'mean_spend':spend/len(part),
                      'mean_bookings':bookings/len(part),'cpa':ratio(spend,bookings),
                      'eligible':len(part)>=min_days and bookings>=min_bookings})
    bands.sort(key=lambda b:b['mean_spend'])
    for index, band in enumerate(bands):
        band['marginal_cpa'] = None
        band['plateau'] = False
        if index:
            old = bands[index-1]
            ds = band['mean_spend']-old['mean_spend']
            db = band['mean_bookings']-old['mean_bookings']
            band['marginal_cpa'] = ds/db if ds>0 and db>0 else None
            band['plateau'] = ds>0 and db<=0
    enough = len(daily)>=28 and len(bands)==3 and all(b['eligible'] for b in bands)
    eligible = [b for b in bands if b['eligible'] and b['cpa'] is not None]
    best = min(eligible,key=lambda b:b['cpa']) if enough and eligible else None
    upper = None
    if enough and target_cpa > 0:
        for index, band in enumerate(bands[1:],1):
            previous = bands[index-1]
            if previous['cpa'] is not None and previous['cpa'] <= target_cpa and (band['plateau'] or band['marginal_cpa'] is not None and band['marginal_cpa'] > target_cpa):
                upper = previous
                break
    status = ('樣本不足：至少 28 個成熟投放日，且每個花費帶達到設定的天數與訂位門檻。' if not enough else
              '已找到上限觀察候選，仍須可比試投驗證。' if upper else
              '請先設定可接受 CPA，才能判斷上限候選。' if target_cpa<=0 else
              '尚未找到上限：已觀察範圍沒有符合判準的明確遞減，不代表可無限加碼。')
    return {'status':status,'bands':bands,'upper':upper,'best':best,'days':len(daily)}


def acquisition_plan(old_bookings, new_cpa):
    old_bookings, new_cpa = Decimal(str(old_bookings)),Decimal(str(new_cpa))
    if old_bookings<=0 or new_cpa<=0:
        return None
    new_bookings = old_bookings*Decimal(4)/Decimal(6)
    return {'new_bookings':new_bookings,'new_budget':new_bookings*new_cpa}


def direct_reach(reports, account_key, campaign_id, period):
    values=[]
    for report in reports:
        if report.get('account_key') != account_key: continue
        for item in report.get('reach_metrics',[]):
            if item.get('scope')=='campaign' and item.get('campaign_id')==str(campaign_id) and (item.get('since'),item.get('until'))==tuple(map(str,period)):
                values.append(item.get('reach'))
    return values[0] if len(values)==1 else None


def render_activity_comparison(frame, view, full_account_scope, missing_platforms=None):
    st.divider()
    st.subheader('各類廣告，分開看效益')
    st.caption('每種類型都有曝光、點擊與訂位；主要成本不同。比較前請確認地區、受眾、走期及投放量接近，不能只憑單一成本直接換掉活動。')
    for platform in ('meta','google'):
        if platform in (missing_platforms or set()):
            st.warning(('Meta' if platform=='meta' else 'Google Ads')+' 帳號尚未完整讀取，暫不顯示類型合計。')
            continue
        part = frame[frame.platform==platform]
        if part.empty: continue
        st.markdown('### '+('Meta｜曝光・互動・流量・轉換' if platform=='meta' else 'Google Ads｜搜尋・PMax'))
        data = comparative_rows(part)
        table = pd.DataFrame([{k:v for k,v in row.items() if not k.startswith('_')} for row in data])
        money_table(st,table[['類型','活動數','花費','CPM','互動成本','CPC','訂位 CPA']],[platform]*len(table),{'花費','CPM','互動成本','CPC','訂位 CPA'})
        st.caption('核心觀察：曝光看 CPM、互動看互動成本、流量看 CPC、轉換看訂位 CPA。' if platform=='meta' else '搜尋與 PMax 分開比較；主要看訂位 CPA，再看 CPC、CPM 與轉換量。')
        st.caption('Meta：互動為貼文互動，點擊為連結點擊。' if platform=='meta' else 'Google：互動為主要互動（可能為點擊或影片觀看），與 Meta 貼文互動不同，不跨平台直接比較互動率。')
        with st.expander(('Meta' if platform=='meta' else 'Google Ads')+' 曝光、互動、點擊、訂位與活動明細'):
            money_table(st,table,[platform]*len(table),{'主要成本','花費','CPM','互動成本','CPC','訂位 CPA'})
            detailed = comparative_rows(part,True)
            for row in detailed:
                row['整段觸及人數'] = display_number(direct_reach(view['reports'],row['_account'],row['活動 ID'],view['period'])) if full_account_scope and platform=='meta' else '—'
            money_table(st,pd.DataFrame([{k:v for k,v in row.items() if not k.startswith('_')} for row in detailed]),[platform]*len(detailed),{'主要成本','花費','CPM','互動成本','CPC','訂位 CPA'})
        if platform=='meta':
            for report in view['reports']:
                if not full_account_scope: break
                key=report.get('account_key')
                if key not in set(part.account_key): continue
                values=[r.get('reach') for r in report.get('reach_metrics',[]) if r.get('scope')=='account' and (r.get('since'),r.get('until'))==tuple(view['period'])]
                if len(values)==1:
                    st.write('帳號 '+str(report.get('account_name') or key)+'｜本次整段觸及 '+display_number(values[0])+' 人（同帳號、同期間去重）')
    with st.expander('指標計算方式與觸及限制'):
        st.write('CPM＝花費÷曝光次數×1,000；CPC＝花費÷點擊；CTR＝點擊÷曝光；互動率＝此平台互動次數÷曝光；點擊訂位率＝指定訂位事件÷點擊。各率由合計分子／分母計算，不平均每日百分比。')
        st.write('「點擊訂位率」是本頁自訂口徑，不等同 Google 後台可能以主要互動為分母的轉換率；歸因訂位可能含瀏覽後轉換或跨日回補，不視為同一批點擊的實際漏斗。')
        st.write('觸及人數只使用 API 直接回傳的相同活動／帳號整段資料；不加總每日、跨活動或跨平台人數。Google 搜尋／PMax 本版未讀取可比的去重觸及；專案篩選也不套用整個活動的觸及。未提供時顯示 —。')
        st.write('Meta 依 API 活動目標分類，不以名稱猜測；其他目標或未讀到目標會保留為待分類。轉換類包含銷售與名單目標，訂位仍只計帳號設定的事件。')


def render_sweet_spot(frame, view):
    st.divider()
    st.subheader('預算上限與 CPA 甜蜜點')
    st.caption('看「多花錢，多取得多少訂位」。每次按讀取數據後更新；歷史樣本採本次查詢區間，建議用近 90 天，再限定相同檔期與活動。')
    st.caption('先以同一活動建立觀察；整檔總預算上限仍需固定分配比例的專案試投資料，不能把各活動候選值直接相加。')
    mode=st.radio('模型檢視',['投入與邊際效益','新舊客 4:6 試算'],horizontal=True,key='model_mode')
    if mode=='新舊客 4:6 試算':
        st.write('這是訂位量的規劃比例，不是已驗證的新舊客比例，也不是預算 40%／60%。')
        st.caption('目前以有效訂位數作來客比例的代理試算；若每組人數或到店率不同，不能直接當成實際新舊客來客比。')
        a,b=st.columns(2)
        old=a.number_input('同期間舊客有效訂位預估（須先去重）',min_value=0.,value=0.,key='model_old_bookings')
        cpa=b.number_input('新客訂位 CPA 假設',min_value=0.,value=0.,icon=':material/attach_money:',key='model_new_cpa')
        plan=acquisition_plan(old,cpa)
        if plan:
            a,b=st.columns(2)
            a.metric('新客訂位目標（推估）',display_number(plan['new_bookings']))
            money_metric(b,'新客加碼預算（推估）',plan['new_budget'])
        st.caption('新客訂位目標＝舊客訂位預估×4÷6；新客加碼預算＝新客訂位目標×新客 CPA。金額未含服務費與稅，不保證達成。')
        with st.expander('受眾人數、品牌搜尋量要怎麼換算？'):
            st.write('Meta 再行銷受眾人數需再估可觸及比例、點擊與有效訂位率；品牌搜尋量需估可取得曝光、CTR 與有效訂位率。兩者不能直接相加，且要先排除重複訂位。')
            st.write('目前 API 未串接受眾可承接量、品牌關鍵字需求預估與跨平台去重的新舊客身分；本區需自行填入同期間、同單位的舊客訂位預估與新客 CPA，不能把全部轉換都當成新客。')
        return
    choices=frame[['account_key','platform','currency','campaign_id','campaign_name']].drop_duplicates(['account_key','platform','currency','campaign_id'],keep='last')
    options=list(range(len(choices)))
    if not options: return
    if st.session_state.get('model_campaign') not in options:
        st.session_state.pop('model_campaign',None)
    selected=st.selectbox('觀察哪個活動',options,format_func=lambda i:('Meta' if choices.iloc[i].platform=='meta' else 'Google Ads')+'｜'+str(choices.iloc[i].campaign_name)+'｜'+str(choices.iloc[i].campaign_id),key='model_campaign')
    identity=choices.iloc[selected]
    part=frame[(frame.account_key==identity.account_key)&(frame.campaign_id==identity.campaign_id)&(frame.currency==identity.currency)]
    if identity.currency!='TWD': st.write('帳號幣別：'+str(identity.currency))
    with st.expander('觀察條件與可接受 CPA',expanded=True):
        a,b,c=st.columns(3)
        target=a.number_input('可接受的訂位 CPA 上限',min_value=0.,value=0.,icon=':material/attach_money:',key='model_target_cpa',help='請依有效到店、收入與毛利決定；未填不判定上限候選。')
        lag=b.number_input('排除最近幾天的資料',min_value=1,max_value=30,value=3,step=1,key='model_lag',help='避免近期轉換尚未回補；3 天只是可調整的觀察設定，不代表平台結算完成。')
        minimum=c.number_input('每個花費帶至少幾個投放日',min_value=3,max_value=60,value=7,step=1,key='model_min_days')
        conversions=st.number_input('每個花費帶至少幾次訂位',min_value=1,max_value=1000,value=20,step=1,key='model_min_bookings')
    through=datetime.now(TAIPEI).date()-timedelta(days=int(lag)+1)
    result=spend_response(part,through,Decimal(str(target)),int(minimum),int(conversions))
    st.write(result['status'])
    end=min(str(through),view['period'][1])
    st.caption(('採用 '+str(view['period'][0])+' 至 '+end+' 的本次 API 資料。' if end>=str(view['period'][0]) else '本次查詢尚未包含符合成熟期設定的資料。')+' 排除最近 '+str(lag)+' 天及今天；樣本門檻是操作護欄，不代表統計上已證明。')
    if not result['bands']: return
    platform='meta' if identity.platform=='meta' else 'google'
    a,b=st.columns(2)
    best=result['best']; upper=result['upper']
    money_metric(a,'最低觀察 CPA（非保證）',best['cpa'] if best else None,platform,empty='樣本不足')
    b.markdown('**日花費上限觀察候選**')
    if upper:
        st.write(money_text(upper['low'],platform).replace('$',r'\$')+' — '+money_text(upper['high'],platform).replace('$',r'\$'))
        st.caption('這是實際花費範圍，尚不是已驗證的設定預算或整檔預算上限。')
    else:
        st.write('尚未找到上限')
    table=[]
    for index,band in enumerate(result['bands']):
        table.append({'花費帶':str(index+1),'日花費下緣':band['low'],'日花費上緣':band['high'],
                      '投放日數':band['days'],'平台回報訂位':display_number(band['bookings']),
                      '平均日花費':band['mean_spend'],'平均每日訂位':display_number(band['mean_bookings']),
                      '平均 CPA':band['cpa'],'邊際 CPA（對前一帶）':band['marginal_cpa'],
                      '判讀':'加花費未增加平均訂位（觀察）' if band['plateau'] else '樣本達操作門檻' if band['eligible'] else '樣本不足'})
    money_table(st,pd.DataFrame(table),[platform]*len(table),{'日花費下緣','日花費上緣','平均日花費','平均 CPA','邊際 CPA（對前一帶）'})
    from mori.dashboard import totals
    daily=[]
    for day,values in part[part.date.astype(str)<=str(through)].groupby('date'):
        metric=totals(values)
        daily.append({'日期':str(day),'日花費':float(metric['spend']),'平台回報訂位':metric['bookings']})
    st.vega_lite_chart(pd.DataFrame(daily),{'height':240,'mark':{'type':'circle','size':75,'color':'#17421E','opacity':.65},
        'encoding':{'x':{'field':'日花費','type':'quantitative','axis':{'format':'$,.0f' if platform=='meta' else '$,.2f'}},
                    'y':{'field':'平台回報訂位','type':'quantitative'},'tooltip':[{'field':'日期'},{'field':'日花費','format':'$,.2f'},{'field':'平台回報訂位'}]},
        'config':{'font':'Microsoft JhengHei','background':'transparent','view':{'stroke':None}}},width='stretch')
    with st.expander('如何判斷真正的預算上限？'):
        st.write('邊際 CPA＝兩個相鄰花費帶的平均日花費差÷平均每日訂位差。不是兩個平均 CPA 相減。日花費依觀察值分三帶，零訂位但有花費的天數仍計入。')
        st.write('最低觀察 CPA 採合計花費÷合計訂位；上限候選是後一帶出現訂位未增加或邊際 CPA 超過可接受值時的前一帶，且前一帶的平均 CPA 仍須可接受。')
        st.write('這是相關性觀察，不是加預算造成增量的證明。受眾、地區、素材、檔期優惠、星期與競價都可能影響；同一活動也可能中途改過設定。真正上限要固定其他條件，安排可比的階梯預算試投，再核對增量有效訂位。')
        st.write('目前沒有實際營收、到店與毛利資料，不計算生意上的 ROI；也不把整檔天數乘上日花費就宣稱找到整檔上限。新舊客比例與受眾規模另作試算，不混入歷史成效。')
