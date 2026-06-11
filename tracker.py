import json as _json
import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

DB = str(Path(__file__).parent / "tracker.db")

# UTM 及追蹤參數白名單（這些不影響頁面內容，比對時忽略）
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referrer", "fbclid", "gclid", "mc_cid", "mc_eid",
}

def normalize_url(url: str) -> str:
    """移除 UTM / 追蹤參數，回傳正規化 URL 供重複比對用"""
    try:
        p = urlparse(url)
        qs = {k: v for k, v in parse_qs(p.query, keep_blank_values=True).items()
              if k.lower() not in _TRACKING_PARAMS}
        clean = p._replace(query=urlencode(qs, doseq=True))
        return urlunparse(clean).rstrip("/")
    except Exception:
        return url.rstrip("/")

def _conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                url             TEXT NOT NULL,
                domain          TEXT,
                film_title      TEXT,
                ip              TEXT,
                hosting_org     TEXT,
                hosting_country TEXT,
                is_cloudflare   INTEGER DEFAULT 0,
                platform        TEXT,
                abuse_emails    TEXT,
                status          TEXT DEFAULT 'pending',
                date_found      TEXT,
                date_submitted  TEXT,
                date_removed    TEXT,
                notes           TEXT,
                google_report_id TEXT
            )
        """)
        # migrations
        cols = [r[1] for r in conn.execute("PRAGMA table_info(cases)").fetchall()]
        if "google_report_id" not in cols:
            conn.execute("ALTER TABLE cases ADD COLUMN google_report_id TEXT")
        if "pending_action" not in cols:
            conn.execute("ALTER TABLE cases ADD COLUMN pending_action TEXT")
        if "extra_urls" not in cols:
            conn.execute("ALTER TABLE cases ADD COLUMN extra_urls TEXT")
        if "twitter_report_id" not in cols:
            conn.execute("ALTER TABLE cases ADD COLUMN twitter_report_id TEXT")
        if "batch_id" not in cols:
            conn.execute("ALTER TABLE cases ADD COLUMN batch_id TEXT")
        if "film_url" not in cols:
            conn.execute("ALTER TABLE cases ADD COLUMN film_url TEXT")

def add(url, film_title, inv, extra_urls=None, batch_id=None, film_url=None):
    init()
    extra_json = _json.dumps(extra_urls) if extra_urls else None
    with _conn() as conn:
        cur = conn.execute("""
            INSERT INTO cases
              (url, domain, film_title, ip, hosting_org, hosting_country,
               is_cloudflare, platform, abuse_emails, status, date_found, extra_urls, batch_id, film_url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            url,
            inv.get("domain"),
            film_title,
            inv.get("ip"),
            inv.get("hosting_org"),
            inv.get("hosting_country"),
            1 if inv.get("is_cloudflare") else 0,
            inv.get("platform", {}).get("name") if inv.get("platform") else None,
            ", ".join(inv.get("abuse_emails", [])),
            "pending",
            date.today().isoformat(),
            extra_json,
            batch_id,
            film_url or None,
        ))
        return cur.lastrowid

def set_extra_urls(case_id, urls):
    """存額外侵權 URL 清單（不含主 URL）"""
    init()
    with _conn() as conn:
        conn.execute("UPDATE cases SET extra_urls=? WHERE id=?",
                     (_json.dumps(urls), case_id))

def get_all_urls(row) -> list:
    """回傳該案件全部 URL（主 URL + extra_urls）"""
    urls = [row["url"]]
    if row["extra_urls"]:
        try:
            extras = _json.loads(row["extra_urls"])
            urls += [u for u in extras if u != row["url"]]
        except Exception:
            pass
    return urls

def update(case_id, status, notes=None):
    init()
    today = date.today().isoformat()
    with _conn() as conn:
        if status == "submitted":
            conn.execute("UPDATE cases SET status=?, date_submitted=? WHERE id=?", (status, today, case_id))
        elif status == "removed":
            conn.execute("UPDATE cases SET status=?, date_removed=? WHERE id=?", (status, today, case_id))
        else:
            conn.execute("UPDATE cases SET status=? WHERE id=?", (status, case_id))
        if notes:
            conn.execute("UPDATE cases SET notes=? WHERE id=?", (notes, case_id))

def set_pending_action(case_id, action_dict):
    """存待確認動作（JSON），action_dict = {type, to, subject, body}"""
    init()
    import json as _json
    with _conn() as conn:
        conn.execute("UPDATE cases SET pending_action=? WHERE id=?",
                     (_json.dumps(action_dict, ensure_ascii=False), case_id))

def clear_pending_action(case_id):
    init()
    with _conn() as conn:
        conn.execute("UPDATE cases SET pending_action=NULL WHERE id=?", (case_id,))

def set_google_report_id(case_id, report_id):
    init()
    with _conn() as conn:
        conn.execute(
            "UPDATE cases SET google_report_id=? WHERE id=?",
            (report_id, case_id)
        )

def set_twitter_report_id(case_id, report_id):
    init()
    with _conn() as conn:
        conn.execute(
            "UPDATE cases SET twitter_report_id=? WHERE id=?",
            (report_id, case_id)
        )

def get_twitter_submitted_urls():
    """回傳所有已送 Twitter/X DMCA 的 URL → {url: (case_id, report_id)}"""
    init()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, url, twitter_report_id FROM cases "
            "WHERE twitter_report_id IS NOT NULL AND twitter_report_id != ''"
        ).fetchall()
    result = {}
    for r in rows:
        result[r["url"]] = (r["id"], r["twitter_report_id"])
        norm = normalize_url(r["url"])
        if norm != r["url"]:
            result[norm] = (r["id"], r["twitter_report_id"])
    return result

def get_google_submitted_urls():
    """
    回傳所有已送 Google DMCA 的 URL → {url: (case_id, report_id)}
    同時收錄原始 URL 和正規化 URL（去除 UTM 參數），確保 UTM 不同的同一頁面也能被偵測。
    """
    init()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, url, google_report_id FROM cases "
            "WHERE google_report_id IS NOT NULL AND google_report_id != ''"
        ).fetchall()
    result = {}
    for r in rows:
        result[r["url"]] = (r["id"], r["google_report_id"])
        norm = normalize_url(r["url"])
        if norm != r["url"]:
            result[norm] = (r["id"], r["google_report_id"])
    return result

def list_all(status=None):
    init()
    with _conn() as conn:
        if status:
            return conn.execute("SELECT * FROM cases WHERE status=? ORDER BY id DESC", (status,)).fetchall()
        return conn.execute("SELECT * FROM cases ORDER BY id DESC").fetchall()

STATUS_EMOJI = {
    "pending":   "⏳",
    "submitted": "📤",
    "removed":   "✅",
    "ignored":   "🚫",
}

def print_cases(rows):
    if not rows:
        print("  （無案件）")
        return
    print(f"  {'ID':>4}  {'狀態':6}  {'發現日期':10}  {'片名':20}  URL")
    print("  " + "-" * 80)
    for r in rows:
        emoji = STATUS_EMOJI.get(r["status"], "?")
        film = (r["film_title"] or "")[:18]
        url  = (r["url"] or "")[:50]
        print(f"  {r['id']:>4}  {emoji} {r['status']:<6}  {r['date_found']:10}  {film:<20}  {url}")
