#!/usr/bin/env python3
"""
JAOfilm DMCA Monitor — 全收件匣 DMCA 回信自動處理

掃描邏輯：
  1. 掃所有回到 jao@jaofilm.com 的 DMCA 相關信件（任何寄件人）
  2. 分類：
     - removed   → ping URL 驗證 → 確認 404 才標 removed
     - cf_info   → 解析主機商 → 自動補寄 host notice
     - denied    → 標記無法處理，人工確認
     - unknown   → 顯示在儀表板等人工處理
  3. 每次掃描後若有 URL 仍然存在但主機商已回應，標 needs_check

用法：
  python3 monitor.py          # 手動跑一次
  python3 monitor.py --watch  # 每 10 分鐘掃一次
"""

import re
import sys
import time
import base64
import requests
from datetime import date, datetime
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

import tracker
import mailer
from generate import generate_host
from config import COPYRIGHT_OWNER, BRAND_NAME, CONTACT_EMAIL, WEBSITE

# ── 設定 ──────────────────────────────────────────────────────────────────────

SCOPES           = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_PATH       = Path(__file__).parent / ".gmail_token.json"
CREDENTIALS_PATH = Path(__file__).parent / ".gmail_credentials.json"
PROCESSED_LOG    = Path(__file__).parent / ".processed_cf_emails.log"

# 移除確認關鍵字（任何寄件人）
REMOVAL_SIGNALS = [
    "successfully removed",
    "has been disabled",
    "content has been removed",
    "content has been taken down",
    "removed the content",
    "disabled the content",
    "status: closed",
    "ticket.*closed",
    "we have removed",
    "have been removed",
    "already been removed",
]

# 拒絕/無法處理關鍵字
DENIAL_SIGNALS = [
    "unable to take action",
    "not our client",
    "independent third-party",
    "no affiliation",
    "unable to comply",
    "we cannot remove",
    "not hosted by us",
    "not responsible",
]

# ── Gmail 認證 ────────────────────────────────────────────────────────────────

def get_gmail_service():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                print(f"❌  請先建立 {CREDENTIALS_PATH}")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)

# ── 信件分類 ──────────────────────────────────────────────────────────────────

def classify_email(sender: str, subject: str, body: str) -> str:
    """
    回傳分類：
      cf_receipt    - CF / 登記商收件確認
      cf_info       - CF 含主機商資訊
      x_supplement  - X/Twitter 要求補件（DMCA 格式）
      removed       - 任何寄件人確認移除
      denied        - 拒絕處理
      unknown       - 需人工判斷
    """
    sender_l = sender.lower()
    body_l   = body.lower()

    # Google removals 信件
    if "removals@google.com" in sender_l:
        if "已提交過" in body or "previously submitted" in body_l:
            return "google_duplicate"
        # 移除確認：Google 搜尋已將 URL 從索引移除
        if re.search(
            r"we.ll remove these urls|remove these urls from our search results|"
            r"remove the following urls|will be removed from our search",
            body_l
        ):
            return "google_removed"
        return "cf_receipt"  # 其他 Google 信（收件確認等）

    # Cloudflare 信件
    if "cloudflare.com" in sender_l:
        if re.search(r"host for the reported domain is", body, re.I):
            return "cf_info"
        return "cf_receipt"

    # 登記商/一般收件確認
    if any(s in sender_l for s in ("name.com", "godaddy.com", "namecheap.com")):
        if re.search(r"report received|thank you for contacting|this inbox is not monitored", body_l):
            return "cf_receipt"

    # X/Twitter 信件
    if "legal-support@x.com" in sender_l or "legal-support@twitter.com" in sender_l:
        if re.search(r"please submit the following information|electronic signature", body_l):
            return "x_supplement"
        # 下架確認（線上表單 DMCA 被接受後的回信）
        if re.search(
            r"removed|disabled|taken down|actioned|complied with|removed the content|"
            r"we have acted|content.*removed|has been suspended",
            body_l
        ):
            return "x_removed"
        # 拒絕
        if re.search(
            r"not find a violation|no violation|unable to action|does not violate|"
            r"not a copyright|counter.?notice|not constitute",
            body_l
        ):
            return "x_denied"
        return "cf_receipt"  # 收件確認，跳過

    # 移除確認
    for sig in REMOVAL_SIGNALS:
        if re.search(sig, body_l):
            return "removed"

    # 拒絕
    for sig in DENIAL_SIGNALS:
        if re.search(sig, body_l):
            return "denied"

    return "unknown"

