#!/usr/bin/env python3
"""
JAOfilm DMCA Mailer
自動讀取 notice 檔，預覽確認後透過 SMTP 寄出。

用法：
  python3 mailer.py                      # 列出所有待寄 notice
  python3 mailer.py send                 # 批次寄出（逐一確認）
  python3 mailer.py send <notice_file>   # 寄出單一 notice
  python3 mailer.py --dry-run            # 預覽，不實際寄出

SMTP 設定（擇一）：
  1. 在 .env 檔設定（推薦）
  2. 環境變數：JAO_SMTP_HOST / JAO_SMTP_USER / JAO_SMTP_PASS
"""

import os
import re
import sys
import glob
import smtplib
from datetime import date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import tracker
from config import CONTACT_EMAIL

# ── SMTP 設定 ──────────────────────────────────────────────────────────────────

def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

load_env()

SMTP_HOST = os.environ.get("JAO_SMTP_HOST", "smtp.mailgun.org")
SMTP_PORT = int(os.environ.get("JAO_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("JAO_SMTP_USER", "postmaster@mg.jaofilm.com")
SMTP_PASS = os.environ.get("JAO_SMTP_PASS", "")
FROM_ADDR = CONTACT_EMAIL   # info@jaofilm.com

# ── 哪些 notice 類型可以用 email 寄 ───────────────────────────────────────────

EMAIL_TYPES = ("_host", "_cloudflare", "_platform")
SKIP_TYPES  = ("_google",)          # 需要瀏覽器填表
SENT_LOG    = Path(__file__).parent / ".sent_notices.log"

def already_sent(path):
    if SENT_LOG.exists():
        return str(path) in SENT_LOG.read_text()
    return False

def mark_sent(path):
    with SENT_LOG.open("a") as f:
        f.write(str(path) + "\n")

# ── Tracker DB helpers ────────────────────────────────────────────────────────

def _domain_from_filename(path):
    """2026-05-30_2bgay_com_host.txt → 2bgay.com"""
    stem = Path(path).stem                          # 2026-05-30_2bgay_com_host
    parts = stem.split("_")[1:]                     # ['2bgay', 'com', 'host']
    domain_parts = []
    for p in parts:
        if p in ("host", "cloudflare", "google", "platform"):
            break
        domain_parts.append(p)
    return ".".join(domain_parts)

def _lookup_abuse_email(domain):
    """從 tracker DB 查 abuse email（舊 notice 未寫入 email 時用）"""
    try:
        rows = tracker.list_all()
        for r in rows:
            if r["domain"] and domain in r["domain"] and r["abuse_emails"]:
                return r["abuse_emails"].split(",")[0].strip()
    except Exception:
        pass
    return None

# ── 解析 notice 檔案 ──────────────────────────────────────────────────────────

def parse_notice(path):
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()

    # Subject
    subject = ""
    for line in lines:
        if line.startswith("Subject:"):
            subject = line[len("Subject:"):].strip()
            break

    # 收件人 email（找第一個非我們自己的 email）
    emails = re.findall(r"[\w.+-]+@[\w.-]+\.\w+", text)
    to_email = next(
        (e for e in emails if "jaofilm.com" not in e and "cloudflare.com" not in e.split("@")[1]),
        None
    )
    # Cloudflare notice 特殊處理
    if not to_email and "cloudflare" in str(path).lower():
        to_email = "abuse@cloudflare.com"
    # 舊版 host notice 沒有 email → 從 tracker DB 查
    if not to_email and "_host" in str(path):
        domain = _domain_from_filename(str(path))
        to_email = _lookup_abuse_email(domain)

    # Body：去掉 Subject 行，保留其餘
    body_lines = [l for l in lines if not l.startswith("Subject:")]
    body = "\n".join(body_lines).strip()

    return {
        "subject": subject,
        "to": to_email,
        "body": body,
        "path": str(path),
    }

# ── 掃描待寄清單 ───────────────────────────────────────────────────────────────

def get_pending_notices():
    notices_dir = Path(__file__).parent / "notices"
    pending = []
    for f in sorted(notices_dir.glob("*.txt")):
        name = f.stem
        if any(name.endswith(t) for t in SKIP_TYPES):
            continue
        if not any(name.endswith(t) for t in EMAIL_TYPES):
            continue
        if already_sent(f):
            continue
        parsed = parse_notice(f)
        if parsed["to"]:
            pending.append(parsed)
    return pending

# ── 顯示預覽 ──────────────────────────────────────────────────────────────────

def print_preview(notice, index=None, total=None):
    prefix = f"[{index}/{total}] " if index else ""
    print(f"\n{'='*60}")
    print(f"  {prefix}📄 {Path(notice['path']).name}")
    print(f"  寄至：{notice['to']}")
    print(f"  主旨：{notice['subject']}")
    print(f"  {'─'*50}")
    # 只顯示前 8 行 body
    preview_lines = notice["body"].splitlines()[:8]
    for l in preview_lines:
        print(f"  {l}")
    if len(notice["body"].splitlines()) > 8:
        print(f"  ...")
    print(f"{'='*60}")

# ── 寄信 ─────────────────────────────────────────────────────────────────────

def send_email(notice, dry_run=False):
    if not SMTP_PASS and not dry_run:
        print("❌  JAO_SMTP_PASS 未設定，請在 .env 檔加入 Mailgun 密碼")
        print("    echo 'JAO_SMTP_PASS=你的密碼' >> .env")
        return False

    msg = MIMEMultipart()
    msg["From"]    = f"JAO / JAOfilm <{FROM_ADDR}>"
    msg["To"]      = notice["to"]
    msg["Subject"] = notice["subject"]
    msg.attach(MIMEText(notice["body"], "plain", "utf-8"))

    if dry_run:
        print("  [DRY RUN] 不實際寄出")
        return True

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(FROM_ADDR, notice["to"], msg.as_string())
        print(f"  ✅ 已寄出 → {notice['to']}")
        mark_sent(notice["path"])
        return True
    except Exception as e:
        print(f"  ❌ 寄信失敗：{e}")
        return False

# ── 指令：列出待寄 ────────────────────────────────────────────────────────────

def cmd_list():
    pending = get_pending_notices()
    if not pending:
        print("\n✅  沒有待寄的 notice（全部已寄出或為 Google 表單類型）")
        return
    print(f"\n📬  待寄 notice（{len(pending)} 封）：\n")
    for i, n in enumerate(pending, 1):
        name = Path(n["path"]).name
        print(f"  {i:>2}. {name}")
        print(f"      寄至：{n['to']}")
        print(f"      主旨：{n['subject'][:60]}")
        print()
    print("執行 'python3 mailer.py send' 開始批次寄出")
    print("執行 'python3 mailer.py --dry-run' 預覽全部不寄出")

# ── 指令：批次寄出 ────────────────────────────────────────────────────────────

def cmd_send_all(dry_run=False):
    pending = get_pending_notices()
    if not pending:
        print("\n✅  沒有待寄的 notice")
        return

    total = len(pending)
    sent  = 0

    for i, notice in enumerate(pending, 1):
        print_preview(notice, index=i, total=total)
        if dry_run:
            send_email(notice, dry_run=True)
            sent += 1
            continue

        ans = input(f"\n  寄出這封？[Y/n/q] ").strip().lower()
        if ans == "q":
            print("  中止。")
            break
        if ans in ("", "y"):
            if send_email(notice):
                sent += 1
        else:
            print("  跳過。")

    print(f"\n{'='*60}")
    print(f"  完成：{sent}/{total} 封{'（DRY RUN）' if dry_run else '已寄出'}")
    if not dry_run and sent > 0:
        print(f"  記得更新 tracker：python3 main.py update <id> submitted")

# ── 指令：寄單一檔案 ──────────────────────────────────────────────────────────

def cmd_send_one(path, dry_run=False):
    if not os.path.exists(path):
        print(f"❌  找不到檔案：{path}")
        sys.exit(1)
    notice = parse_notice(path)
    if not notice["to"]:
        print(f"❌  找不到收件人 email，請確認 notice 內容")
        sys.exit(1)
    print_preview(notice)
    if not dry_run:
        ans = input("\n  寄出這封？[Y/n] ").strip().lower()
        if ans not in ("", "y"):
            print("  取消。")
            return
    send_email(notice, dry_run)

# ── 入口 ─────────────────────────────────────────────────────────────────────

def cmd_auto_send():
    """全自動寄出，不需要確認（供 app.py 呼叫）"""
    pending = get_pending_notices()
    sent = 0
    for notice in pending:
        if send_email(notice):
            sent += 1
    if sent:
        print(f"[auto] 已寄出 {sent} 封")

def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a not in ("--dry-run",)]

    if "--auto-send" in sys.argv:
        cmd_auto_send()
        return

    if not args and not dry_run:
        cmd_list()
    elif not args and dry_run:
        cmd_send_all(dry_run=True)
    elif args[0] == "send":
        if len(args) > 1:
            cmd_send_one(args[1], dry_run)
        else:
            cmd_send_all(dry_run)
    else:
        # 直接傳 notice 路徑
        if os.path.exists(args[0]):
            cmd_send_one(args[0], dry_run)
        else:
            print(__doc__)

if __name__ == "__main__":
    main()
