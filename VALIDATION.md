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

## 2026.11.26.54 — invoice orders and guided registration

- Added 精立數位 order reference to new invoice registration; invoice and order numbers remain separate. New registrations require the order number in the UI; legacy records remain valid without invented references.
- Existing valid invoices support order-number backfill/correction through append-only `invoice_order_links`. Original attachments, allocation, budget and funding status are unchanged. Prior order references are retained and shown in history.
- Reordered the invoice page: select project/platform, selected-project context, fee/tax calculator, order/invoice upload form, saved invoices. All-project table, rate/rounding settings and supporting explanations default to collapsed. Added scoped larger typography, numbered steps, ivory panels, warm separators and more spacing while preserving brand green and money precision.
- Local verification: release completeness check passes (71 files). Full pytest suite: 201 passed. Coverage includes new/legacy order references, invalid IDs, immutable correction history, void restrictions, UI backfill, collapsed secondary panels, net/fee/tax persistence, document encryption, and cached navigation.
- No production invoices, order links, budget transfers or platform settings were submitted. AppTest uses fixtures; it does not verify live Streamlit deployment. Local browser screenshot tooling could not launch because Chromium is absent and its download host returned HTTP 403; visual rendering is not claimed as verified.

## 2026.11.26.55 — advertising performance overview

- Rebuilt the overview as a guided performance home: date/account query bar, three large KPIs, switchable daily trend, side-by-side Meta/Google logo cards, grouped project table, and collapsed traffic, campaign detail/export, and methodology sections. Scoped warm ivory/champagne styling keeps the existing brand and Microsoft JhengHei; dollar amounts preserve per-platform precision and reduced fraction styling in the primary metrics/project table.
- Date presets cover yesterday, last 7 complete days, last 30 complete days, month to date, and custom ranges. Comparison explicitly reads the immediately preceding equal-length inclusive period. Updates occur only on the read button; platform/project/trend/detail changes reuse the stored report snapshot. Changed query inputs label the previous snapshot as stale until read.
- Overall totals are withheld when a requested account failed, while valid platform data remain available. Missing conversion data stay unknown; different currencies are separated; today's inclusion is labelled incomplete. Comparisons are disabled if the previous-period fetch failed and never divide by a zero baseline.
- Project grouping unions original rows once, scopes account/date/conditions, and supports direct navigation to the matching project budget. Google campaign-only reports do not substitute for ad/asset-group matching; those project aggregates show an explanation and budget navigation instead. Main totals are account-report totals, never sums of overlapping projects.
- Spending sums use raw Decimal precision before display rounding; Meta money has no decimal part, Google/combined retain two. Platform-attributed bookings are explicitly labelled as not deduplicated actual bookings/arrivals. Existing API attribution/credentials, budget ledger, invoice and anomaly settings are unchanged.
- Local checks: 208 pytest tests passed; release manifest/internal imports check passes (71 files). New tests cover equal-period boundaries, raw-cost precision, zero/unknown deltas, project union/date/account scoping, uncertain-name suppression, failed-account handling, cached filter changes, and project-to-budget navigation. Local Chromium is not installed, so desktop/mobile screenshot verification is not claimed. No production settings or financial records were submitted during testing.

## 2026.11.27.56 — activity objectives and observational marginal-cost model

