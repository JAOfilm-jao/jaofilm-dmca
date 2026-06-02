# JAOfilm DMCA Tool — CLAUDE.md

## 專案概要

版權侵權自動化執法工具。偵測盜版 → 生成 DMCA notice → 自動寄信 → 填寫 Google 表單 → 監控回信。

本地路徑：`~/Projects/tools/jaofilm-dmca/`
GitHub：`github.com/JAOfilm-jao/jaofilm-dmca`（private）
Dashboard：`http://localhost:5002`（launchd 常駐，開機自動啟動）

---

## 日常使用（正常狀況下你只需要這兩件事）

### 1. 新增侵權 URL
開 `http://localhost:5002` → 貼 URL → 按「調查 + 申訴」→ 系統自動處理

### 2. 處理紅色清單
收到 macOS 通知 → 開 Dashboard → 紅色清單：
- **Google DMCA** → 按「填表」→ Chrome 自動填完 → 你按送出
- **主機商補件** → 收到 email → 手動回覆（法人全名 + 偽證聲明）
- **確認下架** → 點「🔗 查看頁面」→ 確認 404 → 按「✓ 已下架」

---

## 自動執行的事（不需要你操作）

| 排程 | 動作 |
|------|------|
| URL 輸入後立即 | 調查 + 生成 notice + 寄出 host/CF email |
| 每小時 | monitor.py 掃描 CF 回信 → 解析主機商 → 自動補寄 |
| 每 8 小時 | 檢查需要人工的案件 → macOS 通知 |

---

## 工具檔案

| 檔案 | 用途 |
|------|------|
| `app.py` | **Flask Dashboard**（port 5002，主入口）|
| `templates/index.html` | Dashboard UI |
| `main.py` | 調查 URL + 生成 notice + 存 DB + 更新狀態 |
| `mailer.py` | Email 批次寄出（含 `--auto-send` 全自動模式）|
| `google_dmca.py` | Google DMCA Pure Playwright 填表（**免費**）|
| `monitor.py` | Gmail API 掃描 CF 回信 → 自動補寄主機商 |
| `reinvestigate.py` | RDAP 重查 abuse email（找不到時用）|
| `investigate.py` | WHOIS / IP / Cloudflare 偵測 |
| `generate.py` | 生成 host / cloudflare / google notice |
| `tracker.py` | SQLite CRUD |
| `config.py` | 常數、白名單、平台聯絡方式 |
| `open_chrome_debug.sh` | 開啟 Chrome CDP debug mode |
| `tracker.db` | SQLite 案件資料庫（不入 git）|
| `notices/` | 已生成的 notice 文字檔 |
| `.env` | SMTP 密碼 + API key（不入 git）|
| `.gmail_credentials.json` | Gmail OAuth（不入 git）|
| `.gmail_token.json` | Gmail token（不入 git）|

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

## Chrome Debug Mode（Google DMCA 前置）

```bash
bash open_chrome_debug.sh
# 驗證：curl -s http://127.0.0.1:9222/json/version
```

- user-data-dir：`~/.jaofilm-dmca-chrome`（專用 profile，非預設）
- CDP port：`http://127.0.0.1:9222`
- 已登入 Google（jaochihwei@gmail.com）

---

## 申請人固定資料

| 欄位 | 值 |
|------|-----|
| First name | CHIH WEI |
| Last name | JAO |
| Company | JAOfilm（品牌名，無需登記）|
| Signature | CHIH WEI JAO（必須完全符合 First + Last）|
| Email | info@jaofilm.com |
| Country | Taiwan |
| Copyright URL | https://jaofilm.com |

---

## 平台優先順序

1. **Google DMCA** → 斷搜尋流量，乘數效果最大（`google_dmca.py`）
2. **Cloudflare** → email 寄 `abuse@cloudflare.com`（回信會揭露主機商）
3. **主機商** → `mailer.py` 自動寄
4. **PH / XV / Telegram** → `mailer.py` 自動寄

---

## 重要技術注意

- **Cloudflare form 封鎖 bot** → 改用 email，不用填表單
- **Cloudflare 回信揭露主機商** → monitor.py 自動解析並補寄
- **Google DMCA wizard 流程**（google_dmca.py 硬寫死，免費）：
  Google 搜尋 → 否(AI) → 法律原因 → 智慧財產 → 版權 → 是(版權人) → 其他(影片) → 提出申訴
- **簽名驗證**：Google 要求完全符合 First + Last（CHIH WEI JAO）
- **主機商補件**（如 Razorblade）：需提供法人全名 + 偽證聲明
- **browser_filler.py 已棄用**：browser-use 太貴（Opus $5/次）
- **Gmail API**：jao@jaofilm.com 帳號，JAOfilm Autoposter GCP 專案

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

- **自動偵測 404**：定期 ping 侵權 URL，自動標記 removed
- **Discovery**：自動掃描侵權 URL（Google Custom Search API）
