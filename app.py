import io
import json
import requests
import pandas as pd
import streamlit as st
from datetime import datetime

# ==========================================
# 0. 輔助函式與顏色著色邏輯
# ==========================================
def classify_ad(ad_name, keyword_map):
    """程式碼作用：比對廣告名稱關鍵字並歸類至專案"""
    if not isinstance(ad_name, str) or not ad_name:
        return "其他/未歸類專案"
    for kw, proj in keyword_map.items():
        if kw in ad_name:
            return proj
    return "其他/未歸類專案"

def style_balance_color(val):
    """程式碼作用：依據結餘數字自動著色 (正數綠字、負數紅字)"""
    if isinstance(val, (int, float)):
        if val > 0:
            return 'color: #2e7d32; font-weight: bold;'
        elif val < 0:
            return 'color: #d32f2f; font-weight: bold;'
    return ''

# ==========================================
# 1. 頁面配置與 Session State 初始化
# ==========================================
st.set_page_config(page_title="森森燒肉 - 廣告預算儀表板", layout="wide")

# 1. 側邊欄 Logo 上傳功能
uploaded_logo = st.sidebar.file_uploader("🖼️ 上傳品牌 Logo", type=["png", "jpg", "jpeg"])
if uploaded_logo:
    st.sidebar.image(uploaded_logo, use_container_width=True)

# 2. 正式主標題 (已更名為森森燒肉並移除肉類 icon)
st.title("森森燒肉 - 廣告預算與可用預算即時儀表板")

# 3. 平台額度上限
if "meta_account_limit" not in st.session_state:
    st.session_state.meta_account_limit = 198500.0

if "google_account_limit" not in st.session_state:
    st.session_state.google_account_limit = 0.0

# 4. 關鍵字歸類規則
if "keyword_map" not in st.session_state:
    st.session_state.keyword_map = {
        "林口": "林口店開幕專案",
        "足球": "足球應援祭專案",
        "森鑽": "森鑽卡宣傳專案"
    }

# 5. 各專案規劃預算
if "project_budgets" not in st.session_state:
    st.session_state.project_budgets = {
        "林口店開幕專案": 60000.0,
        "足球應援祭專案": 60000.0,
        "森鑽卡宣傳專案": 78500.0,
        "其他/未歸類專案": 0.0
    }

# 6. 專案狀態 (進行中 / 已結案)
if "project_status" not in st.session_state:
    st.session_state.project_status = {
        "林口店開幕專案": "進行中",
        "足球應援祭專案": "已結案",
        "森鑽卡宣傳專案": "進行中",
        "其他/未歸類專案": "進行中"
    }

# ==========================================
# 2. Meta API 數據抓取邏輯
# ==========================================
def fetch_meta_account_spend_cap():
    """向 Meta API 查詢廣告帳號後台設定的「帳號花費上限 (spend_cap)」"""
    if "meta_access_token" not in st.secrets or "meta_ad_account_id" not in st.secrets:
        return None
        
    token = st.secrets["meta_access_token"]
    account_id = str(st.secrets["meta_ad_account_id"]).strip()
    clean_id = account_id if account_id.startswith("act_") else f"act_{account_id}"
    
    url = f"https://graph.facebook.com/v19.0/{clean_id}"
    params = {"access_token": token, "fields": "spend_cap"}
    
    try:
        response = requests.get(url, params=params, timeout=10)
        res_data = response.json()
        if "spend_cap" in res_data:
            return float(res_data["spend_cap"])
    except Exception:
        pass
    return None

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

# 自動讀取最新 Meta 帳號上限
auto_spend_cap = fetch_meta_account_spend_cap()
if auto_spend_cap and auto_spend_cap > 0:
    st.session_state.meta_account_limit = auto_spend_cap

# ==========================================
# 3. 側邊欄控制項 (狀態管理與按鈕控制)
# ==========================================
st.sidebar.header("⚙️ 儀表板控制台")
today = datetime.today()
first_day = today.replace(day=1)
date_range = st.sidebar.date_input("查詢日期區間：", value=(first_day, today), max_value=today)

st.sidebar.divider()

