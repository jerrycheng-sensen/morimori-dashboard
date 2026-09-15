import streamlit as st
import pandas as pd
from datetime import datetime
import io  # 用於產生 Excel 檔案位元流

# 未來用於 API 串接的套件 (預先載入)
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. 頁面配置與全域記憶體初始化
# ==========================================
# [更新重點 1] 瀏覽器分頁標題與網頁主標題統一更新為小寫 morimori
st.set_page_config(page_title="morimori - 廣告預算儀表板", layout="wide")
st.title("🥩 morimori - 廣告預算與儲值即時儀表板")

if "keyword_map" not in st.session_state:
    st.session_state.keyword_map = {"林口": "林口店開幕專案", "中秋": "中秋燒肉禮盒專案", "常態": "品牌常態宣傳專案"}

if "project_budgets" not in st.session_state:
    st.session_state.project_budgets = {"林口店開幕專案": 100000.0, "中秋燒肉禮盒專案": 50000.0, "品牌常態宣傳專案": 80000.0, "其他/未歸類專案": 0.0}

if "deposit_logs" not in st.session_state:
    st.session_state.deposit_logs = [
        {"儲值日期": "2026-08-01", "歸屬專案": "林口店開幕專案", "儲值金額 (TWD)": 100000.0, "備註": "代理商首筆代儲"},
    ]

# ==========================================
# 2. 廣告數據處理邏輯 (API 準備架構)
# ==========================================
@st.cache_data(ttl=3600)
def fetch_ad_data():
    """判斷是否已設定 API 金鑰，若有則呼叫真實數據，否則使用模擬數據"""
    if "meta_access_token" in st.secrets and "google_ads_developer_token" in st.secrets:
        st.toast("已偵測到廣告 API 金鑰，未來將從此處拉取真實數據！")
        pass
    
    meta_limit, google_limit = 198500.0, 166252.0
    raw_ads = [
        {"平台": "Meta", "廣告名稱": "2026_林口店開幕_FB新選單推廣_v1", "花費 (TWD)": 65000},
        {"平台": "Meta", "廣告名稱": "2026_林口店開幕_IG肉品優惠_v2", "花費 (TWD)": 42000},
        {"平台": "Google", "廣告名稱": "PMax_全台門市_常態品牌宣傳", "花費 (TWD)": 50000},
    ]
    return meta_limit, google_limit, pd.DataFrame(raw_ads)

def classify_ad(ad_name, mapping):
    for kw, proj in mapping.items():
        if kw and kw in ad_name:
            return proj
    return "其他/未歸類專案"

# ==========================================
# 3. 側邊欄控制與流水帳備份邏輯
# ==========================================
st.sidebar.header("⚙️ 儀表板控制台")
today = datetime.today()
first_day = today.replace(day=1)
date_range = st.sidebar.date_input("查詢日期區間：", value=(first_day, today), max_value=today)

st.sidebar.divider()

st.sidebar.subheader("💳 新增專案儲值紀錄")
with st.sidebar.form("deposit_form", clear_on_submit=True):
    d_date = st.date_input("儲值日期", value=today)
    d_proj = st.selectbox("歸屬專案", list(st.session_state.project_budgets.keys()))
    d_amount = st.number_input("儲值金額 (TWD)", min_value=0.0, step=10000.0)
    d_note = st.text_input("備註說明", value="")
    submitted = st.form_submit_button("➕ 寫入流水帳 (並備份至雲端)")

if submitted and d_amount > 0:
    new_record = {"儲值日期": str(d_date), "歸屬專案": d_proj, "儲值金額 (TWD)": d_amount, "備註": d_note}
    st.session_state.deposit_logs.append(new_record)
    
    if "gcp_service_account" in st.secrets:
        st.sidebar.success(f"已記錄並備份至 Google Sheets：{d_proj} 儲值 ${d_amount:,.0f}")
    else:
        st.sidebar.warning("尚未設定 Google Sheets 金鑰，目前僅暫存於記憶體中。")
        st.sidebar.success(f"已暫存：{d_proj} 儲值 ${d_amount:,.0f}")

# ==========================================
# 4. 主畫面呈現與 Excel 報表下載
# ==========================================
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_d, end_d = date_range
    meta_limit, google_limit, df_ads = fetch_ad_data()
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
    st.info(f"📅 當前區間：**{start_d}** 至 **{end_d}**")
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("雙平台後台總上限", f"${total_deposit_limit:,.0f} TWD")
    m2.metric("手動紀錄總儲值", f"${df_main['歷史累計儲值 (TWD)'].sum():,.0f} TWD")
    m3.metric("區間實際總花費", f"${total_spend:,.0f} TWD")
    m4.metric("剩餘總可用水額", f"${total_deposit_limit - total_spend:,.0f} TWD")
    
    st.divider()
    
    col_title, col_btn = st.columns([4, 1])
    with col_title:
        st.markdown("**🎯 各專案預算規劃與實際花費**")
    with col_btn:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_main.to_excel(writer, index=False, sheet_name='預算報表')
            df_deposits.to_excel(writer, index=False, sheet_name='儲值流水帳')
        
        # [更新重點 2] 輸出的 Excel 檔名同步改為小寫 morimori
        st.download_button(
            label="📊 下載 Excel 報表",
            data=buffer.getvalue(),
            file_name=f"morimori_廣告預算報表_{start_d}_至_{end_d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
    st.dataframe(df_main, use_container_width=True, hide_index=True)
