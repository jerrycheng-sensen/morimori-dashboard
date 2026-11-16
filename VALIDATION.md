# 驗證紀錄

日期：2026/11/10（台灣）

- Python 3.12，本機執行 `python -m pytest -q`：**30 passed**。
- `compileall`：通過。
- `check.yml`、`monitor.yml`：YAML 解析通過；尚未在 GitHub runner 實際啟動。
- Streamlit AppTest：登入前阻擋 API、錯誤密碼處理、六個頁面與示例數據顯示通過。
- 廣告平台、LINE、GitHub 寫入測試均使用 mock，沒有呼叫真實廣告帳號或發送通知。
- 沒有使用 Manus 的登入、AI、Heartbeat 或資料庫服務。
- 已確認正確 GitHub 連線對原專案具備寫入權限。
- 沒有上傳或改動原 GitHub 主分支，沒有更動現有正式 Streamlit 網站。

## 尚未驗收

1. 私人資料儲存庫及其 Token。
2. Meta 可用 API version、帳號與 action_type、實際數據和後台一致。
3. Google Cloud 正式帳號存取、OAuth 離線授權、客戶與轉換動作 ID、搜尋及 PMax 數據對帳。
4. Streamlit 和 GitHub Actions 的 Secrets 都配置完成。
5. 真實 LINE 收件、重跑防重、排程依台灣時間執行，以及免費用量追蹤。
6. 原版瀏覽器工作階段中的專案預算／名稱歸類設定保存與移轉。

## 範圍限制

Google 第一版僅提供行銷活動層級規則；未移植 Manus AI 聊天與每週敘述摘要。這是整合測試版，不是已上線或全功能驗收完成的宣告。
