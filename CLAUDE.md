# JAOfilm DMCA Tool — CLAUDE.md

## 專案概要

版權侵權自動化執法工具。偵測盜版 → 生成 DMCA notice → 自動寄信 → 填寫 Google 表單 → 監控回信 → 自動確認下架。

本地路徑：`~/Projects/tools/jaofilm-dmca/`
GitHub：`github.com/JAOfilm-jao/jaofilm-dmca`（private）
Dashboard：`http://localhost:5002`（launchd 常駐，開機自動啟動）

---

## 日常使用（正常狀況下你只需要這幾件事）

### 1. 新增侵權 URL
開 `http://localhost:5002` → 貼 URL → 按「調查 + 申訴」→ 系統自動處理

### 2. Google DMCA 填表
按「填表」→ Chrome Debug Mode 必須開著 → Chrome 自動跑完 wizard + 填所有欄位 → 你勾 reCAPTCHA → 按「提交」→ **系統自動偵測成功頁、抓檢舉 ID、更新儀表板**

### 3. 掃描 DMCA 回信
按「掃描所有 DMCA 回信」→ 自動處理（見下方自動執行說明）

### 4. 需人工的情況（紅色清單）
- **主機商補件** → 收到 email → 手動回覆（法人全名 + 偽證聲明）
- **URL 仍存在但主機商稱已移除** → 手動確認後按「✓ 已下架」

---

## 自動執行的事（不需要你操作）

| 排程 | 動作 |
|------|------|
| URL 輸入後立即 | 調查 + 生成 notice + 寄出 host/CF email |
| 每小時 | monitor.py 掃描**所有** DMCA 回信（任意寄件人）|
| → 「已移除」類型 | ping URL → 確認 404 → 自動標 removed |
| → CF 含主機商 | 解析主機商 email → 自動補寄 host notice |
| → 主機商拒絕 | 記備註（denied）|
| 每 8 小時 | 案件 review → macOS 通知 |

---

## 工具檔案

| 檔案 | 用途 |
|------|------|
| `app.py` | **Flask Dashboard**（port 5002，主入口）|
| `templates/index.html` | Dashboard UI（填表 / 掃描 / 統計）|
| `main.py` | 調查 URL + 生成 notice + 存 DB + 更新狀態 |
| `mailer.py` | Email 批次寄出（含 `--auto-send` 全自動模式）|
| `google_dmca.py` | Google DMCA Playwright 全自動填表 + 自動回報 report ID |
| `monitor.py` | Gmail API 掃描**所有** DMCA 回信 → URL 驗證 → 自動標 removed |
| `reinvestigate.py` | RDAP 重查 abuse email（找不到時用）|
| `investigate.py` | WHOIS / IP / Cloudflare 偵測 |
| `generate.py` | 生成 host / cloudflare / google notice |
| `tracker.py` | SQLite CRUD（含 `google_report_id` 欄位）|
| `config.py` | 常數、白名單、平台聯絡方式 |
| `open_chrome_debug.sh` | 開啟 Chrome CDP debug mode |
| `tracker.db` | SQLite 案件資料庫（不入 git）|
| `notices/` | 已生成的 notice 文字檔 |
| `.env` | SMTP 密碼 + API key（不入 git）|
| `.gmail_credentials.json` | Gmail OAuth（不入 git）|
| `.gmail_token.json` | Gmail token（不入 git）|
| `.processed_cf_emails.log` | 已處理信件 ID 記錄（不入 git）|

---

## launchd 管理

```bash
# 重啟 Dashboard
launchctl unload ~/Library/LaunchAgents/com.jaofilm.dmca.plist
launchctl load   ~/Library/LaunchAgents/com.jaofilm.dmca.plist

# 查看 log
tail -f ~/Projects/tools/jaofilm-dmca/logs/app.log
```

---

## Chrome Debug Mode（Twitter/X + Google DMCA 前置）

```bash
bash open_chrome_debug.sh
# 驗證：curl -s http://127.0.0.1:9222/json/version
```

- **user-data-dir**：`~/.jaofilm-dmca-chrome`（獨立 profile，與主 Chrome 互不干擾）
- CDP port：`http://127.0.0.1:9222`
- **Twitter/X**：必須登入 **@jaofilm_DMCA**（dmca@jaofilm.com）
  - Google 帳號可用 jaochihwei@gmail.com（dmca@ 是別名，同一帳號）
- **必須在點「填表」前確認開著**

### 首次設定（只需做一次）

