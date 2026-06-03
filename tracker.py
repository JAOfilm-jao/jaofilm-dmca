import sqlite3
from datetime import date
from pathlib import Path

DB = str(Path(__file__).parent / "tracker.db")

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

def add(url, film_title, inv):
    init()
    with _conn() as conn:
        cur = conn.execute("""
            INSERT INTO cases
              (url, domain, film_title, ip, hosting_org, hosting_country,
               is_cloudflare, platform, abuse_emails, status, date_found)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
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
        ))
        return cur.lastrowid

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