# ── URL 驗證 ──────────────────────────────────────────────────────────────────

def verify_url_down(url: str) -> bool:
    """回傳 True 表示內容確認已移除（404/403/410/connection error）"""
    # Twitter/X SPA 對未登入請求回 404，無法用 curl 判斷真實狀態
    # 依賴 email 確認即可，不做 ping 驗證
    if re.search(r'(x\.com|twitter\.com)/\w+/status/', url or ""):
        return True
    try:
        resp = requests.get(url, timeout=15, allow_redirects=True,
                            headers={"User-Agent": "Mozilla/5.0"})
        # 404/410 = 明確移除；403 = 可能封鎖（視為移除）
        if resp.status_code in (404, 410, 403):
            return True
        # 200 但內容消失（常見：頁面存在但 embed 被移除）— 需人工確認
        return False
    except Exception:
        # 連線失敗 = domain 可能已下線
        return True

# ── 解析 CF 主機商資訊 ────────────────────────────────────────────────────────

def compose_x_dmca_reply(infringing_url: str, film_title: str) -> str:
    from config import COPYRIGHT_OWNER, CONTACT_EMAIL, WEBSITE
    return f"""1. Electronic Signature:
{COPYRIGHT_OWNER}

2. Description of Copyrighted Work:
Original adult film produced and exclusively owned by JAOfilm.
Title: {film_title}
Link to authorized work: {WEBSITE}

3. Location of Infringing Material:
{infringing_url}

4. Contact Information:
JAOfilm
{CONTACT_EMAIL}
+1 267 551 0981
Taipei, Taiwan

5. Good Faith Statement:
I have a good faith belief that the use of the material in the manner complained of isn't authorized by the copyright owner, its agent, or the law.

6. Accuracy Statement:
I swear under penalty of perjury that I am authorized to act on behalf of the copyright owner.
"""


def parse_cf_host_info(body: str) -> dict:
    result = {"domain": None, "host_org": None, "host_email": None, "report_id": None}

    m = re.search(r"Report ID[:\s]+([a-f0-9]{16})", body, re.I)
    if m:
        result["report_id"] = m.group(1)

    m = re.search(r"regarding[:\s]+(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", body, re.I)
    if m:
        result["domain"] = m.group(1).lower().rstrip(".")

    m = re.search(
        r"host for the reported domain is[:\s]*\n([^\n]+)\n([\w.+-]+@[\w.-]+\.\w+)",
        body, re.I | re.M
    )
    if m:
        result["host_org"]   = m.group(1).strip()
        result["host_email"] = m.group(2).strip()

    return result

# ── 從信件 body 找對應案件 ────────────────────────────────────────────────────

def find_case_by_email_body(sender: str, subject: str, body: str):
    """從 DB 找最可能對應的案件（用 domain / URL 比對）"""
    rows = tracker.list_all()
    # 先從 subject / body 抓 domain
    domains_found = re.findall(
        r'\b([a-zA-Z0-9-]+\.(?:com|tv|net|org|me|info|co))\b',
        subject + " " + body
    )
    for row in rows:
        row_domain = (row["domain"] or "").lower()
        if not row_domain:
            continue
        for d in domains_found:
            if row_domain in d.lower() or d.lower() in row_domain:
                return row
    # Fallback：比對寄件人 email 與 abuse_emails
    sender_domain = sender.split("@")[-1].lower() if "@" in sender else ""
    for row in rows:
        emails = (row["abuse_emails"] or "").lower()
        if sender_domain and sender_domain in emails:
            return row
    return None

