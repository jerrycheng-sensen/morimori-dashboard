# 森森廣告數據與異常提醒：Streamlit 整合測試版

以既有 `jerrycheng-sensen/morimori-dashboard`（基準 commit `c06a232eb50fbe97f40cf70d4f9095c47e5fd1c6`）及使用者提供的 Manus 規則 v2 為基礎，改寫為 Python 共用邏輯。程式不依賴 Manus 登入、Heartbeat、資料庫或點數。

**目前是完成本機模擬測試的待部署版本。沒有讀取真實 Meta／Google／LINE 金鑰，沒有更新線上網站，也沒有啟用真實通知。**

## 本版範圍

| 區塊 | 支援內容 |
|---|---|
| 數據總覽 | Meta、Google 多帳號；帳號幣別分開；日期、活動類型篩選；每日花費圖表；轉換、CPA；Excel |
| 專案預算 | 專案預算、起迄、進行中／已結案；依名稱歸類；完整期間累計花費／結餘／執行率；設定匯出 |
| Meta 異常規則 | 活動、廣告組合、廣告層級；三層名稱 AND 篩選；先篩選後彙總；1～30 天；啟用起迄 |
| Google 異常規則 | 行銷活動層級，含搜尋與 PMax；活動名稱、類型篩選；指定事件或主要轉換口徑 |
| 通知 | LINE 單人／群組；可依規則指定對象代號；多筆異常合併；當日防重；結果不明以固定 retry key 重試 |
| 排程 | 台灣時間，每天 1～4 個時段及星期；網頁儲存；GitHub Actions 每 30 分鐘巡檢；網頁關閉仍運作 |
| 紀錄 | 私人保存近 30 次執行，每次顯示前 50 筆異常樣本；通知回執保留約 40 天；失敗不寫成零轉換 |

本版不含：原 Manus 的 AI 分析聊天、每週敘述摘要、Google 廣告組合／素材群組層級、改動廣告預算或暫停廣告。這些不影響本版每日數據監控，但不能把本版視為原 Manus 所有功能皆已完整移植。

## 部署前準備

1. 讀到的程式儲存庫為 **公開**。因此規則、帳號設定、通知對象與執行紀錄必須使用另一個 **私人資料儲存庫**。程式會檢查並拒絕讀寫公開的資料儲存庫。金鑰只放 Secrets。
2. 2026/11/10 已確認 `jerrycheng-sensen/morimori-dashboard` 的正確 GitHub 連線具備寫入權限，可建立整合分支與 PR。正式部署仍須設定私人資料儲存庫、平台憑證及驗收。

## 最短啟用路徑

### 1. 上傳程式（先用測試分支）

- 先備份目前主分支。保留原版 `reference/original_app.py.txt` 作對照。
- 把本資料夾根目錄的 `app.py`、`mori/`、需求檔、`.streamlit/config.toml` 和 `.github/workflows/` 放到儲存庫根目錄，不要只上傳 ZIP。
- 執行測試，使用測試分支部署第二個 Streamlit app 檢查。正式 app 維持原主分支，直到驗收。
- `check.yml` 是無憑證測試；`monitor.yml` 必須進入預設主分支後，才可排程及手動 dispatch。
- 合併前保留預設的 `schedule.enabled=false`，不要先啟用真實通知。

### 2. 建立私人資料儲存庫

- 新增 `morimori-monitor-state`，選 **Private**，勾選 README 以建立 `main` 分支。
- 不需手動建立 `settings.json`／`runtime.json`；程式第一次儲存時建立。
- 建立 Fine-grained personal access token，只選該私人 repo，`Contents: Read and write`；不需 Administration、Issues 或 Secrets 權限。
- 將 `owner/repo` 與此 token 分別設為 `STATE_REPO`、`STATE_TOKEN`。
- GitHub Contents API 讀寫具版本 SHA 比對；有衝突會拒絕覆蓋，需重新整理。此做法適合小型、低頻管理，不是大型資料倉儲。單檔達 900 KB 會停止寫入，需備份與封存。未來可改用資料庫而保留網頁與規則邏輯。

### 3. Streamlit Secrets

將 `.streamlit/secrets.example.toml` 的內容貼入測試 app 的 Settings → Secrets，填入真實值。

