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
| `APP_PASSWORD` | 至少 10 字元的隨機管理密碼；範例密碼不能使用 |
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