- Added overview-only provider methods. Meta requests campaign objective/post engagements plus independent whole-period account/campaign reach queries with safe cursor pagination. Google joins campaign/day `metrics.interactions` separately from cost/conversions. Optional metric failures leave core expense/conversion reports available; authentication/quota failures are not retried as field failures. Scheduled anomaly and budget-provider paths retain their existing fetch methods.
- Activity comparisons classify Meta by API objective (awareness/engagement/traffic/sales-or-leads; unknown/other retained), Google by channel (Search/PMax/other). Tables include CPM, CPC, interaction rate, click CTR, platform bookings and explicitly custom bookings-per-click ratio. Google interactions are not equated with Meta post engagements. Rates use aggregate numerators/denominators; failed-platform type totals are withheld.
- Reach is never added across days, campaigns or platforms. Only exact report/account/campaign/period reach is displayed. Project-filtered views do not borrow whole-campaign reach; Google comparable reach is unimplemented and remains unknown. Optional reach data are not added to financial totals.
- Added 90-day query preset and a read-only observational model using the current report's daily history, scoped to one account/campaign/currency. Recent days are excluded by an explicit adjustable maturity setting (not a promise of finality); negative/missing measurements are rejected. Three observed daily-spend quantile bands retain paid zero-booking days. Band CPA is sum cost/sum bookings; marginal CPA is the change in mean daily spend divided by the change in mean daily attributed bookings.
- Candidate interpretation requires >=28 mature active days, three bands and user-configurable minimum days/bookings per band. Candidate upper spend requires an explicit acceptable CPA and an eligible preceding band before a plateau/high marginal-cost band. No qualifying pattern yields 'upper not found', not an extrapolated unlimited budget. Operational sample guards are not statistical/causal proof. Daily actual spend is not configured budget, project total budget, proven incrementality or ROI. Project-level ceiling still requires comparable staged-budget tests with fixed allocation/context.
- The 4:6 planner is an explicitly hypothetical effective-booking proxy: required new bookings = projected deduplicated old bookings *4/6; extra budget = new bookings * assumed new-customer CPA. It is not a 40/60 budget split or measured customer identity. Audience capacity, brand search demand, cross-platform customer deduplication, real revenue/margin and automated budget changes are not implemented. Model recomputes on each explicit overview read; no autonomous scheduled model refresh is claimed.
- Sources checked 2026-11-27: Meta Ads Insights/SDK objective and engagement fields; Google Ads API v26 metrics documentation (interactions vary by format; engagements are not generic post engagements).
- Validation: full pytest suite 221 passed; release completeness/internal-import check passes (73 files). Tests cover objective mapping, weighted rates, unknown metrics, exact-period reach, optional provider failure isolation, observed plateau versus continuing response, zero/missing/negative conversions, immature/small samples, same-campaign guards, 4:6 assumptions and local UI recalculation. No live invoice/settings/budget writes or advertising budget changes were performed. Fixture tests do not verify live API compatibility or desktop/mobile rendering.

## 2026.11.27.57 — whole-festival model and project classification

- Added project-purpose categories 檔期 / 新店開幕 / 特殊專案 to project editing, the budget rail and overview filtering. Legacy settings remain valid; the two user-confirmed baseline names default to 檔期, known opening/special projects retain explicit mappings, and other legacy projects show 待分類 instead of a guessed purpose. Saving a project records its selected category.
- Added a separate 檔期投資模型 view using 足球燒肉應援祭 and 感謝祭第5彈 together. Reads all child platform advertising plans regardless of management status, through each plan's advertising end date (not the parent event end). Whole-window costs, configured platform booking events, daily series and source audits remain available; no operations, revenue or attendance inputs are required. Stable unit/date ownership prevents overlapping project recognition. Unknown names, missing conversions and mixed currencies do not become zero.
- Added model-only provider methods: Meta combines verified current metadata and authoritative whole-period costs with raw daily configured-event outcomes. Google separately queries selected booking actions at ad/asset-group/day level, joins the cost units, and reconciles booking totals against campaign/day reports; unsupported, duplicated or unmatched sources stop this model update. Existing financial and anomaly query paths remain in place.
- The new observational Hill model shares response shape across the two whole flights, with separate response scales. It excludes today and the most recent three days (a modelling guard, not platform finality), requires sufficient mature observations/spend variation, and tests the last chronological 25% before refitting. Whole-flight budget scenarios assume comparable daily intensity/context over the selected project's advertising duration. A sweet point is shown only for an interior average-CPA minimum in the observed range; an upper requires an explicit acceptable marginal CPA and a crossing on the diminishing-response side. Missing identification stays unknown. These are conditional ad-attribution estimates, not causal incremental bookings, unique customers, operating ROI or guaranteed future ceilings. The earlier single-activity daily-band view is collapsed and labelled separately.
- Private festival-model.json snapshots are refreshed daily by the dedicated 09:15 Taipei workflow, independent of site visits and project closure. The workflow is registered on default main but explicitly checks out the live app branch. Installation also triggers the first model-only run; no LINE notification credentials or message step are included. The existing encrypted credential resolution is reused. Errors retain the previous successful data/model and last-success timestamp; configuration-signature changes suppress stale recommendations. UI chart/reference changes use the saved snapshot and do not reread platform APIs.
- Validation: 237 pytest tests passed; release completeness/internal-import check passes (78 files). New coverage includes advertising-versus-event cutoff, closed/preparing status independence, micros precision, selected Search/PMax booking joins, current Meta names, failure retention/redaction, overlapping recognition, synthetic holdout checks, no invented boundary optimum, project classification persistence and model UI snapshot reuse. Fixture tests are not proof of live API compatibility or model identification on production history. No production invoices, transfers, project budgets, advertising settings or LINE messages were submitted during tests.
- Deployment verification 2026-11-27: live-branch commit 58e29c8f679f104f86c8b427503f76797e945a0d passed GitHub integration run 45947680268. The default-branch workflow was installed through the single-file Contents API; commit d5973a22780e45940415f018a76abc4747fde278 adds only that workflow and preserves all three pre-existing main files byte-for-byte. Initial production model job 45947848530 / 140336559081 completed successfully against the live-branch commit and reported `Festival model status: estimated`. Actual model figures remain in the private snapshot and were not exposed in public logs. The public Streamlit app still displayed .55 after one reload; no owner restart controls were available in this browser, so live .57 visual deployment remains unverified/pending an owner restart.

