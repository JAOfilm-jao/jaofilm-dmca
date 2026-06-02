import socket
import ipaddress
import requests
import dns.resolver
from urllib.parse import urlparse
from config import PLATFORM_CONTACTS, DMCA_COUNTRIES

# Cloudflare 的 IP 段（官方公佈）
CF_RANGES = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
]

def _is_cf_ip(ip):
    try:
        ip_obj = ipaddress.ip_address(ip)
        return any(ip_obj in ipaddress.ip_network(r) for r in CF_RANGES)
    except Exception:
        return False

def _cf_by_ns(domain):
    try:
        answers = dns.resolver.resolve(domain, "NS", lifetime=5)
        return any("cloudflare" in str(r).lower() for r in answers)
    except Exception:
        return False

def _get_ip(domain):
    try:
        return socket.gethostbyname(domain)
    except Exception:
        return None

def _ipinfo(ip):
    try:
        r = requests.get(f"https://ipinfo.io/{ip}/json", timeout=6)
        return r.json()
    except Exception:
        return {}

def _whois_abuse(domain):
    """Simple abuse email extraction via WHOIS (python-whois)."""
    try:
        import whois
        w = whois.whois(domain)
        emails = w.emails or []
        if isinstance(emails, str):
            emails = [emails]
        return [e for e in emails if "abuse" in e.lower()]
    except Exception:
        return []

def detect_platform(domain):
    for key, info in PLATFORM_CONTACTS.items():
        if key in domain:
            return info
    return None

def investigate(url):
    parsed = urlparse(url)
    domain = parsed.netloc.lower().lstrip("www.")
    if not domain:
        domain = url.strip()

    result = {
        "url": url,
        "domain": domain,
        "ip": None,
        "is_cloudflare": False,
        "hosting_org": "Unknown",
        "hosting_country": "?",
        "registrar": None,
        "abuse_emails": [],
        "platform": detect_platform(domain),
        "actions": [],
    }

    ip = _get_ip(domain)
    result["ip"] = ip

    if ip:
        result["is_cloudflare"] = _is_cf_ip(ip) or _cf_by_ns(domain)
        info = _ipinfo(ip)
        result["hosting_org"] = info.get("org", "Unknown")
        result["hosting_country"] = info.get("country", "?")
        abuse_email = (info.get("abuse") or {}).get("email")
        if abuse_email:
            result["abuse_emails"].append(abuse_email)

    # WHOIS abuse fallback
    whois_abuse = _whois_abuse(domain)
    for e in whois_abuse:
        if e not in result["abuse_emails"]:
            result["abuse_emails"].append(e)

    # Build action list
    actions = []
    priority = 1

    # Google 永遠第一
    actions.append({
        "priority": priority,
        "target": "Google（搜尋結果下架）",
        "method": "form",
        "url": "https://support.google.com/legal/troubleshooter/1114905",
        "notice_key": None,
        "note": "最高優先。斷所有 Google 流量來源。",
    })
    priority += 1

    # 平台申訴
    if result["platform"]:
        p = result["platform"]
        actions.append({
            "priority": priority,
            "target": p["name"],
            "method": "email" if p.get("email") else "form",
            "email": p.get("email"),
            "url": p.get("form"),
            "notice_key": "platform",
        })
        priority += 1

    # Cloudflare
    if result["is_cloudflare"]:
        actions.append({
            "priority": priority,
            "target": "Cloudflare",
            "method": "email+form",
            "email": "abuse@cloudflare.com",
            "url": "https://abuse.cloudflare.com/",
            "notice_key": "cloudflare",
            "note": "即使主機在俄/中，CF 在美國，受 DMCA 管轄。",
        })
        priority += 1

    # 主機商（只打 DMCA 有效國家）
    if result["abuse_emails"] and result["hosting_country"] in DMCA_COUNTRIES:
        for email in result["abuse_emails"]:
            actions.append({
                "priority": priority,
                "target": f"主機商（{result['hosting_org']} / {result['hosting_country']}）",
                "method": "email",
                "email": email,
                "notice_key": "host",
                "note": f"美國/歐洲主機，DMCA 具法律效力。",
            })
            priority += 1
    elif result["abuse_emails"]:
        actions.append({
            "priority": None,
            "target": f"主機商（{result['hosting_org']} / {result['hosting_country']}）",
            "method": "skip",
            "note": f"主機在 {result['hosting_country']}，DMCA 無效，跳過。",
        })

    result["actions"] = actions
    return result