with st.sidebar.expander("🛠️ 前台專案與關鍵字管理台", expanded=True):
    
    st.markdown("**1️⃣ 建立新專案與狀態設定**")
    with st.form("add_project_form", clear_on_submit=True):
        new_proj_name = st.text_input("專案名稱", placeholder="例如：跨年檔期專案")
        new_proj_budget = st.number_input("目標規劃預算 (TWD)", min_value=0.0, step=10000.0)
        new_proj_status = st.selectbox("專案狀態", ["進行中", "已結案"])
        btn_add_proj = st.form_submit_button("➕ 建立專案")
        if btn_add_proj and new_proj_name:
            st.session_state.project_budgets[new_proj_name] = new_proj_budget
            st.session_state.project_status[new_proj_name] = new_proj_status
            st.success(f"✅ 已建立專案：{new_proj_name} ({new_proj_status})")

    st.markdown("---")
    
    st.markdown("**2️⃣ 設定廣告名稱關鍵字歸類**")
    with st.form("add_keyword_form", clear_on_submit=True):
        new_kw = st.text_input("廣告名稱關鍵字", placeholder="例如：跨年")
        target_proj = st.selectbox("自動歸類至專案", list(st.session_state.project_budgets.keys()), key="kw_target")
        btn_add_kw = st.form_submit_button("🏷️ 綁定關鍵字")
        if btn_add_kw and new_kw:
            st.session_state.keyword_map[new_kw] = target_proj
            st.success(f"✅ 規則已生效：含「{new_kw}」自動歸類至【{target_proj}】")

    st.markdown("---")
    
    # 🟢 專案狀態按鈕切換與刪除區塊
    st.markdown("**3️⃣ 專案狀態切換與管理**")
    with st.form("manage_project_form"):
        edit_proj_list = [p for p in st.session_state.project_budgets.keys() if p != "其他/未歸類專案"]
        selected_proj = st.selectbox("選擇要變更的專案", edit_proj_list if edit_proj_list else ["無可管理專案"])
        
        current_st = st.session_state.project_status.get(selected_proj, "進行中")
        st.caption(f"當前專案狀態：**{current_st}**")
        
        updated_status = st.radio("切換狀態為：", ["進行中", "已結案"], horizontal=True)
        col_m1, col_m2 = st.columns(2)
        btn_update_status = col_m1.form_submit_button("💾 儲存狀態")
        btn_del_proj = col_m2.form_submit_button("🗑️ 刪除專案")
        
        if btn_update_status and selected_proj in st.session_state.project_status:
            st.session_state.project_status[selected_proj] = updated_status
            st.success(f"✅ 專案【{selected_proj}】狀態已更新為：{updated_status}")
            st.rerun()
            
        if btn_del_proj and selected_proj in st.session_state.project_budgets:
            del st.session_state.project_budgets[selected_proj]
            del st.session_state.project_status[selected_proj]
            st.session_state.keyword_map = {k: v for k, v in st.session_state.keyword_map.items() if v != selected_proj}
            st.success(f"🗑️ 已刪除專案：{selected_proj}")
            st.rerun()