## 2026.11.27.58 — unified workspace design and decision-first model screen

- Added a shared visual system in assets/dashboard.css and reusable escaped presentation components in mori/design_system.py. All pages inherit the forest-green/white/neutral palette, Microsoft JhengHei, consistent type scale, 46px control targets, visible keyboard focus, quiet borders, softened monetary fractions, native segmented controls and lighter tables. Sidebar destinations use decorative SVG masks, preserving accessible text names. The project rail is wider and retains its existing sticky/cached behavior. Large decorative page banners and redundant nested visual treatments are reduced.
- Rebuilt the festival model page around decisions: compact reference/settings/refresh toolbar, three large decision cards, a response chart with labelled sweet-point/upper markers, adjacent interpretation, then two comparable historical-project cards. The full recognition table and methodology/audit now default to collapsed. Settings use a native popover; edits remain local until explicit save. Unknown results and last-success/stale/error information remain visible. No changes to source queries, attribution, model fitting, scheduled refresh, financial calculations, credentials, invoices or budget transactions.
- Shared page headers now cover overview, budget, anomaly rules, notification scheduling, execution history and account/API settings. Overview account/date controls and primary read action sit in one toolbar; project/category/platform controls are grouped. Subsequent development is required by AGENTS.md to reuse these components and the same hierarchy, rather than introduce a separate visual theme per feature.
- Verification: 239 tests passed before final low-impact spacing/column refinements; release manifest/import check passes (81 files). New tests cover escaped project/card content and native model settings/reference/chart controls remaining local until explicit save, without changing source snapshots. GitHub CI validates the final tree. Browser QA used a separate, explicitly labelled synthetic-data preview (not production fallback): desktop model, settings popover, overview, budget and invoice navigation were inspected; a 390px iframe viewport had document width/scrollWidth 390 and stacked controls/cards. A fresh preview process verified the corrected style-only HTML injection and preview fixture identity. Actual mobile hardware was not tested. No production financial/settings records or advertising budgets were changed for this redesign.


## 2026.11.27.59 — current all-festival models

- All explicitly classified festival projects contribute independent diagnostics. Eligible individual models feed an equal-flight normalized pooled model; undersampled projects remain visible with observed seven-day candidates.
- Closing a project does not change its data signature or date eligibility. Reads include today; fitting excludes today and the prior three days. Hourly cache, six-hour background schedule, manual refresh; no LINE dispatch.
- CPA boundary minima are provisional visible candidates, not proven interior/global optima. All model output remains observational, with chronological holdout checks.
- Capacity sources are selected account/adset/campaign IDs, not manually entered budget/CPA thresholds. Meta uses current targeting estimates and whole-week deduplicated reach; Google uses non-overlapping brand historical search metrics and observed CTR/CPC. These are conditional demand proxies, not verified repeat customers or an identified profit-maximizing limit. No automatic 4:6-to-budget conversion.
- Unconfirmed sources or failed/malformed API data yield explicit missing capacity, never zero or a partial combined upper. No production capacity number may be claimed until actual sources are selected and APIs return complete data.
- Local Microsoft JhengHei/JhengHei UI stack with device font diagnostic; no proprietary font redistribution. Main text 18px, supporting 16px, controls 17px.
