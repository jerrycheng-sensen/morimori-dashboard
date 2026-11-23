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


## 2026.11.23.45 — Meta current-name verification recovery

- Retry incomplete expanded Meta name reads using bounded scalar-ID lookups; resolve current parent names separately with account/ID checks.
- Evaluate name availability only for fields required by each plan. Verified nonmatching conditions exclude unrelated ads; immutable-ID assignments remain usable. Ambiguous paid rows still block affected totals, with ad IDs and safe reasons shown.
- Preserve original Insights names and raw Decimal costs; no credential, invoice, budget, or spend-period changes.
- Validation: 167 automated tests passed, including partial-name attribution, all/any ambiguity, scalar fallback, and explicit-ID assignment. Release manifest: all 71 files present.
- Live user-token/API behavior was not verified in the local test environment.

## 2026.11.23.46 — Isolate current-name API queries

- Replace the root multi-ID GET with independent read-only GET operations carried in Graph API batches (at most 50), decoded in request order. One object error no longer invalidates other objects.
- If the batch transport rejects a request, retry direct object-ID GETs; do not fan out authentication/quota failures. Verify object/account IDs before using names, retaining unknown states for genuinely unavailable metadata.
- Distinguish Meta code 100 (query/object) from code 190 (token); never print original API messages or credentials.
- Validation: 172 automated tests passed, including real HTTP envelope shape, mixed success/failure batch responses, direct-ID transport fallback, and malformed response rejection. Monetary calculations, raw precision, budgets, invoices, and credentials unchanged.
- The user's live Meta responses still require confirmation after deployment; mocked tests do not prove account access.

## 2026.11.23.47 — Correct an existing budget transfer

- Add one-step correction of the current transfer total, with live cached preview of both budgets and remaining amounts before confirmation. Normal transfer checks remain unchanged.
- Append a correction linked to the original transaction, recording previous/new amounts, paired effects, reason and time. Never overwrite original records, add new funding, change raw expenses, or mutate Meta/Google settings.
- Allow actual spend to exceed corrected allocations; retain nonnegative budget validation, currencies, successful expense reads, stale-value checks, and conservation of combined budgets.
- Repeated corrections use the latest total. A corrected transfer is cancelled by correcting its total to zero, rather than reversing an obsolete amount. Net transfer summaries show the corrected total.
- Validation: 184 tests passed, including the Linkou 36,386→34,128 case (Linkou 25,872; festival 90,128 and deficit 2,038), repeated edits/cancellation, tampered history rejection, stale values and Streamlit preview/save/no-double-post behavior. All 71 release files verified.
- No production budget transaction was submitted during implementation/testing.

## 2026.11.23.48 — Explain paid deleted/archived ads beside affected projects

- Add a conditional project-header badge and expandable explanation for paid Meta ads already included in successful project expense results and reported ARCHIVED/DELETED. Unaffected projects have no badge or empty explanation.
- Details preserve ad IDs, reported status, raw cost, plan query period and status-check timestamp. Distinguish API status from Ads Manager wording and explicitly state that listed costs are already included, not an extra charge.
- Reuse the existing expense snapshot; no extra API calls, attribution changes, ledger changes, or credential changes. Per-plan windows remain separate; the badge counts distinct ads.
- Validation: 187 tests passed, including zero-spend/active/unverified/failed-result exclusion, exact raw precision, no mutation, duplicate rows/windows, conditional Streamlit rendering, Meta integer display and HTML escaping. All 71 release files verified.
- Live production rendering and Meta API responses require confirmation after deployment.
