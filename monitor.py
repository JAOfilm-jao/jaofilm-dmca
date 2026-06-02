#!/usr/bin/env python3
"""
JAOfilm DMCA Monitor — Gmail API 回信監控
自動偵測 Cloudflare 回信 → 解析主機商 → 生成 host notice → 寄出

用法：
  python3 monitor.py          # 手動跑一次，掃描未處理的 CF 回信
  python3 monitor.py --watch  # 持續監聽（每 10 分鐘掃一次）
"""

import os
import re
import sys
import json
import time
import base64
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

# Google API
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

import tracker
import mailer
from generate import generate_host
from config import COPYRIGHT_OWNER, BRAND_NAME, CONTACT_EMAIL, WEBSITE

# ── 設定 ──────────────────────────────────────────────────────────────────────

SCOPES          = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_PATH      = Path(__file__).parent / ".gmail_token.json"
CREDENTIALS_PATH = Path(__file__).parent / ".gmail_credentials.json"
PROCESSED_LOG   = Path(__file__).parent / ".processed_cf_emails.log"

CF_SENDER       = "abuse@notify.cloudflare.com"
CF_SUBJECT_KEYWORD = "Response to your DMCA"

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
                print("    步驟：Google Cloud Console → APIs → Gmail API → OAuth 2.0 Credentials")
                print("    下載 credentials.json 存為 .gmail_credentials.json")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)

# ── 解析 Cloudflare 回信 ──────────────────────────────────────────────────────

def parse_cf_response(body: str) -> dict:
    """
    從 CF 回信解析：
    - 侵權 domain
    - 主機商名稱
    - abuse email
    - CF Report ID
    """
    result = {
        "domain":      None,
        "host_org":    None,
        "host_email":  None,
        "report_id":   None,
    }

    # Report ID
    m = re.search(r"Report ID[:\s]+([a-f0-9]{16})", body, re.I)
    if m:
        result["report_id"] = m.group(1)

    # Domain from body: "regarding: example.com" or "regarding: www.example.com"
    m = re.search(r"regarding[:\s]+(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", body, re.I)
    if m:
        result["domain"] = m.group(1).lower().rstrip(".")
    # Fallback: subject line
    if not result["domain"]:
        m = re.search(r"regarding[:\s]+(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z]{2,})", body, re.I)
        if m:
            result["domain"] = m.group(1).lower()

    # Host org and email
    # Pattern: "The host for the reported domain is:\nORG_NAME, CC\nemail@host.com"
    m = re.search(
        r"host for the reported domain is[:\s]*\n([^\n]+)\n([\w.+-]+@[\w.-]+\.\w+)",
        body, re.I | re.M
    )
    if m:
        result["host_org"]   = m.group(1).strip()
        result["host_email"] = m.group(2).strip()

    return result

# ── 已處理記錄 ────────────────────────────────────────────────────────────────

def is_processed(msg_id: str) -> bool:
    if PROCESSED_LOG.exists():
        return msg_id in PROCESSED_LOG.read_text()
    return False

def mark_processed(msg_id: str):
    with PROCESSED_LOG.open("a") as f:
        f.write(msg_id + "\n")

# ── 主掃描邏輯 ────────────────────────────────────────────────────────────────

def scan_once(service, dry_run=False):
    print(f"\n🔍  掃描 Cloudflare 回信... ({datetime.now().strftime('%H:%M:%S')})")

    # 搜尋最近 30 天的 CF 回信（含主機商資訊的那封）
    query = f'from:{CF_SENDER} subject:"Response to your DMCA" newer_than:30d'
    result = service.users().messages().list(userId="me", q=query, maxResults=20).execute()
    messages = result.get("messages", [])

    if not messages:
        print("  ✅  沒有新的 CF 回信")
        return 0

    processed = 0
    for msg_ref in messages:
        msg_id = msg_ref["id"]
        if is_processed(msg_id):
            continue

        # 取得完整信件
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()

        # 解碼 body
        body = ""
        payload = msg.get("payload", {})
        if payload.get("body", {}).get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
        else:
            for part in payload.get("parts", []):
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        body += base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

        info = parse_cf_response(body)

        if not info["host_email"]:
            mark_processed(msg_id)
            continue  # 這封沒有主機商資訊（只是確認信）

        print(f"\n  📨  CF 回信：domain={info['domain']} report_id={info['report_id']}")
        print(f"      主機商：{info['host_org']}")
        print(f"      Email ：{info['host_email']}")

        if dry_run:
            print("      [DRY RUN] 不寄信")
            mark_processed(msg_id)
            processed += 1
            continue

        # 找對應的案件，抓侵權 URL
        infringing_url = _find_url_for_domain(info["domain"], body)
        film_title = _find_film_for_domain(info["domain"])

        # 生成 host notice
        notice_text = generate_host(
            infringing_url or f"https://{info['domain']}/",
            info["domain"],
            film_title or "JAOfilm series",
            info["host_org"],
            info["host_email"],
        )

        # 存成 notice 檔
        today = date.today().strftime("%Y-%m-%d")
        safe_domain = info["domain"].replace(".", "_")
        safe_org    = re.sub(r"[^\w]", "_", (info["host_org"] or "host"))[:20].lower()
        notice_path = Path(__file__).parent / "notices" / f"{today}_{safe_domain}_host_{safe_org}.txt"
        notice_path.write_text(notice_text, encoding="utf-8")

        # 寄信
        notice_data = {
            "subject": notice_text.splitlines()[0].replace("Subject: ", ""),
            "to":      info["host_email"],
            "body":    "\n".join(notice_text.splitlines()[1:]).strip(),
            "path":    str(notice_path),
        }
        success = mailer.send_email(notice_data)
        if success:
            mailer.mark_sent(str(notice_path))
            print(f"      ✅  Host notice 已寄出 → {info['host_email']}")
        else:
            print(f"      ❌  寄信失敗，notice 存在 {notice_path.name}")

        mark_processed(msg_id)
        processed += 1

    print(f"\n  完成：處理了 {processed} 封新 CF 回信")
    return processed

def _find_url_for_domain(domain: str, body: str) -> str:
    """從 CF 回信 body 抓侵權 URL"""
    urls = re.findall(rf"hxxps?://[^\s]*{re.escape(domain)}[^\s]*", body, re.I)
    if urls:
        return urls[0].replace("hxxps://", "https://").replace("hxxp://", "http://")
    # Fallback：從 tracker DB 查
    try:
        rows = tracker.list_all()
        for r in rows:
            if r["domain"] and domain in r["domain"]:
                return r["url"]
    except Exception:
        pass
    return f"https://{domain}/"

def _find_film_for_domain(domain: str) -> str:
    """從 tracker DB 查片名"""
    try:
        rows = tracker.list_all()
        for r in rows:
            if r["domain"] and domain in r["domain"]:
                return r["film_title"]
    except Exception:
        pass
    return "JAOfilm series"

# ── 入口 ──────────────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    watch   = "--watch"   in sys.argv
    interval = 600  # 10 分鐘

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
