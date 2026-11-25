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

## 2026.11.23.49 — Readable Google attribution preview totals

- Replace the small preview expense caption with a bordered result summary: prominent total spend, exact query dates, distinct ad/asset-group count, impressions and clicks. Retain the unsaved-setting notice.
- Show campaign-level expense subtotals by immutable campaign ID/currency; keep daily raw details in a separate expander. Group already matched result rows, never sum individual rule matches. Preserve monetary Decimal precision until display and Google small decimal formatting.
- No changes to attribution rules, provider queries, stored project settings, expense calculations or financial records.
- Validation: 190 automated tests passed, including preview-then-save integration, exact raw amount aggregation, repeated-day unit counts, distinct same-name campaigns, escaped names, Google decimal rendering and zero-match results. All 71 release files verified.
- Live user-token results and production rendering are not established by mocked tests.

## 2026.11.24.50 — Exact Google cost inputs and daily attribution audit

- Preserve Google cost_micros as Decimal-derived raw strings in campaign and ad/asset-group daily rows. Keep numeric compatibility fields, but use raw values for financial totals and reconciliation. Reject malformed/negative micros instead of silently coercing them.
- Compare campaign-versus-detail costs exactly, including a one-micro discrepancy. Retain the existing explicit live-day warning policy; historical/missing-row mismatches block recognition and now identify the campaign ID, date, both values and difference.
- Preserve campaign-level query rows plus query start/end timestamps. Add a daily audit to Google previews and plan cards, separating condition-excluded cost from campaign/detail response differences without modifying stored budgets or inserting adjustments. Invalidate previous snapshots once on this release.
- Validation: full suite 193 passed; the subsequently added exact audit UI test passed separately (194 tests total). All 71 release files verified. Tests cover >2^53 integer micros, malformed input, one-micro historical discrepancies, missing detail, partial recognition, query provenance and exact audit values.
- The specific screenshot discrepancy (TWD 2.44) remains unproven: original UI/API read timestamps and matching backend daily export were not available. This release adds evidence needed to investigate; it does not assert a retroactive diagnosis or guarantee Google finality after project closure.

## 2026.11.24.51 — Budget workspace navigation and page flow

- Place the four native section buttons immediately after the page heading, ahead of financial summaries. Start project navigation at the top left of the overview workspace, alongside the summary/content column.
- Make the desktop navigation column sticky beneath the app header, with a viewport-bounded independently scrolling rail; remove the fixed 480px empty project-list area. Stack columns on narrower screens and keep a bounded project list without sticky overlays.
- All-project view opens the cross-project summary; a selected project places its name and details first with the global summary available in a collapsed section. Other editing/ledger/invoice sections retain a collapsible summary and their existing forms.
- Preserve cached reports, financial calculations, invoice entry points, project/year/status semantics and selected button states. No project, invoice or ledger data was submitted during implementation.
- Validation: full 194-test suite passed; updated layout/navigation/cache integration test passed after extending it to check rail-before-summary order and project/all-project switching with no additional account reads. All 71 release files verified. Browser viewport/sticky behavior still requires live deployment verification.

## 2026.11.24.52 — Consistent dollar symbols across monetary displays

- Apply a single dollar symbol through shared monetary text/HTML/metric/table formatters, removing redundant TWD prefixes. Keep currency codes in underlying records and explicit account/invoice metadata; no conversion or financial calculation changes.
- Cover project/combined/platform KPIs, preview subtotals, invoices, transfer records, monetary notes/errors, overview spend/CPA/CPC metrics and sortable tables, rule thresholds/candidates, and chart axes/tooltips. Monetary input controls use a dollar icon while preserving native numeric editing (currency literals in number_input format strings are unsupported).
- Preserve Meta integer and Google/combined two-decimal presentation, smaller/lighter HTML fractions, unknown placeholders, percentages/counts/IDs/dates, numeric sorting and raw exports. The diagnostic audit keeps its full raw precision with a dollar symbol.
- Validation: full existing suite 194 passed; two added formatting/data-integrity tests passed (196 total); dashboard chart tests passed after platform-specific currency format updates. All 71 release files verified. No production financial data, credentials or settings submitted.

## 2026.11.25.53 — Separate advertising budget from invoice fees and VAT

- Add an invoice calculator with the user's confirmed default: Meta 3% service fee plus 5% VAT on advertising + service; Google no service fee and 5% VAT on advertising. Show net advertising amount, service fee, VAT and estimated invoice total separately, all in dollar formatting.
- Seed the editable calculator from original platform budget, explicitly excluding transfers from automatic new-deposit recognition. Require an explicit apply action to copy gross total into invoice face value and net advertising into project recognition. Support whole-unit or two-decimal component rounding, an explicit tax-base option and manual registration.
- Preserve a validated immutable charge quote with invoice records. Recompute it on registration/load; require notes for actual-face/estimate differences. Validate all fields before saving any encrypted attachment. Historical invoices without fee metadata remain unchanged, and only net allocated advertising contributes to existing invoice totals.
- No automatic payment verification, budget/ledger mutation, OCR or external financial transaction. Invoice attachment requirement, encryption, duplicate checks, void history and existing manual/split registration remain in place.
- Validation: 199 tests passed, including both Meta tax bases, Google fee-free arithmetic, rounding precision, altered quote rejection, actual-invoice difference notes, calculator/apply/save interaction, switching platform defaults, net recognition and unchanged project budgets. All 71 release files verified. No production invoice was submitted during testing.
