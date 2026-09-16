import io
import json
import requests
import pandas as pd
import streamlit as st
from datetime import datetime

# ==========================================
# 0. 關鍵字歸類輔助函式
# ==========================================
def classify_ad(ad_name, keyword_map):
    """
    程式碼作用：比對廣告名稱關鍵字並歸類至專案
    """
    if not isinstance(ad_name, str) or not ad_name:
        return "其他/未歸類專案"
    for kw, proj in keyword_map.items():
        if kw in ad_name:
            return proj
    return "其他/未歸類專案"

# ==========================================
# 1. 頁面配置與全域記憶體初始化
# ==========================================
st.set_page_config(page_title="morimori - 廣告預算儀表板", layout="wide")
st.title("🥩 morimori - 廣告預算與儲值即時儀表板")

# 預設專案關鍵字規則
if "keyword_map" not in st.session_state:
    st.session_state.keyword_map = {
        "林口": "林口店開幕專案",
        "中秋": "中秋燒肉禮盒專案",
        "常態": "品牌常態宣傳專案",
        "足球": "足球應援祭專案"
    }

# 預設專案目標預算
if "project_budgets" not in st.session_state:
    st.session_state.project_budgets = {
        "林口店開幕專案": 60000.0,
        "中秋燒肉禮盒專案": 50000.0,
        "品牌常態宣傳專案": 80000.0,
        "足球應援祭專案": 60000.0,
        "其他/未歸類專案": 0.0
    }

# 預設儲值流水帳
if "deposit_logs" not in st.session_state:
    st.session_state.deposit_logs = [
        {"儲值日期": "2026-06-01", "歸屬專案": "足球應援祭專案", "儲值金額 (TWD)": 60000.0, "備註": "足球應援祭代儲（已結案）"},
        {"儲值日期": "2026-08-01", "歸屬專案": "林口店開幕專案", "儲值金額 (TWD)": 60000.0, "備註": "代理商首筆代儲"},
        {"儲值日期": "2026-08-15", "歸屬專案": "中秋燒肉禮盒專案", "儲值金額 (TWD)": 50000.0, "備註": "節慶加碼預算"},
    ]

