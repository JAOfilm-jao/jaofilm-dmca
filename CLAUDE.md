# JAOfilm DMCA Tool — CLAUDE.md

## 專案概要

版權侵權自動化執法工具。偵測盜版 → 生成 DMCA notice → 自動寄信 → 填寫 Google 表單。

本地路徑：`~/Projects/tools/jaofilm-dmca/`

---

## 完整 SOP

```bash
# 1. 調查新侵權 URL + 生成所有 notice
python3 main.py file <url> --film "影片名稱"

# 2. 寄出 email（host / Cloudflare）
python3 mailer.py          # 列出待寄清單
python3 mailer.py send     # 批次寄出，逐一 Y 確認

# 3. Google DMCA 填表（免費，Pure Playwright）
bash open_chrome_debug.sh  # 先確認 Chrome 在 debug mode
python3 google_dmca.py notices/<date>_<domain>_google.txt
# → Chrome 自動填完 → 你確認內容 → 按送出

# 4. 更新狀態
python3 main.py update <id> submitted --notes "Google ID: 4-xxx"
python3 main.py list
```

---

## 工具檔案

| 檔案 | 用途 |
|------|------|
| `main.py` | 主工具：調查 + 生成 notice + 存 DB + 更新狀態 |
| `investigate.py` | WHOIS / IP / Cloudflare 偵測 |
| `generate.py` | 生成 host / cloudflare / google notice |
| `tracker.py` | SQLite CRUD |
| `config.py` | 常數、白名單、平台聯絡方式 |
| `mailer.py` | Email 自動批次寄出（SMTP via Mailgun）|
| `google_dmca.py` | Google DMCA Pure Playwright 填表（免費）|
| `open_chrome_debug.sh` | 開啟 Chrome CDP debug mode |
| `tracker.db` | SQLite 案件資料庫 |
| `notices/` | 已生成的 notice 文字檔 |
| `.env` | SMTP 密碼 + Anthropic API key（不入 git）|

---

## Chrome Debug Mode（google_dmca.py 前置條件）

```bash
bash open_chrome_debug.sh
# 驗證：curl -s http://127.0.0.1:9222/json/version
```

- user-data-dir：`~/.jaofilm-dmca-chrome`（專用 profile）
- CDP port：`http://127.0.0.1:9222`
- 已登入 Google（jaochihwei@gmail.com），重開後自動保持登入

---

## 申請人固定資料

| 欄位 | 值 |
|------|-----|
| First name | CHIH WEI |
| Last name | JAO |
| Company | JAOfilm |
| Signature | CHIH WEI JAO（必須完全符合 First + Last）|
| Email | info@jaofilm.com |
| Country | Taiwan |
| Copyright URL | https://jaofilm.com |

---

## 平台優先順序

1. **Google DMCA** → 斷搜尋流量，乘數效果最大
2. **Cloudflare** → email 直接寄 `abuse@cloudflare.com`（會回信揭露主機商）
3. **主機商** → `mailer.py` 自動寄
4. **PH / XV / Telegram** → `mailer.py` 自動寄

---

## 重要技術注意

- **Cloudflare form 封鎖 bot** → 改用 email 直接寄，不用填表單
- **Cloudflare 回信會揭露主機商** → 拿到 host abuse email 立即補 `mailer.py send`
- **Google DMCA wizard 流程**（google_dmca.py 硬寫死）：
  Google 搜尋 → 否(AI) → 法律原因 → 智慧財產 → 版權 → 是(版權人) → 其他(影片) → 提出申訴
- **簽名驗證**：Google 要求 Signature 完全符合 First name + Last name（CHIH WEI JAO）
- **主機商補件**（如 Razorblade）：需提供法人全名 + 偽證聲明
- **browser_filler.py 已棄用**：browser-use 太貴（Opus $5/次），改用 Pure Playwright

---

## .env 格式

```
JAO_SMTP_HOST=smtp.mailgun.org
JAO_SMTP_PORT=587
JAO_SMTP_USER=postmaster@mg.jaofilm.com
JAO_SMTP_PASS=<Mailgun SMTP 密碼>
JAO_ANTHROPIC_API_KEY=<備用，browser_filler.py 用>
```

---

## 尚未建立

- Phase C：Streamlit Dashboard（視覺化追蹤）
- Phase D：Gmail API 監控（CF 回信自動補寄主機商）
- Discovery：自動掃描侵權 URL（SerpAPI）