# ── 已處理記錄 ────────────────────────────────────────────────────────────────

def is_processed(msg_id: str) -> bool:
    if PROCESSED_LOG.exists():
        return msg_id in PROCESSED_LOG.read_text()
    return False

def mark_processed(msg_id: str):
    with PROCESSED_LOG.open("a") as f:
        f.write(msg_id + "\n")

# ── 解碼信件 body ─────────────────────────────────────────────────────────────

def decode_body(msg: dict) -> str:
    body = ""
    payload = msg.get("payload", {})
    if payload.get("body", {}).get("data"):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
    else:
        for part in payload.get("parts", []):
            if part.get("mimeType") in ("text/plain", "text/html"):
                data = part.get("body", {}).get("data", "")
                if data:
                    body += base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    return body

def get_header(msg: dict, name: str) -> str:
    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""

# ── 主掃描邏輯 ────────────────────────────────────────────────────────────────

def scan_once(service, dry_run=False) -> dict:
    print(f"\n🔍  掃描 DMCA 信件... ({datetime.now().strftime('%H:%M:%S')})")

    # 掃所有 DMCA 相關信件（jao@ 和 info@ 都在同一個帳號，不限 to:）
    query = "(DMCA OR from:removals@google.com OR from:legal-support@x.com OR from:legal-support@twitter.com) newer_than:60d -from:me"
    result = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
    messages = result.get("messages", [])

    if not messages:
        print("  ✅  沒有新的 DMCA 回信")
        return {"processed": 0, "removed": 0, "cf_info": 0, "denied": 0, "unknown": 0}

    stats = {"processed": 0, "removed": 0, "cf_info": 0, "denied": 0, "unknown": 0}

    for msg_ref in messages:
        msg_id = msg_ref["id"]
        if is_processed(msg_id):
            continue

        msg     = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        sender  = get_header(msg, "from")
        subject = get_header(msg, "subject")
        body    = decode_body(msg)
        kind    = classify_email(sender, subject, body)

        print(f"\n  📨  [{kind}] {sender[:50]}")
        print(f"      Subject: {subject[:70]}")

        # ── Google 重複送出警告 ────────────────────────────────────────────
        if kind == "google_duplicate":
            # 從 body 抓侵權 URL（Google 格式：「關於以下網址：https://...」）
            url_m = re.search(r'關於以下網址：\s*(https?://\S+)', body)
            if url_m:
                dup_url = url_m.group(1).rstrip('。').rstrip(',')
            else:
                # fallback：body 裡第一個非 google.com 的 URL
                for candidate in re.findall(r'https?://[^\s,）\)]+', body):
                    if "google.com" not in candidate:
                        dup_url = candidate.rstrip('。').rstrip(',')
                        break
                else:
                    dup_url = None

            if dup_url:
                all_rows = tracker.list_all()
                matched  = [r for r in all_rows if r["url"] == dup_url]
                for case in matched:
                    existing = case["notes"] or ""
                    if "Google 重複警告" not in existing and not dry_run:
                        tracker.update(
                            case["id"], case["status"],
                            existing + f" | Google 重複警告 {datetime.now().strftime('%Y-%m-%d')} — 勿再次送出"
                        )
                print(f"      ⚠️  Google 重複警告 → {dup_url[:70]}")
            else:
                print(f"      ⚠️  Google 重複警告（無法解析 URL）")

            mark_processed(msg_id)
            stats["processed"] += 1
            continue

        # ── Google 搜尋移除確認：驗證每個 URL ─────────────────────────────
        if kind == "google_removed":
            # 從 body 抓所有非 Google URL
            raw_urls = re.findall(r'https?://\S+', body)
            infringing = [
                u.rstrip('.,;)\n>') for u in raw_urls
                if "google.com" not in u.lower()
            ]

            if not infringing:
                print("      ⚠️  Google 移除確認信：無法解析侵權 URL")
                mark_processed(msg_id)
                stats["unknown"] += 1
                continue

            # 找對應案件（先 domain 比對，再 URL 直接命中）
            case = find_case_by_email_body(sender, subject, body)
            if not case:
                all_rows = tracker.list_all()
                for row in all_rows:
                    if row["url"] in infringing:
                        case = row
                        break

            if not case:
                print(f"      ⚠️  找不到對應案件（sample: {infringing[0][:60]}）")
                mark_processed(msg_id)
                stats["unknown"] += 1
                continue

            print(f"      案件 #{case['id']} {case['domain']}")
            print(f"      Google 確認移除 {len(infringing)} 個 URL，逐一驗證...")

            # 同步 extra_urls 至 DB（若尚未存入）
            if not case["extra_urls"] and not dry_run:
                extras = [u for u in infringing if u != case["url"]]
                if extras:
                    tracker.set_extra_urls(case["id"], extras)
                    print(f"      📝  extra_urls 已寫入 DB（{len(extras)} 個）")

            # 同步 google_report_id（從 subject 解析，若尚未記錄）
            rid_m = re.search(r'\[(\d+-\d+)\]', subject)
            if rid_m and not case["google_report_id"] and not dry_run:
                tracker.set_google_report_id(case["id"], rid_m.group(1))

            # 逐一 ping 每個 URL
            n_down = sum(1 for u in infringing if verify_url_down(u))
            primary_down = verify_url_down(case["url"])

            if primary_down:
                note = (
                    f"Google 搜尋移除確認 {len(infringing)} URL，"
                    f"實際驗證 {n_down}/{len(infringing)} 已下線 ({datetime.now().strftime('%Y-%m-%d')})"
                )
                print(f"      ✅  主 URL 已下線 → 標記 removed（{n_down}/{len(infringing)} 驗證通過）")
                if not dry_run:
                    tracker.update(case["id"], "removed", note)
                stats["removed"] += 1
            else:
                existing = case["notes"] or ""
                note = (
                    f"Google 搜尋已除索 {len(infringing)} URL，"
                    f"但主 URL 仍可存取 {n_down}/{len(infringing)} 已下線 ({datetime.now().strftime('%Y-%m-%d')})"
                )
                print(f"      ⚠️  主 URL 仍存在（{n_down}/{len(infringing)} 下線），記備註")
                if not dry_run:
                    tracker.update(case["id"], case["status"], existing + " | " + note)
                stats["unknown"] += 1

            mark_processed(msg_id)
            stats["processed"] += 1
            continue

        # ── CF / 登記商收件確認：跳過 ─────────────────────────────────────
        if kind == "cf_receipt":
            print("      → 收件確認，跳過")
            mark_processed(msg_id)
            continue

        # ── X/Twitter 補件請求：自動草稿 ──────────────────────────────────
        if kind == "x_supplement":
            case = find_case_by_email_body(sender, subject, body)
            # 從 subject 抓 ticket ID
            ticket_m = re.search(r'(LEGAL-\d+)', subject)
            ticket_id = ticket_m.group(1) if ticket_m else "LEGAL-UNKNOWN"

            infringing_url = case["url"] if case else ""
            film_title     = case["film_title"] if case else "JAOfilm series"
            reply_body     = compose_x_dmca_reply(infringing_url, film_title)

            action = {
                "type":    "x_reply",
                "to":      "legal-support@x.com",
                "subject": f"Re: {ticket_id}: DMCA Copyright Infringement Notice – JAOfilm",
                "body":    reply_body,
                "ticket_id": ticket_id,
            }

            if case and not dry_run:
                tracker.set_pending_action(case["id"], action)
                print(f"      ✅  X 補件草稿已存入 case #{case['id']}，待你在 Dashboard 確認送出")
            else:
                print(f"      ⚠️  X 補件，找不到對應案件（ticket={ticket_id}）")
                if not dry_run:
                    # 建新 case 存入
                    inv = {"domain": "x.com", "ip": "", "hosting_org": "", "hosting_country": "US",
                           "is_cloudflare": False, "platform": {"name": "Twitter/X", "email": "legal-support@x.com"},
                           "abuse_emails": []}
                    new_id = tracker.add(infringing_url or "https://x.com/", "JAOfilm series", inv)
                    tracker.set_pending_action(new_id, action)
                    tracker.update(new_id, "submitted")
                    print(f"      ✅  新建 case #{new_id} 並存入草稿")

            mark_processed(msg_id)
            stats["processed"] += 1
            continue

        # ── X/Twitter 下架確認 ────────────────────────────────────────────
        if kind == "x_removed":
            ticket_m  = re.search(r'(LEGAL-\d+)', subject)
            ticket_id = ticket_m.group(1) if ticket_m else None
            case = None
            if ticket_id:
                for row in tracker.list_all():
                    if dict(row).get("twitter_report_id") == ticket_id:
                        case = row
                        break
            if not case:
                case = find_case_by_email_body(sender, subject, body)

            if not case:
                print(f"      ⚠️  X 下架確認找不到對應案件 (ticket={ticket_id})")
                mark_processed(msg_id)
                stats["unknown"] += 1
                continue

            url = case["url"]
            print(f"      案件 #{case['id']} {case['domain']} (ticket={ticket_id})")
            # Twitter/X SPA 無法用 curl 驗證，一律記備註待人工到儀表板確認
            print(f"      ℹ️  Twitter URL 無法自動驗證，記備註待人工確認")
            if not dry_run:
                existing = case["notes"] or ""
                tracker.update(case["id"], case["status"],
                               existing + f" | ⚠️ X 來信聲稱已處理，請人工確認 URL 是否下架後按「✓ 已下架」{datetime.now().strftime('%Y-%m-%d')} ticket={ticket_id or 'unknown'}")
            stats["unknown"] += 1

            mark_processed(msg_id)
            stats["processed"] += 1
            continue

        # ── X/Twitter 拒絕 ────────────────────────────────────────────────
        if kind == "x_denied":
            ticket_m  = re.search(r'(LEGAL-\d+)', subject)
            ticket_id = ticket_m.group(1) if ticket_m else None
            case = None
            if ticket_id:
                for row in tracker.list_all():
                    if dict(row).get("twitter_report_id") == ticket_id:
                        case = row
                        break
            if not case:
                case = find_case_by_email_body(sender, subject, body)

            if case and not dry_run:
                existing = case["notes"] or ""
                tracker.update(case["id"], case["status"],
                               existing + f" | X 拒絕處理 {datetime.now().strftime('%Y-%m-%d')} ticket={ticket_id or 'unknown'}")
            print(f"      ℹ️  X 拒絕，已記錄備註 (ticket={ticket_id})")
            mark_processed(msg_id)
            stats["denied"] += 1
            stats["processed"] += 1
            continue

        # ── CF 含主機商：補寄 host notice ─────────────────────────────────
        if kind == "cf_info":
            if dry_run:
                print("      [DRY RUN] cf_info，不寄信")
                mark_processed(msg_id)
                stats["cf_info"] += 1
                stats["processed"] += 1
                continue

            info = parse_cf_host_info(body)
            if not info["host_email"]:
                mark_processed(msg_id)
                continue

            case = find_case_by_email_body(sender, subject, body)
            infringing_url = case["url"] if case else f"https://{info['domain']}/"
            film_title     = case["film_title"] if case else "JAOfilm series"

            notice_text = generate_host(
                infringing_url, info["domain"], film_title,
                info["host_org"], info["host_email"]
            )
            today      = date.today().strftime("%Y-%m-%d")
            safe_d     = (info["domain"] or "unknown").replace(".", "_")
            safe_org   = re.sub(r"[^\w]", "_", (info["host_org"] or "host"))[:20].lower()
            notice_path = Path(__file__).parent / "notices" / f"{today}_{safe_d}_host_{safe_org}.txt"
            notice_path.write_text(notice_text, encoding="utf-8")

            notice_data = {
                "subject": notice_text.splitlines()[0].replace("Subject: ", ""),
                "to":      info["host_email"],
                "body":    "\n".join(notice_text.splitlines()[1:]).strip(),
                "path":    str(notice_path),
            }
            if mailer.send_email(notice_data):
                mailer.mark_sent(str(notice_path))
                print(f"      ✅  Host notice 寄出 → {info['host_email']}")
            else:
                print(f"      ❌  寄信失敗，notice 存在 {notice_path.name}")

            mark_processed(msg_id)
            stats["cf_info"] += 1
            stats["processed"] += 1
            continue

        # ── 移除確認：驗證 URL ────────────────────────────────────────────
        if kind == "removed":
            case = find_case_by_email_body(sender, subject, body)
            if not case:
                print("      ⚠️  找不到對應案件，跳過")
                mark_processed(msg_id)
                stats["unknown"] += 1
                continue

            url = case["url"]
            print(f"      案件 #{case['id']} {case['domain']}")
            print(f"      Ping URL: {url[:70]}")

            is_down = verify_url_down(url)
            if is_down:
                print(f"      ✅  URL 已下線（404/連線失敗），標記 removed")
                if not dry_run:
                    tracker.update(case["id"], "removed",
                                   f"自動確認移除（{datetime.now().strftime('%Y-%m-%d %H:%M')}）via {sender[:40]}")
                stats["removed"] += 1
            else:
                print(f"      ⚠️  URL 仍可存取，標記 needs_check")
                if not dry_run:
                    existing_notes = case["notes"] or ""
                    tracker.update(case["id"], case["status"],
                                   existing_notes + f" | 主機商稱已移除但 URL 仍存在 {datetime.now().strftime('%Y-%m-%d')}")
                stats["unknown"] += 1

            mark_processed(msg_id)
            stats["processed"] += 1
            continue

        # ── 拒絕處理 ──────────────────────────────────────────────────────
        if kind == "denied":
            case = find_case_by_email_body(sender, subject, body)
            if case and not dry_run:
                existing_notes = case["notes"] or ""
                tracker.update(case["id"], case["status"],
                               existing_notes + f" | 主機商拒絕處理 {datetime.now().strftime('%Y-%m-%d')} via {sender[:40]}")
            print(f"      ℹ️  主機商拒絕，已記錄備註")
            mark_processed(msg_id)
            stats["denied"] += 1
            stats["processed"] += 1
            continue

        # ── 未知：記錄待人工處理 ──────────────────────────────────────────
        case = find_case_by_email_body(sender, subject, body)
        if case and not dry_run:
            existing_notes = case["notes"] or ""
            tracker.update(case["id"], case["status"],
                           existing_notes + f" | 未分類回信 {datetime.now().strftime('%Y-%m-%d')} from {sender[:40]}")
        print(f"      ❓  未分類，已記錄備註")
        mark_processed(msg_id)
        stats["unknown"] += 1
        stats["processed"] += 1

    print(f"\n  完成：處理了 {stats['processed']} 封 "
          f"（removed={stats['removed']} cf={stats['cf_info']} "
          f"denied={stats['denied']} unknown={stats['unknown']}）")
    return stats

# ── 入口 ──────────────────────────────────────────────────────────────────────

def main():
    dry_run  = "--dry-run" in sys.argv
    watch    = "--watch"   in sys.argv
    interval = 600

    service = get_gmail_service()

    if watch:
        print(f"👁  監聽模式：每 {interval//60} 分鐘掃描一次（Ctrl+C 停止）")
        while True:
            scan_once(service, dry_run)
            time.sleep(interval)
    else:
        scan_once(service, dry_run)

if __name__ == "__main__":
    main()