# ==========================================
# 2. Meta API 數據抓取與硬核防呆
# ==========================================
def fetch_meta_ads_data(start_date, end_date):
    if "meta_access_token" not in st.secrets or "meta_ad_account_id" not in st.secrets:
        return []
        
    token = st.secrets["meta_access_token"]
    account_id = str(st.secrets["meta_ad_account_id"]).strip()
    clean_id = account_id if account_id.startswith("act_") else f"act_{account_id}"
    
    since_str = start_date.strftime("%Y-%m-%d") if hasattr(start_date, "strftime") else str(start_date)
    until_str = end_date.strftime("%Y-%m-%d") if hasattr(end_date, "strftime") else str(end_date)
    
    url = f"https://graph.facebook.com/v19.0/{clean_id}/insights"
    params = {
        "access_token": token,
        "level": "ad",
        "fields": "ad_name,spend",
        "time_range": json.dumps({"since": since_str, "until": until_str}),
        "limit": 500
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        res_data = response.json()
        
        if "error" in res_data:
            err_msg = res_data["error"].get("message", "未知 Meta API 錯誤")
            st.error(f"⚠️ Meta API 回傳錯誤：{err_msg}")
            return []
            
        ads_list = []
        for item in res_data.get("data", []):
            ads_list.append({
                "平台": "Meta",
                "廣告名稱": item.get("ad_name", "未命名廣告"),
                "花費 (TWD)": float(item.get("spend", 0.0))
            })
        return ads_list
    except Exception as e:
        st.error(f"❌ Meta API 連線失敗：{e}")
        return []

def fetch_ad_data(start_date=None, end_date=None):
    has_meta_key = "meta_access_token" in st.secrets and "meta_ad_account_id" in st.secrets
    
    if has_meta_key and start_date and end_date:
        ads_list = fetch_meta_ads_data(start_date, end_date)
        df_ads = pd.DataFrame(ads_list)
        if not df_ads.empty:
            st.toast(f"✅ 成功從 Meta 讀取到 {len(df_ads)} 筆廣告資料！", icon="📡")
    else:
        ads_list = [
            {"平台": "Meta", "廣告名稱": "【森森燒肉】林口店開幕優惠_FB粉專", "花費 (TWD)": 15000.0},
            {"平台": "Google", "廣告名稱": "【森森燒肉】品牌關鍵字_搜尋廣告", "花費 (TWD)": 12000.0}
        ]
        df_ads = pd.DataFrame(ads_list)

    if "廣告名稱" not in df_ads.columns:
        df_ads["廣告名稱"] = pd.Series(dtype=str)
    if "花費 (TWD)" not in df_ads.columns:
        df_ads["花費 (TWD)"] = pd.Series(dtype=float)
    if "平台" not in df_ads.columns:
        df_ads["平台"] = pd.Series(dtype=str)

    return 200000.0, 150000.0, df_ads

# ==========================================
# 3. 側邊欄控制項 (前台動態管理介面)
# ==========================================
st.sidebar.header("⚙️ 儀表板控制台")
today = datetime.today()
first_day = today.replace(day=1)
date_range = st.sidebar.date_input("查詢日期區間：", value=(first_day, today), max_value=today)

st.sidebar.divider()

# 🟢 前台動態管理：新增專案與關鍵字
with st.sidebar.expander("🛠️ 前台專案與歸類管理", expanded=False):
    # 表單 1：新增全新專案
    with st.form("add_project_form", clear_on_submit=True):
        st.markdown("**1. 建立新專案與目標預算**")
        new_proj_name = st.text_input("專案名稱", placeholder="例如：跨年檔期專案")
        new_proj_budget = st.number_input("目標規劃預算 (TWD)", min_value=0.0, step=10000.0)
        btn_add_proj = st.form_submit_button("➕ 建立專案")
        
        if btn_add_proj and new_proj_name:
            st.session_state.project_budgets[new_proj_name] = new_proj_budget
            st.success(f"✅ 已建立專案：{new_proj_name}")

    # 表單 2：設定關鍵字自動歸類規則
    with st.form("add_keyword_form", clear_on_submit=True):
        st.markdown("**2. 設定廣告名稱關鍵字歸類**")
        new_kw = st.text_input("廣告名稱關鍵字", placeholder="例如：跨年")
        target_proj = st.selectbox("自動歸類至專案", list(st.session_state.project_budgets.keys()))
        btn_add_kw = st.form_submit_button("🏷️ 綁定關鍵字")
        
        if btn_add_kw and new_kw:
            st.session_state.keyword_map[new_kw] = target_proj
            st.success(f"✅ 規則已生效：含「{new_kw}」歸類至【{target_proj}】")

st.sidebar.divider()

# 表單 3：專案儲值紀錄
st.sidebar.subheader("💳 新增專案儲值紀錄")
with st.sidebar.form("deposit_form", clear_on_submit=True):
    d_date = st.date_input("儲值日期", value=today)
    d_proj = st.selectbox("歸屬專案", list(st.session_state.project_budgets.keys()))
    d_amount = st.number_input("儲值金額 (TWD)", min_value=0.0, step=10000.0)
    d_note = st.text_input("備註說明", value="")
    submitted = st.form_submit_button("➕ 寫入儲值紀錄")

if submitted and d_amount > 0:
    st.session_state.deposit_logs.append({
        "儲值日期": str(d_date),
        "歸屬專案": d_proj,
        "儲值金額 (TWD)": d_amount,
        "備註": d_note
    })
    st.sidebar.success(f"✅ 已紀錄：{d_proj} 儲值 ${d_amount:,.0f}")

# ==========================================
# 4. 主畫面呈現與報表匯出
# ==========================================
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_d, end_d = date_range
    meta_limit, google_limit, df_ads = fetch_ad_data(start_d, end_d)
    total_deposit_limit = meta_limit + google_limit
    
    df_ads["歸類專案"] = df_ads["廣告名稱"].apply(lambda x: classify_ad(x, st.session_state.keyword_map))
    df_spend = df_ads.groupby("歸類專案")["花費 (TWD)"].sum().reset_index()
    
    df_deposits = pd.DataFrame(st.session_state.deposit_logs)
    df_dep_sum = df_deposits.groupby("歸屬專案")["儲值金額 (TWD)"].sum().reset_index() if not df_deposits.empty else pd.DataFrame(columns=["歸屬專案", "儲值金額 (TWD)"])
    df_dep_sum.rename(columns={"歸屬專案": "歸類專案", "儲值金額 (TWD)": "歷史累計儲值 (TWD)"}, inplace=True)
    
    df_main = pd.DataFrame(list(st.session_state.project_budgets.items()), columns=["歸類專案", "目標規劃預算 (TWD)"])
    df_main = pd.merge(df_main, df_dep_sum, on="歸類專案", how="left").fillna(0)
    df_main = pd.merge(df_main, df_spend, on="歸類專案", how="left").fillna(0)
    df_main["預算結餘/透支 (TWD)"] = df_main["目標規劃預算 (TWD)"] - df_main["花費 (TWD)"]
    
    total_spend = df_main["花費 (TWD)"].sum()
    
    st.info(f"📅 當前資料區間：**{start_d}** 至 **{end_d}**")
    
    st.markdown("**💰 全局預算水額概況**")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("雙平台後台總上限", f"${total_deposit_limit:,.0f} TWD")
    m2.metric("系統紀錄總儲值", f"${df_main['歷史累計儲值 (TWD)'].sum():,.0f} TWD")
    m3.metric("區間實際總花費", f"${total_spend:,.0f} TWD")
    m4.metric("剩餘總可用水額", f"${total_deposit_limit - total_spend:,.0f} TWD")
    
    over_budget = df_main[df_main["預算結餘/透支 (TWD)"] < 0]
    if not over_budget.empty:
        for _, r in over_budget.iterrows():
            st.error(f"🚨 **超支警告：【{r['歸類專案']}】透支 ${abs(r['預算結餘/透支 (TWD)']):,.0f} TWD！**")
            
    st.divider()
    
    col_title, col_btn = st.columns([4, 1])
    with col_title:
        st.markdown("**🎯 各專案預算規劃與實際花費**")
    with col_btn:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_main.to_excel(writer, index=False, sheet_name='預算報表')
            df_deposits.to_excel(writer, index=False, sheet_name='儲值流水帳')
        
        st.download_button(
            label="📊 下載 Excel 報表",
            data=buffer.getvalue(),
            file_name=f"morimori_廣告預算報表_{start_d}_至_{end_d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
    st.dataframe(df_main, use_container_width=True, hide_index=True)
    
    st.divider()
    with st.expander("📜 檢視完整儲值流水帳"):
        st.dataframe(df_deposits, use_container_width=True, hide_index=True)
