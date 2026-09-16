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
# 1. 頁面配置與全域記憶體初始化 (永久防遺失版)
# ==========================================
st.set_page_config(page_title="morimori - 廣告預算儀表板", layout="wide")
st.title("🥩 morimori - 廣告預算與水額即時儀表板")

# 1. 代理商開立的平台額度上限
if "meta_account_limit" not in st.session_state:
    st.session_state.meta_account_limit = 200000.0  # Meta 預設總額度上限

if "google_account_limit" not in st.session_state:
    st.session_state.google_account_limit = 150000.0  # Google 預設總額度上限

# 2. 專案關鍵字歸類規則 (已寫入森鑽卡，重啟不遺失)
if "keyword_map" not in st.session_state:
    st.session_state.keyword_map = {
        "林口": "林口店開幕專案",
        "中秋": "中秋燒肉禮盒專案",
        "常態": "品牌常態宣傳專案",
        "足球": "足球應援祭專案",
        "森鑽": "森鑽卡宣傳專案"  # 🟢 森鑽卡關鍵字
    }

# 3. 各專案規劃預算
if "project_budgets" not in st.session_state:
    st.session_state.project_budgets = {
        "林口店開幕專案": 60000.0,
        "中秋燒肉禮盒專案": 50000.0,
        "品牌常態宣傳專案": 80000.0,
        "足球應援祭專案": 60000.0,
        "森鑽卡宣傳專案": 78500.0,  # 🟢 森鑽卡預算
        "其他/未歸類專案": 0.0
    }

# ==========================================
# 2. Meta API 數據抓取邏輯
# ==========================================
def fetch_meta_ads_data(start_date=None, end_date=None, is_all_time=False):
    if "meta_access_token" not in st.secrets or "meta_ad_account_id" not in st.secrets:
        return []
        
    token = st.secrets["meta_access_token"]
    account_id = str(st.secrets["meta_ad_account_id"]).strip()
    clean_id = account_id if account_id.startswith("act_") else f"act_{account_id}"
    url = f"https://graph.facebook.com/v19.0/{clean_id}/insights"
    
    params = {
        "access_token": token,
        "level": "ad",
        "fields": "ad_name,spend",
        "limit": 500
    }
    
    if is_all_time:
        params["date_preset"] = "maximum"
    elif start_date and end_date:
        since_str = start_date.strftime("%Y-%m-%d") if hasattr(start_date, "strftime") else str(start_date)
        until_str = end_date.strftime("%Y-%m-%d") if hasattr(end_date, "strftime") else str(end_date)
        params["time_range"] = json.dumps({"since": since_str, "until": until_str})
    
    try:
        response = requests.get(url, params=params, timeout=10)
        res_data = response.json()
        if "error" in res_data:
            return []
            
        ads_list = []
        for item in res_data.get("data", []):
            ads_list.append({
                "平台": "Meta",
                "廣告名稱": item.get("ad_name", "未命名廣告"),
                "花費 (TWD)": float(item.get("spend", 0.0))
            })
        return ads_list
    except Exception:
        return []

def get_ads_data_safely(ads_list):
    df = pd.DataFrame(ads_list)
    if df.empty or "廣告名稱" not in df.columns:
        df = pd.DataFrame(columns=["平台", "廣告名稱", "花費 (TWD)"])
    return df

# ==========================================
# 3. 側邊欄控制項 (前台自主管理)
# ==========================================
st.sidebar.header("⚙️ 儀表板控制台")
today = datetime.today()
first_day = today.replace(day=1)
date_range = st.sidebar.date_input("查詢日期區間：", value=(first_day, today), max_value=today)

st.sidebar.divider()

with st.sidebar.expander("🛠️ 前台總額度與專案管理台", expanded=True):
    
    st.markdown("**1️⃣ 代理商平台總額度設定**")
    with st.form("limit_form"):
        m_lim = st.number_input("Meta 帳號總額度 (TWD)", value=st.session_state.meta_account_limit, step=10000.0)
        g_lim = st.number_input("Google 帳號總額度 (TWD)", value=st.session_state.google_account_limit, step=10000.0)
        btn_save_lim = st.form_submit_button("💾 更新平台總額度")
        if btn_save_lim:
            st.session_state.meta_account_limit = m_lim
            st.session_state.google_account_limit = g_lim
            st.success("✅ 總額度已更新！")

    st.markdown("---")
    
    st.markdown("**2️⃣ 建立新專案與目標預算**")
    with st.form("add_project_form", clear_on_submit=True):
        new_proj_name = st.text_input("專案名稱", placeholder="例如：跨年檔期專案")
        new_proj_budget = st.number_input("目標規劃預算 (TWD)", min_value=0.0, step=10000.0)
        btn_add_proj = st.form_submit_button("➕ 建立專案")
        if btn_add_proj and new_proj_name:
            st.session_state.project_budgets[new_proj_name] = new_proj_budget
            st.success(f"✅ 已建立專案：{new_proj_name}")

    st.markdown("---")
    
    st.markdown("**3️⃣ 設定廣告名稱關鍵字歸類**")
    with st.form("add_keyword_form", clear_on_submit=True):
        new_kw = st.text_input("廣告名稱關鍵字", placeholder="例如：跨年")
        target_proj = st.selectbox("自動歸類至專案", list(st.session_state.project_budgets.keys()), key="kw_target")
        btn_add_kw = st.form_submit_button("🏷️ 綁定關鍵字")
        if btn_add_kw and new_kw:
            st.session_state.keyword_map[new_kw] = target_proj
            st.success(f"✅ 規則已生效：含「{new_kw}」自動歸類至【{target_proj}】")