| 必要設定 | 用途 |
|---|---|
| `APP_PASSWORD` | 依管理者要求，開發階段已取消應用程式登入；此值暫不使用 |
| `STATE_REPO`, `STATE_TOKEN` | 私人設定及紀錄的永久儲存 |
| `META_ACCESS_TOKEN`, `META_API_VERSION` | Meta 授權與目前可用版本；舊小寫 `meta_access_token` 在網頁仍相容 |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` | Google OAuth 離線授權，詳下一節 |
| `GOOGLE_LOGIN_CUSTOMER_ID` | 若透過 MCC 存取，填 MCC ID；不是報表帳號 ID |
| `GOOGLE_API_VERSION` | 目前預設 `v26`，可透過 Secrets 更新 |
| `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_RECIPIENT_ID` | LINE Messaging API 與預設收件人／群組 |

多個通知對象可加：`LINE_RECIPIENTS_JSON = '{"marketing":"C...","jerry":"U..."}'`；規則填 `marketing` 或 `jerry`。`default` 使用 `LINE_RECIPIENT_ID`。

如要從網頁按鈕手動啟動 Actions，另設 `SOURCE_REPO`、`SOURCE_BRANCH`、`SOURCE_TOKEN`。這個 Token 只選程式 repo，給 `Actions: Read and write`，不與私人資料 Token 混用。未設定時仍可從 GitHub Actions 頁手動操作。

**不要把任何真實金鑰放進程式、設定 JSON、截圖、公開 repo 或對話。**

### 4. Google Ads 授權（需你登入自己的帳號）

1. 在 Google Cloud 建立或選擇公司使用的專案，啟用 Google Ads API。
2. 確認該 Cloud 專案有正式廣告帳號的 API 存取級別，不只測試帳號存取。
3. 設定 OAuth 同意畫面與 OAuth client，用有目標 Google Ads 帳號權限的 Google 帳號授權 `https://www.googleapis.com/auth/adwords`，取得支援 offline access 的 refresh token。請依官方 single-user authentication 流程進行，見下方連結。OAuth 同意畫面若仍在 Testing，需依官方規則確認 token 有效期間，不能假設為永久。
4. 保存 client ID、client secret、refresh token 到 Streamlit Secrets 及 GitHub Actions Secrets。
5. Google Ads 客戶 ID 填在網頁「帳號與串接」，不含 `-`；若經 MCC 存取，再將 MCC ID 填 `GOOGLE_LOGIN_CUSTOMER_ID`。
6. 按「檢查串接與轉換事件」列出轉換動作 ID。選要追蹤的訂位事件，保存 ID 後再查數據。不要只靠名稱猜 ID，也不要自行把全部主要轉換稱為訂位。

依 2026/11/9 查到的 Google 官方說明，developer token 已於 2026/9/9 sunset，存取級別改由 Cloud 專案管理。因此 `GOOGLE_DEVELOPER_TOKEN` 是相容舊設定的選填欄位，而不是新部署的必填條件。實際存取仍須由 Google 批准。

### 5. 在網頁建帳號、規則與預算

- Meta：每帳號明確選一種 `action_type`。可查近 7 天回傳種類，再跟廣告後台確認。同一購買可能有多種彙總 action_type，不可相加。
- Google：可選指定 conversion action ID（使用 `all_conversions`，包含該事件的次要轉換），或明確選用帳號主要轉換總和（`conversions`）。預設尚未選事件時顯示未設定，不能觸發零轉換。
- Google 成本與指定事件分開查詢，再依活動 ID＋日期合併；不把成本隨事件分段，以免重複或漏算。
- Google 用 campaign 資源涵蓋 PMax，不以 `ad_group` 代替 PMax 素材群組。第一版只能在行銷活動層級告警。
- Meta 點擊為連結點擊；Google 為 Ads 點擊，不能假設定義相同。
- 日期資料依廣告帳號時區；通知排程與「截至昨天」以台灣日曆日計算。外國時區帳號應另行驗證跨日口徑。
- 花費是 API 原值、帳號幣別，未加代理商服務費或另計稅。不同幣別分開顯示；雙平台轉換不視為已去重的實際訂位。
- 專案預算必須有起迄與名稱關鍵字。Meta 可選廣告名稱，沿用原版分類方式；Google 先用活動名稱。多個關鍵字可先建立不同專案，但重疊分類不可以相加當作帳號總花費。
- 舊版只存在瀏覽器工作階段的專案設定不能由 GitHub 程式自動恢復。請在原網頁仍開啟時保存目前資料，再輸入新版；程式裡過期的硬編碼預算不作為最新預算沿用。
- 舊版「spend_cap 減最近900天花費」不等於正確的儲值餘額，本版不沿用該推算。若要儲值餘額，需另定起算日、入帳總額及帳務口徑後再加。

### 6. GitHub Actions Secrets（網頁和排程各自要設定）

在**程式儲存庫** Settings → Secrets and variables → Actions 新增：

