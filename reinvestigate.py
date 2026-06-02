#!/usr/bin/env python3
"""
JAOfilm DMCA Re-investigator
對沒有找到 abuse email 的案件，用 RDAP API 重新查詢。

用法：
  python3 reinvestigate.py          # 重查所有 pending + 無 email 的案件
  python3 reinvestigate.py <domain> # 重查特定 domain
"""

import sys
import re
import json
import requests
import sqlite3
from pathlib import Path
from datetime import date

import tracker
from investigate import _ipinfo, _get_ip, _is_cf_ip, _cf_by_ns
from generate import generate_host, generate_cloudflare, generate_google_checklist
from config import DMCA_COUNTRIES

RDAP_URL = "https://rdap.org/domain/{}"

# ── RDAP 查詢（比 WHOIS 準）────────────────────────────────────────────────

def rdap_abuse_email(domain):
    """用 RDAP 查 abuse email"""
    try:
        r = requests.get(RDAP_URL.format(domain), timeout=8, headers={"Accept": "application/json"})
        if r.status_code != 200:
            return []
        data = r.json()
        emails = []

        def extract_emails(obj):
            if isinstance(obj, dict):
                # vCard email
                if "vcardArray" in obj:
                    for entry in obj["vcardArray"][1]:
                        if entry[0] == "email":
                            emails.append(entry[3])
                # roles
                if "roles" in obj and any(role in ["abuse", "technical", "administrative"]
                                           for role in obj.get("roles", [])):
                    if "vcardArray" in obj:
                        for entry in obj["vcardArray"][1]:
                            if entry[0] == "email":
                                emails.append(entry[3])
                for v in obj.values():
                    extract_emails(v)
            elif isinstance(obj, list):
                for item in obj:
                    extract_emails(item)

        extract_emails(data)
        # 偏好 abuse@... 開頭的 email
        abuse = [e for e in emails if "abuse" in e.lower()]
        return abuse or emails[:1]
    except Exception:
        return []

def arin_abuse_email(ip):
    """用 ARIN Whois API 查 abuse email（美國 IP 最準）"""
    try:
        r = requests.get(
            f"https://rdap.arin.net/registry/ip/{ip}",
            timeout=8, headers={"Accept": "application/json"}
        )
        if r.status_code != 200:
            return []
        data = r.json()
        emails = []

        def search(obj):
            if isinstance(obj, dict):
                if "vcardArray" in obj:
                    for entry in obj["vcardArray"][1]:
                        if entry[0] == "email":
                            emails.append(entry[3])
                for v in obj.values():
                    search(v)
            elif isinstance(obj, list):
                for i in obj:
                    search(i)

        search(data)
        return [e for e in emails if "abuse" in e.lower()] or emails[:1]
    except Exception:
        return []

# ── 重查邏輯 ──────────────────────────────────────────────────────────────────

def reinvestigate(domain, url, film_title, case_id):
    print(f"\n🔍  重查：{domain}")

    ip = _get_ip(domain)
    if not ip:
        print(f"    ❌  無法解析 IP")
        return False

    print(f"    IP：{ip}")
    info = _ipinfo(ip)
    org     = info.get("org", "Unknown")
    country = info.get("country", "?")
    print(f"    主機商：{org} ({country})")

    # RDAP
    emails = rdap_abuse_email(domain)
    if not emails and country in ("US", "CA"):
        emails = arin_abuse_email(ip)
    if not emails:
        # 最後嘗試：abuse@<registrar domain>
        abuse_fallback = (info.get("abuse") or {}).get("email")
        if abuse_fallback:
            emails = [abuse_fallback]

    if not emails:
        print(f"    ⚠️   仍找不到 abuse email")
        return False

    email = emails[0]
    print(f"    ✅  找到 abuse email：{email}")

    # 更新 tracker
    with sqlite3.connect(str(Path(__file__).parent / "tracker.db")) as conn:
        conn.execute(
            "UPDATE cases SET hosting_org=?, hosting_country=?, abuse_emails=? WHERE id=?",
            (org, country, email, case_id)
        )

    # 生成 notice
    today = date.today().strftime("%Y-%m-%d")
    safe  = domain.replace(".", "_")
    notices_dir = Path(__file__).parent / "notices"

    if country in DMCA_COUNTRIES:
        path = notices_dir / f"{today}_{safe}_host.txt"
        path.write_text(
            generate_host(url, domain, film_title, org, email),
            encoding="utf-8"
        )
        print(f"    📄  Host notice：{path.name}")

    # Cloudflare check
    is_cf = _is_cf_ip(ip) or _cf_by_ns(domain)
    if is_cf:
        path = notices_dir / f"{today}_{safe}_cloudflare.txt"
        path.write_text(
            generate_cloudflare(url, domain, film_title),
            encoding="utf-8"
        )
        print(f"    📄  CF notice：{path.name}")

    return True

def main():
    if len(sys.argv) > 1:
        domain = sys.argv[1]
        rows = [r for r in tracker.list_all() if r["domain"] == domain]
        if not rows:
            print(f"❌  找不到 domain：{domain}")
            sys.exit(1)
    else:
        # 找所有 pending 且沒有 abuse email 的案件
        rows = [r for r in tracker.list_all()
                if r["status"] == "pending" and not r["abuse_emails"]]

    if not rows:
        print("✅  沒有需要重查的案件")
        return

    print(f"📋  找到 {len(rows)} 個需要重查的案件")
    found = 0
    for r in rows:
        success = reinvestigate(
            r["domain"], r["url"], r["film_title"] or "JAOfilm series", r["id"]
        )
        if success:
            found += 1

    print(f"\n✅  完成：{found}/{len(rows)} 個找到 abuse email")
    if found > 0:
        print("    執行 'python3 mailer.py send' 寄出新生成的 notice")

if __name__ == "__main__":
    main()