# ==========================================
# 4. 主畫面呈現：頂部卡片與頁籤分流
# ==========================================
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_d, end_d = date_range
    
    # --- A. 全帳號即時可用預算計算 ---
    meta_all_time_list = fetch_meta_ads_data(is_all_time=True)
    df_meta_all_time = get_ads_data_safely(meta_all_time_list)
    meta_total_spent_all_time = df_meta_all_time["花費 (TWD)"].sum() if not df_meta_all_time.empty else 0.0
    
    meta_remaining = st.session_state.meta_account_limit - meta_total_spent_all_time
    google_remaining = st.session_state.google_account_limit - 0.0
    total_remaining = meta_remaining + google_remaining

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
    # 呈現區塊 1：⚡ 即時帳號可用預算概況
    # ==========================================
    st.subheader("⚡ 即時帳號可用預算概況 (API 自動讀取後台額度上限 - 全時段花費)")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("雙平台總剩餘可用預算", f"${total_remaining:,.0f} TWD")
    r2.metric("Meta Ads 剩餘可用預算", f"${meta_remaining:,.0f} TWD", help=f"API 自動讀取後台上限: ${st.session_state.meta_account_limit:,.0f}")
    r3.metric("Google Ads 剩餘可用預算", f"${google_remaining:,.0f} TWD", help=f"設定上限: ${st.session_state.google_account_limit:,.0f}")
    r4.metric("雙平台未分配專案預算", f"${unallocated_budget:,.0f} TWD", help="代理商總額度上限 - 各專案已規劃預算總和")

    st.divider()

    # ==========================================
    # 呈現區塊 2：頁籤切換 (歷年總覽 vs 區間明細)
    # ==========================================
    tab_all, tab_range = st.tabs(["📊 歷年專案總覽 (全時段)", "📅 指定區間花費分析"])

    # 🟢 頁籤 1：歷年專案總覽 (全時段格式修復)
    with tab_all:
        col_t1, col_b1 = st.columns([4, 1])
        with col_t1:
            st.markdown("### 🏆 歷年專案總體執行概況 (包含執行率與狀態)")
            
        if not df_meta_all_time.empty:
            df_meta_all_time["歸類專案"] = df_meta_all_time["廣告名稱"].apply(lambda x: classify_ad(x, st.session_state.keyword_map))
            df_all_spend = df_meta_all_time.groupby("歸類專案")["花費 (TWD)"].sum().reset_index()
        else:
            df_all_spend = pd.DataFrame(columns=["歸類專案", "花費 (TWD)"])

        df_all_view = pd.DataFrame(list(st.session_state.project_budgets.items()), columns=["歸類專案", "目標規劃預算 (TWD)"])
        df_all_view = pd.merge(df_all_view, df_all_spend, on="歸類專案", how="left").fillna(0)
        df_all_view.rename(columns={"花費 (TWD)": "全時段總花費 (TWD)"}, inplace=True)
        
        df_all_view["全時段結餘/透支 (TWD)"] = df_all_view["目標規劃預算 (TWD)"] - df_all_view["全時段總花費 (TWD)"]
        df_all_view["預算執行率 (%)"] = df_all_view.apply(
            lambda r: (r["全時段總花費 (TWD)"] / r["目標規劃預算 (TWD)"] * 100) if r["目標規劃預算 (TWD)"] > 0 else 0.0, axis=1
        )
        df_all_view["專案狀態"] = df_all_view["歸類專案"].map(st.session_state.project_status).fillna("進行中")
        
        df_all_view = df_all_view[["歸類專案", "專案狀態", "目標規劃預算 (TWD)", "全時段總花費 (TWD)", "預算執行率 (%)", "全時段結餘/透支 (TWD)"]]

        with col_b1:
            buffer_all = io.BytesIO()
            with pd.ExcelWriter(buffer_all, engine='openpyxl') as writer:
                df_all_view.to_excel(writer, index=False, sheet_name='全時段歷年報表')
            st.download_button(
                label="📊 下載歷年報表",
                data=buffer_all.getvalue(),
                file_name="森森燒肉_歷年專案總覽報表.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        # 🟢 關鍵格式化修正：帶入 format 徹底去除 .000000 雜訊，呈現乾淨數值與 %
        styled_df_all = (
            df_all_view.style
            .format({
                "目標規劃預算 (TWD)": "${:,.0f}",
                "全時段總花費 (TWD)": "${:,.0f}",
                "預算執行率 (%)": "{:.1f}%",
                "全時段結餘/透支 (TWD)": "${:,.0f}"
            })
            .map(style_balance_color, subset=["全時段結餘/透支 (TWD)"])
        )
        st.dataframe(styled_df_all, use_container_width=True, hide_index=True)

    # 🟢 頁籤 2：指定區間花費分析 (格式修復)
    with tab_range:
        st.markdown(f"### 📅 指定區間花費概況 ({start_d} 至 {end_d})")
        d1, d2, d3 = st.columns(3)
        d1.metric("雙平台區間總廣告花費", f"${total_range_spend:,.0f} TWD")
        d2.metric("Meta Ads 廣告花費", f"${meta_range_spend:,.0f} TWD")
        d3.metric("Google Ads 廣告花費", f"${google_range_spend:,.0f} TWD")
        
        st.divider()

        if not df_ads_range.empty:
            df_ads_range["歸類專案"] = df_ads_range["廣告名稱"].apply(lambda x: classify_ad(x, st.session_state.keyword_map))
            df_range_spend = df_ads_range.groupby("歸類專案")["花費 (TWD)"].sum().reset_index()
        else:
            df_range_spend = pd.DataFrame(columns=["歸類專案", "花費 (TWD)"])
            
        df_range_view = pd.DataFrame(list(st.session_state.project_budgets.items()), columns=["歸類專案", "目標規劃預算 (TWD)"])
        df_range_view = pd.merge(df_range_view, df_range_spend, on="歸類專案", how="left").fillna(0)
        df_range_view.rename(columns={"花費 (TWD)": "區間實際花費 (TWD)"}, inplace=True)
        df_range_view["區間剩餘/透支 (TWD)"] = df_range_view["目標規劃預算 (TWD)"] - df_range_view["區間實際花費 (TWD)"]
        df_range_view["專案狀態"] = df_range_view["歸類專案"].map(st.session_state.project_status).fillna("進行中")
        
        df_range_view = df_range_view[["歸類專案", "專案狀態", "目標規劃預算 (TWD)", "區間實際花費 (TWD)", "區間剩餘/透支 (TWD)"]]

        styled_df_range = (
            df_range_view.style
            .format({
                "目標規劃預算 (TWD)": "${:,.0f}",
                "區間實際花費 (TWD)": "${:,.0f}",
                "區間剩餘/透支 (TWD)": "${:,.0f}"
            })
            .map(style_balance_color, subset=["區間剩餘/透支 (TWD)"])
        )
        st.dataframe(styled_df_range, use_container_width=True, hide_index=True)