```text
STATE_REPO
STATE_TOKEN
STATE_BRANCH                  # 可省略，預設 main
META_ACCESS_TOKEN
META_API_VERSION
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_REFRESH_TOKEN
GOOGLE_LOGIN_CUSTOMER_ID       # 有 MCC 才填
GOOGLE_API_VERSION             # 可省略，預設 v26
GOOGLE_DEVELOPER_TOKEN         # 可選
LINE_CHANNEL_ACCESS_TOKEN
LINE_RECIPIENT_ID
LINE_RECIPIENTS_JSON           # 可選
LIVE_NOTIFICATIONS_ENABLED     # 先 false，驗收後才改 true
```

1. 先保持通知排程停用。在 Actions 手動執行 `廣告異常巡檢`，選 `preview`；網頁查看私人執行紀錄。
2. 用同區間、同層級、同事件與歸因設定，對照 Meta／Google 後台花費與轉換。
3. 確認對象後把 `LIVE_NOTIFICATIONS_ENABLED` 設為 `true`，手動選 `send` 進行一次真實通知驗收。這一步會真的發送 LINE。
4. 確認 LINE 收到、重跑不重複、失敗有紀錄後，再從網頁啟用通知排程。
5. 後續如果 Secret 關閉，排程只預覽，不發通知。成功 API 回應表示 LINE 接受請求，不保證對方未封鎖或實際已讀。

## 排程與免費限制

- Actions 固定每小時的第 7、37 分鐘巡檢；網頁時段採台灣時間。例：09:15 通知設定，正常會在09:37那次巡檢處理，另可能受 GitHub 延遲影響。這不是準點服務。
- 到期後取同日最近時段補跑；不補發昨天漏跑時段。每個規則／實體／資料日／收件對象只發一次，因此下午時段不會重複昨天同一筆異常。
- 主程式不改廣告預算、不停廣告，只讀數據與發提醒。
- Streamlit Community Cloud 可休眠；Actions 排程獨立，不需開著網頁。公開 repo 長期無活動的 schedule 可能被 GitHub 停用，需確認 Actions 狀態與恢復，網頁不保證自行喚醒被停用的 workflow。
- 公開 repo 的標準 Linux Actions runner 有免費使用條件。私人 repo 有帳號共用的用量上限；48次/日 × 30日 = 1,440次啟動。若每次按1分鐘計，約1,440分鐘；這只是估算，不含較久執行、重跑、其他專案與儲存量，並非免費保證。
- 不上傳包含廣告數據的公開 Actions artifacts；公開 log 只記狀態。執行結果只存私人 repo。
- LINE Push 會消耗官方帳號訊息額度，群組按收件人數計數。程式會合併訊息、查詢剩餘額度，但不能預先知道群組實際收件人數；若發送因額度不足失敗，保留結果並顯示錯誤，不能自動付費加購。
- LINE 重試碼有效期有限；結果不明超過23小時停止自動重試，需核對收件後由網頁解除，避免超過24小時以同碼再發造成重複。
- 不依賴 AI API，基本閾值判斷無模型費用。免費方案仍須追蹤平台政策與用量。

## 本機預覽與測試

