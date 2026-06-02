#!/usr/bin/env python3
"""
JAOfilm DMCA Tool
Usage:
  python main.py file <url> --film "Film Title"   # 新增案件
  python main.py list [--status pending|submitted|removed]
  python main.py update <id> <status>             # submitted / removed / ignored
"""
import sys
import os
import argparse
from datetime import date
from urllib.parse import urlparse

from investigate import investigate
from generate import (
    generate_host, generate_cloudflare, generate_platform, generate_google_checklist
)
import tracker
from config import LEGITIMATE_SOURCES

# ─── helpers ──────────────────────────────────────────────────────────────────

def safe_domain(domain):
    return domain.replace(".", "_").replace("/", "_")

def is_legitimate(url):
    domain = urlparse(url).netloc.lower().lstrip("www.")
    return any(s in domain for s in LEGITIMATE_SOURCES)

# ─── commands ─────────────────────────────────────────────────────────────────

def cmd_file(url, film_title):
    if is_legitimate(url):
        print(f"⚠️  這是合法來源，跳過。")
        return

    print(f"\n🔍  調查中：{url}")
    print("═" * 64)

    inv = investigate(url)

    print(f"\n📋  調查結果")
    print(f"    Domain      : {inv['domain']}")
    print(f"    IP          : {inv['ip'] or 'N/A'}")
    print(f"    主機商      : {inv['hosting_org']} ({inv['hosting_country']})")
    print(f"    Cloudflare  : {'✅ 是' if inv['is_cloudflare'] else '❌ 否'}")
    if inv['platform']:
        print(f"    平台        : {inv['platform']['name']}")
    if inv['abuse_emails']:
        print(f"    Abuse email : {', '.join(inv['abuse_emails'])}")

    # Generate notices
    os.makedirs("notices", exist_ok=True)
    today_str = date.today().strftime("%Y-%m-%d")
    base = f"notices/{today_str}_{safe_domain(inv['domain'])}"
    generated = {}

    # Google checklist（永遠生成）
    path = f"{base}_google.txt"
    with open(path, "w") as f:
        f.write(generate_google_checklist(url, film_title))
    generated["google"] = path

    if inv["platform"]:
        p = inv["platform"]
        path = f"{base}_platform.txt"
        with open(path, "w") as f:
            f.write(generate_platform(url, inv["domain"], film_title, p["name"]))
        generated["platform"] = path

    if inv["is_cloudflare"]:
        path = f"{base}_cloudflare.txt"
        with open(path, "w") as f:
            f.write(generate_cloudflare(url, inv["domain"], film_title))
        generated["cloudflare"] = path

    if inv["abuse_emails"]:
        path = f"{base}_host.txt"
        with open(path, "w") as f:
            f.write(generate_host(url, inv["domain"], film_title, inv["hosting_org"], inv["abuse_emails"][0]))
        generated["host"] = path

    # Print action plan
    print(f"\n🎯  行動清單")
    for action in inv["actions"]:
        if action.get("method") == "skip":
            print(f"\n    ⊘  [跳過] {action['target']}")
            print(f"       {action.get('note', '')}")
            continue

        p = action.get("priority", "?")
        print(f"\n    {p}.  {action['target']}")
        if action.get("note"):
            print(f"        ℹ️   {action['note']}")

        key = action.get("notice_key")
        if key and key in generated:
            print(f"        📄  Notice: {generated[key]}")

        if action.get("email"):
            print(f"        ✉️   寄至: {action['email']}")
        if action.get("url"):
            print(f"        🔗  表單: {action['url']}")

    print(f"\n    ⭐  永遠要做：Google DMCA")
    print(f"        🔗  https://support.google.com/legal/troubleshooter/1114905")
    print(f"        📄  填表指南：{generated['google']}")

    # Save to DB
    case_id = tracker.add(url, film_title, inv)
    print(f"\n✅  案件已建立 (ID: {case_id})")
    print(f"    提交後執行：python main.py update {case_id} submitted")
    print(f"    確認下架後：python main.py update {case_id} removed\n")


def cmd_list(status):
    rows = tracker.list_all(status)
    label = f"[{status}]" if status else "[全部]"
    print(f"\n📁  案件清單 {label}")
    print()
    tracker.print_cases(rows)
    print()


def cmd_update(case_id, status, notes=None):
    tracker.update(case_id, status, notes)
    print(f"✅  案件 #{case_id} 狀態更新為：{status}")


# ─── entry ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="dmca",
        description="JAOfilm DMCA Takedown Tool",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_file = sub.add_parser("file", help="對一個 URL 發起 DMCA")
    p_file.add_argument("url", help="侵權頁面或影片 URL")
    p_file.add_argument("--film", required=True, metavar="TITLE", help="被侵權的影片名稱")

    p_list = sub.add_parser("list", help="列出所有案件")
    p_list.add_argument("--status", choices=["pending", "submitted", "removed", "ignored"])

    p_up = sub.add_parser("update", help="更新案件狀態")
    p_up.add_argument("id", type=int)
    p_up.add_argument("status", choices=["submitted", "removed", "ignored"])
    p_up.add_argument("--notes", default=None)

    args = parser.parse_args()

    if args.cmd == "file":
        cmd_file(args.url, args.film)
    elif args.cmd == "list":
        cmd_list(args.status)
    elif args.cmd == "update":
        cmd_update(args.id, args.status, args.notes)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