# ==========================================
# 4. 主畫面呈現：雙區塊數據與指標面板
# ==========================================
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_d, end_d = date_range
    
    # --- A. 全帳號即時水額計算 ---
    meta_all_time_list = fetch_meta_ads_data(is_all_time=True)
    df_meta_all_time = get_ads_data_safely(meta_all_time_list)
    meta_total_spent_all_time = df_meta_all_time["花費 (TWD)"].sum() if not df_meta_all_time.empty else 0.0
    
    meta_remaining = st.session_state.meta_account_limit - meta_total_spent_all_time
    google_remaining = st.session_state.google_account_limit - 0.0
    total_remaining = meta_remaining + google_remaining

    # 🟢 計算未配給專案的預算水額
    total_platform_limit = st.session_state.meta_account_limit + st.session_state.google_account_limit
    total_allocated_budget = sum(st.session_state.project_budgets.values())
    unallocated_budget = total_platform_limit - total_allocated_budget

    # --- B. 指定區間花費計算 ---
    meta_range_list = fetch_meta_ads_data(start_date=start_d, end_date=end_d)
    df_ads_range = get_ads_data_safely(meta_range_list)
    
    if not df_ads_range.empty:
        st.toast(f"✅ 成功從 Meta 讀取到 {len(df_ads_range)} 筆區間廣告資料！", icon="📡")
        
    meta_range_spend = df_ads_range["花費 (TWD)"].sum() if not df_ads_range.empty else 0.0
    google_range_spend = 0.0
    total_range_spend = meta_range_spend + google_range_spend

    # ==========================================
    # 呈現區塊 1：⚡ 即時帳號剩餘水額與未分配預算
    # ==========================================
    st.subheader("⚡ 即時帳號水額概況 (代理商開立額度 - 全時段花費)")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("雙平台總剩餘可用水額", f"${total_remaining:,.0f} TWD")
    r2.metric("Meta Ads 剩餘可用水額", f"${meta_remaining:,.0f} TWD")
    r3.metric("Google Ads 剩餘可用水額", f"${google_remaining:,.0f} TWD")
    r4.metric("雙平台尚未分配專案水額", f"${unallocated_budget:,.0f} TWD", help="代理商總額度 - 各專案已規劃預算總和")

    st.divider()

    # ==========================================
    # 呈現區塊 2：📅 指定區間累積花費
    # ==========================================
    st.subheader(f"📅 指定區間花費概況 ({start_d} 至 {end_d})")
    d1, d2, d3 = st.columns(3)
    d1.metric("雙平台區間總廣告花費", f"${total_range_spend:,.0f} TWD")
    d2.metric("Meta Ads 廣告花費", f"${meta_range_spend:,.0f} TWD")
    d3.metric("Google Ads 廣告花費", f"${google_range_spend:,.0f} TWD")

    st.divider()

    # ==========================================
    # 各專案花費與預算對照表
    # ==========================================
    col_title, col_btn = st.columns([4, 1])
    with col_title:
        st.markdown("### 🎯 各專案目標預算與區間花費明細")
    
    if not df_ads_range.empty:
        df_ads_range["歸類專案"] = df_ads_range["廣告名稱"].apply(lambda x: classify_ad(x, st.session_state.keyword_map))
        df_spend = df_ads_range.groupby("歸類專案")["花費 (TWD)"].sum().reset_index()
    else:
        df_spend = pd.DataFrame(columns=["歸類專案", "花費 (TWD)"])
        
    df_main = pd.DataFrame(list(st.session_state.project_budgets.items()), columns=["歸類專案", "目標規劃預算 (TWD)"])
    df_main = pd.merge(df_main, df_spend, on="歸類專案", how="left").fillna(0)
    df_main.rename(columns={"花費 (TWD)": "區間實際花費 (TWD)"}, inplace=True)
    df_main["預算結餘/透支 (TWD)"] = df_main["目標規劃預算 (TWD)"] - df_main["區間實際花費 (TWD)"]
    
    with col_btn:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_main.to_excel(writer, index=False, sheet_name='專案報表')
        
        st.download_button(
            label="📊 下載 Excel 報表",
            data=buffer.getvalue(),
            file_name=f"morimori_預算報表_{start_d}_至_{end_d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
    st.dataframe(df_main, use_container_width=True, hide_index=True)