Python 3.12：

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
DEMO_MODE=true streamlit run app.py
```

示範模式明確顯示人工示例，不讀真實 API、不發送 LINE、不保存到 GitHub。正式部署使用 `DEMO_MODE=false`。

目前測試涵蓋閾值邊界、先篩選後彙總、Google 小數轉換／PMax／成本事件合併、API 失敗不歸零、Meta 分頁、私人儲存庫限制、版本衝突、台灣日期與延遲補跑、LINE 防重與結果不明重試、多對象路由，以及 Streamlit 登入與六頁操作。測試不是對真實帳號的端到端驗收。

## 官方依據（2026/11/9 查詢）

- Streamlit 休眠：https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app
- Streamlit 儲存限制：https://docs.streamlit.io/develop/concepts/connections/connecting-to-data
- GitHub 用量：https://docs.github.com/en/billing/reference/product-usage-included
- GitHub schedule：https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- Google Ads OAuth：https://developers.google.com/google-ads/api/docs/oauth/overview
- Google 單一使用者授權：https://developers.google.com/google-ads/api/docs/oauth/single-user-authentication
- Google 存取管理變更：https://developers.google.com/google-ads/api/docs/api-policy/developer-token
- Google 報表 REST：https://developers.google.com/google-ads/api/rest/common/search
- Google PMax 報表：https://developers.google.com/google-ads/api/performance-max/reporting
- Meta Insights：https://developers.facebook.com/docs/marketing-api/insights/
- Meta 版本：https://developers.facebook.com/docs/graph-api/changelog/
- LINE 訊息額度：https://developers.line.biz/en/docs/messaging-api/pricing/
- LINE 重試：https://developers.line.biz/en/docs/messaging-api/retrying-api-request/

Google／Streamlit／GitHub／LINE 官方文件已取得；Meta 官方文件在此次查詢回傳429，未能核實當日最新版本與所有欄位變更。因此 Meta API version 必須由實際應用程式確認，並需做真實帳號驗收，不能宣稱已驗證上線。

### 規則與專案期間

規則可新增、編輯與刪除；刪除前會顯示規則名稱並要求確認。規則可選擇連結同一廣告帳號的專案，執行時讀取專案最新起訖日期與結案狀態。未連結時使用規則自己的資料起訖日。資料結束日仍在隔天早上檢查一次，下一天起顯示已到期；專案手動結案立即停止後續檢查。到期不刪除設定，保留查閱。

### Google project budget attribution (2026.11.20.20)

Budget plans support up to six literal conditions with AND/OR: campaign, ad group,
exact ad ID, RSA headlines, descriptions and path segments. `|` means alternatives
inside a text condition. The ad window limits cost dates. Preview reads real data
without saving. SEARCH costs use ad/day records; other channels retain campaign/day
records and require a campaign condition to match. PMax is not attributed by RSA copy.
Each ad/day cost is counted once, with reconciliation against campaign SEARCH costs.
Overlapping Google plan matches block budget calculation and ledger operations.
Copy is the API's current configuration, not a historical served-copy archive.
Existing plan IDs, original budgets and transaction history are retained.
The data overview continues to use campaign reports; it explicitly redirects
ad-level project filters to the budget page instead of showing misleading CPA.

Validation: 75 tests, including attribution rules, provider cost reconciliation,
conflict handling, preview/save UI and existing budget transfer flows. Actual
customer Google API reads require deployment and preview in the configured app.


### Cross-format Google budget attribution (2026.11.20.22)

The title/description/path selectors are no longer SEARCH-only. Format adapters
normalize RSA, responsive display, expanded text/dynamic-search, Demand Gen
(multi-asset/carousel/video/product), app, smart-campaign, text and supported video
copy fields exposed by the API. Formats without a selected field retain their
ad ID/cost; non-matching rows with unavailable fields are explicitly reported.
Unmapped/future formats are not claimed to have complete text support.

PMax uses asset-group/day cost joined to currently linked headline/long-headline/
description text and asset-group display paths. Its asset group names and exact
IDs have separate selectors and are never passed off as ad groups or ad IDs.
A text match attributes the entire group cost, not the cost of an individual asset
or served combination. Mixed-project groups must be separated or explicitly
assigned; overlapping plan attribution is rejected by group/day identity.
All detail costs reconcile against campaign/day totals before returning a report.
Existing budget snapshots are invalidated after the attribution upgrade.

Validation: 83 tests, including mixed SEARCH/PMax cost reconciliation, multi-asset
no-double-counting, multiple format normalization, unavailable-copy warnings,
asset-group identity overlap checks and preview/save UI. Live account API requests
remain to be verified in the deployed app.


### Unified project budget layout (2026.11.20.23)

A project has one outer card/title and a shared summary, with Meta and Google Ads
shown side by side (stacked on small screens). Platform headings contain only the
platform name. Original plan names, attribution notes and transfer details remain
available in expanders; existing saved names, IDs and ledger entries are untouched.
New platform plan names can be blank and default to the platform name. The editor
explains the difference between the project's name and the optional plan identifier.
Project totals use adjusted allocations and only sum known costs in one currency;
unknown data, mixed currencies or unset budgets do not produce misleading totals.
Money filters pick projects while retaining all their platform cards for comparison.
Validation: 84 tests, including project totals, missing/mixed currency cases and
existing save/transfer UI flows.

### Automatic project budget reads (2026.11.20.24)

Opening the budget page now forces a fresh read for that browser session. A
60-second Streamlit overview fragment checks/refreshes while the page is open;
filters use the current snapshot instead of making a request on every interaction.
Settings changes and Taipei day rollover invalidate the snapshot. Refresh cadence
is measured from request start, so API duration does not add an extra idle minute.
The overview fragment updates independently of the project/ledger editing forms.
The optional secondary button is now labelled 重新讀取; no initial click is needed.

Requests sharing an account and date window are deduplicated within each refresh,
then each plan's attribution conditions are applied independently. Failed reads
remain unknown and are retried on the next timed refresh. Polling does not write
settings, create budget transactions or send LINE. Spending still covers each
plan's complete ad window through yesterday; this is not today's live spend.

Validation: 87 tests, including opening without clicking refresh, reentry,
filtering without repeated reads, refresh expiry, settings/date invalidation,
request deduplication and existing financial/attribution/UI flows. Browser timer
scheduling and live API latency still require observing the deployed app.

### Include today's reported spend (2026.11.20.25)

Budget overview, previews and transfer validation now read through today in
Asia/Taipei, capped at each plan's ad end date. The first and final ad days can
therefore show reported spend before the day ends. Current-day figures are marked
即時數據 / 含今日未完整花費 and note platform reporting delays and later adjustments.
Automatic entry/minute refresh remains enabled. Snapshot keys invalidate earlier
through-yesterday budget data. Anomaly evaluation and scheduled LINE checks keep
their previous completed-day windows.

Today's Google campaign and detail requests are separate snapshots: a cost drift
is explicitly reported and detail cost is used only when both requests returned
the campaign/day key. Missing keys and historical discrepancies still fail closed.
This does not stop ads or change platform budgets; it updates decision visibility.
Validation: 89 tests, including ad start/end-day inclusion, ended-plan limits,
current-day snapshot drift versus historical/missing-data failures, and existing
anomaly date boundaries. Live deployment/API timing has not been observed.

### Manual refresh and independent period/ad badges (2026.11.20.26)

This supersedes the minute polling behavior above. A browser session loads budgets
on its first visit. There is no run_every timer and no time-based expiration;
returning to the page or changing filters reuses the snapshot. 重新讀取 fetches
again. Saved configuration changes and Taipei date changes invalidate the view.
Current-day reported spending and platform-latency notices remain unchanged.

Project titles are enlarged (30px desktop / 25px mobile), with separate labelled
檔期 and 廣告 badges. The period badge/filter uses project start/end dates only;
ad badges use platform plan dates and any manual plan closure. Preparing is amber,
running is green and closed is slate. The project management flag remains in the
editor (explicitly labelled as controlling anomaly checks); this change does not
silently reactivate rules or rewrite saved statuses. Meta-left/Google-right cards
and all allocation/transaction data are retained.

Meta Graph API error 4/17 now explains rate limiting rather than suggesting token
or permission failure. No raw platform error message or credential is displayed.
Validation: 91 tests, including no timer-based reads, navigation/manual refresh,
independent date/ad lifecycle states and sanitized rate-limit error handling.
Live deployment and Meta quota recovery have not been independently observed.

### Budget page visual hierarchy (2026.11.20.27)

The budget page now has a branded dark-green hero with a 48px page heading.
Each project has a separate dark-green title band with a 34px white project name,
a lime edge and independent period/ad state badges. Platform comparison columns
remain unchanged. The three navigation tabs retain native accessible tab behavior
but are rendered as full-width button-style controls with borders, 58px targets,
18px labels, selected-state fill and visible hover/keyboard focus states.
Small screens use stacked controls and adjusted heading sizes. No auto polling,
budget values, attribution settings or ledger records were changed.
Validation: all 91 existing financial, provider and UI tests pass. Visual changes
require the deployed page to load version .27 before they are visible.

### Real budget navigation buttons and site typography (2026.11.20.28)

The three budget navigation controls are now native Streamlit buttons with icons,
full-width hit targets, active primary styling and per-section rendering. They no
longer rely on CSS selectors for tab internals. Existing project save/preview and
budget transfer/reversal UI checks now navigate with these actual controls.
The page hero uses a banknote SVG icon rendered through a data-URI image in place
of the ambiguous NT$ text decoration.

Microsoft JhengHei is the configured body/heading/code font in both main/sidebar
themes; central CSS also covers widgets/popovers, while Vega-Lite config specifies
the chart font. Material icon glyphs retain their icon font. New widgets inherit
the theme. The font is resolved from the viewing device, with a fallback when it
is not installed; no proprietary font binary is bundled. AGENTS.md records the
font convention for future changes.
Validation: 91 tests pass, including real-button navigation through save, preview,
transfer and reversal flows. The deployed appearance still needs to load .28.

### Meta budget cost precision and reconciliation (2026.11.20.29)

Meta project budgets now request ad-level Insights with time_increment=all_days,
using the exact advertising window, instead of adding per-day spend values.
Overview trends and anomaly checks retain their daily query. Budget requests only
ask for cost and attribution identity, without unnecessary conversion metrics.
Raw spend strings are retained and summed with Decimal before display. Missing,
nonfinite or negative cost, incorrect returned dates, missing IDs and duplicate ad
IDs across pages fail closed. Ads sharing a name remain separate IDs.

The budget detail expander shows the matched ad count, whole-period basis, raw
cost, IDs and start/end dates, with a formula-neutralized CSV download for audit.
The configuration marker invalidates older session budget results on upgrade;
there is still no minute polling or automatic ad-budget mutation.

Evidence: the user-supplied Meta export for 2026-09-29 through 2026-11-18 has 37
ad rows whose Decimal spend sum is TWD 92,166, matching the supplied Ads Manager
screenshot. The prior dashboard screenshot shows 92,168. Daily accumulation is
an observed query difference, NOT a proven explanation of the two-dollar gap.
No manual correction or hard-coded spend has been introduced. Live API output
and ad IDs still need reconciliation; the export does not include ad IDs.
Validation: 99 tests pass, including whole-period request/pagination, same-name
ads, duplicate IDs, invalid money/dates, Decimal summation and existing UI,
Google attribution, ledger and anomaly behavior. Mock tests do not establish that
the deployed API result equals the user's export.

### Year and phase project navigation (2026.11.20.30)

The budget overview now has a dedicated left project rail in the main content,
separate from the global app sidebar. It offers a year selector, name search,
project-period status filter, phase groups with counts, selected project buttons
and a return-to-all-matches button. Running projects come first, then preparing,
then closed; closed projects are collapsible. The right pane renders only the
selected project or matching set, retaining Meta/Google side-by-side cards.

Navigation indexes stored project groups dynamically, once per project rather
than once per platform. Legacy ungrouped plans remain findable and labelled.
Status follows project dates independently of advertising closure and the legacy
manual alert-management flag. Cross-year projects are findable in each year they
span; the year selector is a lookup filter, not an annual cost allocation. A
caption explains that costs still use the full configured advertising window.
Search/year/status changes reset an incompatible selection instead of hiding it
silently. Zero matches and budget-filter exclusions have distinct empty states.

Native buttons, visible focus, brand #17421E and inherited Microsoft JhengHei
are retained. The long project list scrolls within the rail; narrow screens use
native stacked columns and a shorter list. The selected data pane adjusts metric
sizes to leave room for platform comparison. No data, ledger entries, date
windows, credentials or refresh triggers were changed. Selection reuses the
session report; only initial/config/date invalidation or manual reload fetches.

Validation: 101 tests pass. Added coverage for grouping versus platform children,
project-versus-ad status, cross-year lookup, legacy entries, search, project
selection, stale selection reset, year switching and reuse of a single spend
read across navigation. A local browser screenshot check could not run because
the execution environment blocks Chromium socket creation; deployed desktop and
mobile visual appearance has not been independently verified.

### Clear budget settings and preparing management state (2026.11.20.31)

Budget settings now present numbered project/platform steps, a brand-green intro,
a visible editing-context panel, larger field labels, white form surfaces and
full-width primary save actions. Project dates and ad dates have separate short
instructions; budget, attribution and save sections are explicitly labelled.
Three color-coded management explanations show preparing, running and closed.
Both project and platform management selectors now support preparing; new forms
default to preparing, while saved states are retained. Validation accepts and
round-trips it. A preparing project or plan pauses linked anomaly rules until
manually changed to running. Closed still stops rules; normal ad-date limits
still apply. Date-derived project navigation/badges and spend query windows are
unchanged, as are existing records and ledger amounts. Explanations distinguish
manual alert management from the date-derived project period.
Validation: 103 tests pass, including preparing-state validation/persistence,
rule pause/resume at either level, unchanged cost windows and the existing save,
ledger, attribution, navigation and precision suites. Deployed visual appearance
still needs confirmation; no browser screenshot was produced in this environment.

### Project funding status and encrypted invoices (2026.11.22.32)

A fourth native budget navigation button, 儲值與發票, adds a per-project/platform
invoice register. The overview displays independent Meta/Google funding badges,
active invoice counts and recognized amounts. The register summarizes platform
counts and recognized totals by currency, plus each plan's adjusted budget and
its existing cached API spend. Project spend is not summed into an account-wide
balance, and no wallet balance, payment verification or OCR is implied.

Per the user's definition, at least one effective saved invoice means 已儲值;
no effective invoice means 未儲值. A partial invoice still has that status but
its recognized amount and budget gap are shown separately. Metadata includes
invoice/reference number, issue/registration dates, face and allocated amounts,
currency, notes, file hash, stable project/account binding and creation time.
One invoice can be split across projects within the same account, with consistent
face value/currency and an allocation ceiling. Same-plan duplicate invoice/file
recognition is rejected. Corrections append a reasoned void, retaining original
metadata/documents; voiding the last effective invoice restores 未儲值. Existing
budget allocations, transfers, ad spend and anomaly behavior are unaffected.

PDF/PNG/JPEG files are required and limited to 5 MB each; suffix/magic, nonempty
content, names, document references and SHA-256 integrity are checked. Attachments
are Fernet-encrypted with the existing deployment CREDENTIALS_KEY and chunked
under invoice-documents/ in the existing private state repository. Every chunk
must be saved before metadata registration; settings use existing SHA conflict
checks. Partial uploads or a settings conflict may leave unreferenced encrypted
chunks, but never create a successful funding record. Download is on demand,
with decryption and hash/size verification, never a public repository URL. No
files or credentials are added to the application source repository.

Access remains governed by existing website sharing permissions: encryption at
rest does not restrict visitors who can open the app from using invoice upload,
download or void controls. No new login/role system was introduced. Production
sharing/authorized users have not been independently verified. State-repo backups
include encrypted attachments; restoring them requires the original key, which
must be backed up through company-approved secret handling separately. Exporting
settings alone does not export attachment bytes. DEMO_MODE uses only per-session
encrypted memory, never private-repo writes or real invoices.

Validation: 120 tests pass, covering missing evidence, upload/save/decrypt/read
round trip, overview linkage, platform isolation, partial funding, bad amounts,
duplicate and cross-project allocations, append-only voids, account/project
binding, chunked encryption, corruption/missing chunks, failed uploads, invalid
files and existing precision/ledger/navigation/alert flows. No real company
invoice was uploaded, and the deployed upload/download UI still needs live
acceptance after version .32 loads.

### Header account funding and spend totals (2026.11.22.33)

The budget page now shows the requested summary directly under the hero and
above the four navigation buttons, visible across overview/edit/ledger/invoice
sections. A combined band shows total invoice-recognized funding (可使用預算)
and actual account spend (已使用預算); side-by-side Meta/Google cards show each
platform's totals. Combined totals are withheld if any account read fails or
currencies differ. No registered invoices is labelled 尚未登錄發票, rather than
pretending the account has a verified zero funding balance. Different currencies
are displayed separately; no currency conversion or wallet-balance claim is made.

Spend is queried directly at Meta Insights account/all_days level and Google
customer cost_micros level. It is never the sum of overlapping project results.
Repeated configuration records for the same physical account are deduplicated;
integer Google micros and Decimal amounts preserve source precision. Missing,
malformed, negative, nonfinite or wrong-period results stay unknown, not zero.
Existing project/provider paths, invoices, funding states, allocations and
transfers are unchanged; a transfer never becomes additional funding.

All totals have an explicit date window through today in each account's time
zone. By default it begins at the oldest configured advertising start or invoice
registration date (including voided historical records so voiding does not shrink
the reporting window). Optional custom start is available under the calculation
expander. Funding includes effective invoice allocations registered in that same
window. The totals are not claimed as lifetime account totals or final billing;
platform reporting may delay/revise today's data. Windows beyond the existing
three-year single-request limit fail visibly; choose a supported custom window.

Initial/date/account/window changes read costs; ordinary tab, search and project
navigation reuses the session snapshot. 重新讀取全部預算 reloads account totals
and requests a project refresh when the overview renders. Invoice-only changes
recompute funding locally unless they expand the default query window. No
minute polling was added. 129 tests pass, covering unique-account queries,
account-vs-project scope, void/date exclusions, precision, unknown/error and mixed
currency states, provider request shapes and header visibility/cache/manual
refresh across navigation. No live cost totals or deployed visual screenshot have
been independently verified after this change.

### Planned budget totals, invoice follow-up and refined icon (2026.11.22.34)

The header labels are now 專案總預算 and 累計花費. Budget totals are summed from
all configured platform-plan envelopes, including preparing/closed plans and
ledger adjustments through today. Internal transfers remain neutral in the
overall sum. They do not depend on invoice recognition or the selected account
spend period. Spend remains the direct whole-account API cost for the displayed
period. The help text states these separate scopes, rather than implying a wallet
balance or an available-cash subtraction.

An invoice-follow-up line below each budget shows unique projects and missing
platform plans. A Meta/Google pair in one project counts as one missing project,
with two missing plans. Existing at-least-one-effective-invoice funding status is
unchanged, including the partial-allocation rule. The expandable pending list and
header invoice action open the existing invoice page, optionally preselecting the
exact plan. Project/platform records and all existing financial data are retained.

Budget currency uses returned account metadata or explicit account currency;
unconfirmed accounts remain separate labelled buckets. Different currencies are
never combined into a single amount. Unset zero budgets have a separate reminder.
The page hero replaces the banknote with a vector budget ledger and allocation
chart, using cream/lime accents on the existing #17421E surface.

Validation: 131 tests pass. New assertions cover budgets without invoices,
project-versus-plan pending counts, void reclassification, neutral transfers,
net adjustments and the preselected invoice shortcut without another API read.
Existing precision, encrypted documents, ledger, provider, UI and alert suites
remain passing. Deployed visual appearance still needs acceptance after .34 loads.

### Calm budget-page hierarchy and naming (2026.11.22.35)

Budget summary labels now consistently use 累積預算, including combined,
per-platform and per-project totals. Per-plan usable budget and all arithmetic
retain their existing meaning; no financial data or invoice state changed.

The budget workspace now scopes a warm-white/stone surface treatment with muted
champagne #B79A65 details, retaining Mori #17421E for hero/project title bands
and selected primary actions. Decorative lime strips on metrics, project title
edges and rail selection markers are replaced. Semantic green/amber/gray status
badges remain distinguishable. The page background loses its grid/green wash only
while this budget workspace is mounted. Other app pages retain their theme.

Account totals, native navigation and project content have explicit pale-gray
separators and consistent margins. Project/platform cards gain independent
padding, spacing and light borders, with shorter spacing on mobile. The workspace
also overrides the global ancestor:first-child metric styling that previously
made every Meta metric green merely because the platform occupied the left
column. Numeric cards now have a consistent warm-white surface and dark-green
values, reducing unintended emphasis. Selected-button hover keeps white text on
a dark-green fill; keyboard focus keeps a visible champagne outline. A duplicate
explanatory caption between summary and navigation was removed; date/reporting
information remains with the relevant totals and project read status.

Validation: all 131 tests passed after the name/layout change; the AppTest suite
was rerun after the final contrast/spacing cleanup. No new implementation-mirror
tests were added for reversible cosmetic changes. Real deployed desktop/mobile
appearance still requires visual acceptance after .35 loads.

### Independent three-KPI project panel and comparable remaining budget (2026.11.22.36)

The combined header is now a standalone warm-white section with its own heading,
border, elevation, spacious three-card grid and numeric type up to 54px. Budget,
spend and remaining have separate labelled surfaces; remaining uses a subtle
champagne treatment, with negative balances preserved and highlighted in red.
Mobile stacks the cards. Labels consistently use 累計預算 / 累計花費 / 剩餘預算.

The earlier header mixed all-plan budgets with full-account spend, explicitly
warning they could not be subtracted. This version makes all three primary KPIs
comparable: every configured plan contributes its adjusted budget and recognized
spend over that plan's advertising window through today, capped at its end date.
Remaining is exactly their difference. Future plans contribute known zero spend;
unset budgets, failed/invalid costs, currency mismatches or duplicate recognition
leave remaining unknown. Repeated ad IDs in overlapping Meta plan periods are
not guessed or double-summed. Currencies remain separate. No invoice or actual
budget/spend data was rewritten.

Both platform sections now also use the three comparable project values. Original
whole-account costs remain independently fetched and visible in each platform's
完整帳號花費（供對帳） expander, including the selected account date window and
read timestamp. Account reconciliation can include ads never registered as
projects, so its amount can differ from the primary project KPI; it is never
silently subtracted from project budgets or presented as a wallet balance.

A shared project snapshot loader runs before the primary KPI panel, so its values
are available on the first render. Header/detail reads share the same session
view; manual refresh updates then rerenders without a second API fetch. No minute
polling was added. Existing invoice actions and project navigation remain native.
Validation: 134 tests pass, including comparable-scope exact Decimal arithmetic,
negative balances, failure/unset/future distinctions, overlap rejection and the
existing initial/manual-only navigation, ledger, invoice and provider suites.
No live values or deployed responsive screenshot have been independently
verified after this change.


### 檔期投放模型（2026.11.27.59）

預設顯示全部「檔期」分類的集合模型，也可切換個別檔期。新檔樣本不足時仍列出實績與七日觀察；結案狀態不會停止讀取或排除模型。上方顯示總檔數與可擬合檔數，細節可展開核對。

「舊客量體來源」僅選實際 Meta 再行銷廣告組合及 Google 品牌搜尋活動，不需要填 CPA 上限。沒有確認來源就顯示缺口，不產生預算數字。量體上限是以現有母體、歷史頻次／CPM、品牌搜尋量／CTR／CPC形成的條件推估，與最低平均 CPA 的曲線判斷分開；不代表獲利最適上限。新舊客4:6不能直接換成預算4:6。

開頁或操作時檢查一小時快取；背景每六小時更新，可手動立即重讀。明細含今天的暫定回報，模型擬合避開今天及前三天。圖上邊界最低值會標示暫估，不再直接隱藏；跨檔回測未通過時呈現歷史觀察。所有金額為未稅廣告費，不含服務費。