```bash
bash open_chrome_debug.sh   # 開啟獨立 Chrome
# → 在開啟的 Chrome 視窗：
#   1. 前往 x.com → 登入 @jaofilm_DMCA
#   2. 關閉 Chrome（登入狀態會保存在 ~/.jaofilm-dmca-chrome）
# → 之後每次執行 open_chrome_debug.sh，@jaofilm_DMCA 就已登入
```

### 為何帳號是關鍵

推特 DMCA 表單的 email 欄位由登入帳號自動帶入且鎖定。
@jaofilm_DMCA 用 dmca@jaofilm.com 註冊 → email domain = jaofilm.com = 被侵權網站 domain → 推特確認版權所有人身分。
（2026-06-12 實測：使用此帳號手動填表後隔天成功下架）

---

## 申請人固定資料

| 欄位 | 值 |
|------|-----|
| First name | CHIH WEI |
| Last name | JAO |
| Company | JAOfilm（品牌名，無需登記）|
| Signature | CHIH WEI JAO（必須完全符合 First + Last）|
| Email | dmca@jaofilm.com（由 @jaofilm_DMCA 帳號自動帶入，不需手動填）|
| Country | Taiwan |
| Copyright URL | https://jaofilm.com/films/{slug}（具體影片頁，從 films.json 帶入）|

---

## 平台優先順序

1. **Google DMCA** → 斷搜尋流量，乘數效果最大（`google_dmca.py`）
2. **Cloudflare** → email 寄 `abuse@cloudflare.com`（回信會揭露主機商）
3. **主機商** → `mailer.py` 自動寄
4. **PH / XV / Telegram** → `mailer.py` 自動寄

---

## 重要技術注意（2026-06-03 更新）

### Google DMCA Wizard 流程（現行，2026-06-03 修正）

```
Google 搜尋（頂層，單一 radio）
  → nth(0) 點選子類型「Google 搜尋」（非 AI Overviews）
  → 否（不是 AI 生成內容）
  → 法律原因
  → 智慧財產
  → 版權
  → nth(0)（是版權所有人）
  → 其他（影片類型）
  → 點擊「提出申訴」link
  → 填表單（aria-label 欄位，非 <label> 元素）
  → 日期：格式「3 6月 2026」，需含月份比對避免點到錯月
  → 填完後輪詢成功頁 → 自動抓 report ID → POST /google-dmca-reported
```

⚠️ **舊流程已失效**：2026 年 Google 改版後，「第二個 Google 搜尋 radio count>1」的判斷不再適用。

### 表單欄位 aria-label（Google DMCA 表單）

| 欄位 | aria-label |
|------|-----------|
| 著作說明 | `在這裡輸入說明` |
| 版權著作 URL | `在這裡輸入範例` |
| 侵權 URL | `在這裡輸入網址` |
| 簽名 | `簽名` |

### monitor.py 分類邏輯

| 分類 | 判斷條件 | 動作 |
|------|---------|------|
| `cf_receipt` | from: cloudflare.com，不含主機商 | 跳過 |
| `cf_info` | from: cloudflare.com，含「host for the reported domain is」| 解析主機商 → 補寄 |
| `removed` | 任意寄件人，含移除關鍵字 | ping URL → 確認才標 removed |
| `denied` | 任意寄件人，含拒絕關鍵字 | 記備註 |
| `unknown` | 其他 | 記備註 |

- **CF sender**：`abuse@cloudflare.com`（非 `abuse@notify.cloudflare.com`）
- **Gmail query**：`to:jao@jaofilm.com DMCA newer_than:60d`

### 其他注意

- **Cloudflare form 封鎖 bot** → 改用 email，不用填表單
- **簽名驗證**：Google 要求完全符合 First + Last（CHIH WEI JAO）
- **主機商補件**（如 Razorblade）：需提供法人全名 + 偽證聲明
- **browser_filler.py 已棄用**：browser-use 太貴（Opus $5/次）
- **Gmail API**：jao@jaofilm.com 帳號，JAOfilm Autoposter GCP 專案
- **subprocess 無 stdin**：google_dmca.py 不可用 `input()`，否則 EOFError crash

---

## .env 格式

```
JAO_SMTP_HOST=smtp.mailgun.org
JAO_SMTP_PORT=587
JAO_SMTP_USER=postmaster@mg.jaofilm.com
JAO_SMTP_PASS=<Mailgun SMTP 密碼>
JAO_ANTHROPIC_API_KEY=<備用>
```

---

## 尚未建立

- **Discovery**：自動掃描新侵權 URL（SerpAPI / Google Custom Search API）
- **自動回覆**：設計決策保持人工確認，避免發出錯誤法律聲明
