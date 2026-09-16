import streamlit as st
import pandas as pd
from datetime import datetime
import io

# ==========================================
# 1. 頁面配置與全域記憶體初始化 (展示模式)
# ==========================================
st.set_page_config(page_title="morimori - 廣告預算儀表板", layout="wide")
st.title("🥩 morimori - 廣告預算與儲值即時儀表板")

# 使用 session_state 作為展示期間的資料庫
if "keyword_map" not in st.session_state:
    st.session_state.keyword_map = {
        "林口": "林口店開幕專案",
        "中秋": "中秋燒肉禮盒專案",
        "常態": "品牌常態宣傳專案"
    }

if "project_budgets" not in st.session_state:
    st.session_state.project_budgets = {
        "林口店開幕專案": 100000.0,
        "中秋燒肉禮盒專案": 50000.0,
        "品牌常態宣傳專案": 80000.0,
        "其他/未歸類專案": 0.0
    }

if "deposit_logs" not in st.session_state:
    st.session_state.deposit_logs = [
        {"儲值日期": "2026-08-01", "歸屬專案": "林口店開幕專案", "儲值金額 (TWD)": 100000.0, "備註": "代理商首筆代儲"},
        {"儲值日期": "2026-08-15", "歸屬專案": "中秋燒肉禮盒專案", "儲值金額 (TWD)": 50000.0, "備註": "節慶加碼預算"},
    ]

# ==========================================
# 2. 廣告數據處理邏輯 (API 數據集中處理區塊)
# ==========================================

@st.cache_data(ttl=1800)
def fetch_ad_data(start_date=None, end_date=None):
    """
    【定位說明】：未來修改或接入 Meta/Google API，只需要在此函式內編輯！
    【運作邏輯】：
    1. 若未偵測到 Secrets 金鑰，執行 else 區塊載入預設 DataFrame。
    2. 回傳資料格式固定為：(Meta上限, Google上限, 廣告明細DataFrame)
    """
    # 判斷是否已在 Streamlit Secrets 設定金鑰
    has_meta_key = "meta_access_token" in st.secrets
    has_google_key = "google_developer_token" in st.secrets
    
    if has_meta_key or has_google_key:
        # --------------------------------------------------
        # 未來真實 API 串接區 (金鑰設定後自動觸發)
        # --------------------------------------------------
        real_ads = []
        # 此處會執行 requests.get() 向 Meta/Google 伺服器請求資料
        # 並將結果 append 至 real_ads 陣列中
        
        meta_limit = 200000.0
        google_limit = 180000.0
        return meta_limit, google_limit, pd.DataFrame(real_ads)
    else:
        # --------------------------------------------------
        # 目前驗證區 (無金鑰時使用，格式與真實 API 完全對齊)
        # --------------------------------------------------
        meta_limit = 198500.0
        google_limit = 166252.0
        raw_ads = [
            {"平台": "Meta", "廣告名稱": "2026_林口店開幕_FB新選單推廣_v1", "花費 (TWD)": 65000},
            {"平台": "Meta", "廣告名稱": "2026_林口店開幕_IG肉品優惠_v2", "花費 (TWD)": 42000},
            {"平台": "Meta", "廣告名稱": "2026_中秋禮盒_預購單圖廣告", "花費 (TWD)": 22000},
            {"平台": "Google", "廣告名稱": "Search_關鍵字_林口燒肉推薦", "花費 (TWD)": 10000},
            {"平台": "Google", "廣告名稱": "PMax_全台門市_常態品牌宣傳", "花費 (TWD)": 50000},
        ]
        # 回傳標準化的 DataFrame 供第 4 區塊繪製儀表板
        return meta_limit, google_limit, pd.DataFrame(raw_ads)

def classify_ad(ad_name, mapping):
    """根據關鍵字字典，自動將廣告名稱歸類至對應的專案"""
    for kw, proj in mapping.items():
        if kw and kw in ad_name:
            return proj
    return "其他/未歸類專案"

# ==========================================
# 3. 側邊欄控制項與儲值表單 (無錯誤提示版)
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
    # 按鈕文字改為更符合現狀的描述
    submitted = st.form_submit_button("➕ 寫入系統並更新圖表")

if submitted and d_amount > 0:
    st.session_state.deposit_logs.append({
        "儲值日期": str(d_date),
        "歸屬專案": d_proj,
        "儲值金額 (TWD)": d_amount,
        "備註": d_note
    })
    # 給予正向的使用者回饋，並提醒可以使用 Excel 匯出
    st.sidebar.success(f"✅ 已成功記錄：{d_proj} 儲值 ${d_amount:,.0f}")
    st.sidebar.info("💡 提示：本次變更已更新至圖表，可透過右方「下載 Excel 報表」按鈕匯出留存。")

# ==========================================
# 4. 主畫面呈現與 Excel 報表下載
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
