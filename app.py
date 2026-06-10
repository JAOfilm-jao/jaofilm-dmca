#!/usr/bin/env python3
"""
JAOfilm DMCA Web App
執行：python3 app.py
開啟：http://localhost:5002
"""

import os
import re
import sys
import json
import uuid
import subprocess
from datetime import date, datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler

sys.path.insert(0, str(Path(__file__).parent))
import tracker
from investigate import investigate
from generate import generate_host, generate_cloudflare, generate_google_checklist
from config import LEGITIMATE_SOURCES

app = Flask(__name__)
scheduler = BackgroundScheduler()

# ── 輔助：判斷案件的「下一步行動」 ─────────────────────────────────────────

def _find_google_notice(case):
    """
    找對應的 Google notice 檔。優先順序：
    1. case-ID 專屬命名：*_c{id}_google.txt（新格式，最精確）
    2. URL 內容比對：檔案內含案件 URL（防同 domain 多案件互相干擾）
    3. domain 命名 fallback：*_{domain}_google.txt（舊格式相容）
    """
    notice_dir  = Path(__file__).parent / "notices"
    domain_safe = (case.get("domain") or "").replace(".", "_")
    case_id     = case.get("id")
    case_url    = case.get("url") or ""

    # 1. case-ID 專屬命名（新格式）
    if case_id:
        hits = list(notice_dir.glob(f"*_c{case_id}_google.txt"))
        if hits:
            return hits[0]

    # 2. URL 內容比對（最可靠的舊格式相容方式）
    if case_url:
        norm_url = case_url.split("?")[0].rstrip("/")  # 忽略 query string 比對
        for f in sorted(notice_dir.glob("*google.txt"), reverse=True):  # 最新的優先
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                if case_url in text or norm_url in text:
                    return f
            except Exception:
                pass

    # 3. domain fallback（舊案件相容）
    hits = list(notice_dir.glob(f"*_{domain_safe}_google.txt"))
    if hits:
        return sorted(hits)[-1]  # 最新的

    hits = [f for f in notice_dir.glob("*google.txt") if domain_safe in f.name]
    if hits:
        return sorted(hits)[-1]

    return None


def next_action(case):
    import json as _json
    status = case["status"]
    notes  = case["notes"] or ""

    # 待確認送出的草稿（X reply 等）
    if case.get("pending_action"):
        try:
            action = _json.loads(case["pending_action"])
            label  = {"x_reply": "X DMCA 補件 — 待你確認送出"}.get(action.get("type"), "待確認動作")
            return {"type": "human", "label": label, "color": "red", "pending": action}
        except Exception:
            pass

    if status == "pending":
        return {"type": "auto", "label": "待調查 + 寄信", "color": "yellow"}

    if status == "submitted":
        days = (date.today() - date.fromisoformat(case["date_submitted"] or date.today().isoformat())).days

        # Twitter/X 平台：優先檢查線上表單是否送出
        is_twitter = (case.get("platform") or "").lower() in ("twitter/x", "twitter", "x")
        if is_twitter and not case.get("twitter_report_id"):
            return {"type": "human", "label": "Twitter/X DMCA 表單待送出", "color": "red"}

        # 已有 google_report_id 欄位，或 notes 裡含任意格式的 Google 檢舉 ID
        google_submitted = (
            bool(case.get("google_report_id"))
            or bool(re.search(r'\b\d+-\d{7,}\b', notes))
            or "google dmca submitted" in notes.lower()
        )
        if not google_submitted:
            google_notice = _find_google_notice(case)
            if google_notice:
                return {"type": "human", "label": "Google DMCA 表單待送出", "color": "red",
                        "notice": str(google_notice)}
        # Razorblade 補件模式
        if "補件" in notes or "razorblade" in notes.lower() or "missing" in notes.lower():
            return {"type": "human", "label": "主機商要求補件", "color": "red"}
        if days < 14:
            return {"type": "auto", "label": f"等待回應（第 {days} 天）", "color": "yellow"}
        return {"type": "human", "label": f"超過 {days} 天無回應，考慮追蹤", "color": "orange"}

    if status == "removed":
        return {"type": "done", "label": "已下架 ✅", "color": "green"}

    if status == "ignored":
        return {"type": "done", "label": "已忽略", "color": "grey"}

    return {"type": "auto", "label": status, "color": "grey"}


def enrich_cases(rows):
    flat = []
    for r in rows:
        c = dict(r)
        c["action"] = next_action(c)
        c["is_batch"] = False
        c["days_since"] = ""
        if c["date_found"]:
            days = (date.today() - date.fromisoformat(c["date_found"])).days
            c["days_since"] = f"{days}天前"
        flat.append(c)

    # 依 batch_id 群組；無 batch_id 的維持單筆
    singles = [c for c in flat if not c.get("batch_id")]
    batched: dict = {}
    for c in flat:
        if c.get("batch_id"):
            batched.setdefault(c["batch_id"], []).append(c)

    # 建立 batch group 物件
    _priority = {"red": 0, "yellow": 1, "orange": 2, "green": 3, "grey": 4}
    batch_groups = []
    for bid, members in batched.items():
        primary = min(members, key=lambda c: _priority.get(c["action"]["color"], 5))
        group = {
            "is_batch":        True,
            "batch_id":        bid,
            "domain":          members[0]["domain"],
            "film_title":      members[0]["film_title"],
            "days_since":      members[0]["days_since"],
            "action":          primary["action"],
            "batch_cases":     members,
            # 以最急迫的 case 作為按鈕觸發 ID
            "id":              primary["id"],
            "twitter_report_id": primary.get("twitter_report_id"),
            "google_report_id":  primary.get("google_report_id"),
            "pending_action":    primary.get("pending_action"),
            "url":             primary["url"],
        }
        batch_groups.append(group)

    return singles + batch_groups

# ── 路由 ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    rows  = tracker.list_all()
    cases = enrich_cases(rows)

    need_human = [c for c in cases if c["action"]["type"] == "human"]
    in_progress = [c for c in cases if c["action"]["type"] in ("auto", "yellow")]
    done = [c for c in cases if c["action"]["type"] == "done"]

    return render_template("index.html",
        need_human=need_human,
        in_progress=in_progress,
        done=done,
        total=len(cases),
    )


@app.route("/add", methods=["POST"])
def add_case():
    url        = request.form.get("url", "").strip()
    film_title = request.form.get("film_title", "JAOfilm series").strip()

    if not url:
        return jsonify({"error": "URL 不能為空"}), 400

    # 重複 URL 檢查（含 UTM 正規化：同一頁面不同追蹤參數視為重複）
    norm_url = tracker.normalize_url(url)
    existing = next(
        (r for r in tracker.list_all()
         if r["url"] == url or tracker.normalize_url(r["url"]) == norm_url),
        None
    )
    if existing:
        return jsonify({
            "error": f"⚠️ 此 URL 已存在（案件 #{existing['id']}，狀態：{existing['status']}）",
            "duplicate": True, "case_id": existing["id"]
        }), 409

    # 檢查是否合法來源
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lower().lstrip("www.")
    if any(s in domain for s in LEGITIMATE_SOURCES):
        return jsonify({"error": "這是合法來源，不需要申訴"}), 400

    # 背景調查（避免 request timeout）
    def do_investigate():
        try:
            inv = investigate(url)
            case_id = tracker.add(url, film_title, inv)

            today = date.today().strftime("%Y-%m-%d")
            safe  = inv["domain"].replace(".", "_").replace("/", "_")
            notices_dir = Path(__file__).parent / "notices"
            os.makedirs(notices_dir, exist_ok=True)

            is_platform = bool(inv.get("platform"))

            if is_platform:
                # 已知平台（Twitter/PH/XV 等）：只走平台 email，跳過 host/CF
                p = inv["platform"]
                if p.get("email"):
                    from generate import generate_platform
                    path = notices_dir / f"{today}_{safe}_platform.txt"
                    path.write_text(generate_platform(
                        url, inv["domain"], film_title, p["name"]))
            else:
                # 一般盜版網站：走 host + CF
                if inv["abuse_emails"]:
                    path = notices_dir / f"{today}_{safe}_host.txt"
                    path.write_text(generate_host(url, inv["domain"], film_title,
                        inv["hosting_org"], inv["abuse_emails"][0]))

                if inv["is_cloudflare"]:
                    path = notices_dir / f"{today}_{safe}_cloudflare.txt"
                    path.write_text(generate_cloudflare(url, inv["domain"], film_title))

            # Google DMCA：用 case_id 命名，避免同 domain 多案件互相覆蓋
            path = notices_dir / f"{today}_{safe}_c{case_id}_google.txt"
            path.write_text(generate_google_checklist(url, film_title))

            # 自動寄出 email notices
            subprocess.run(
                [sys.executable, "mailer.py", "--auto-send"],
                capture_output=True, text=True,
                cwd=str(Path(__file__).parent)
            )

            # 更新案件狀態為 submitted
            tracker.update(case_id, "submitted",
                           f"自動寄出 {'平台 email' if is_platform else 'host/CF email'} ({date.today().isoformat()})")

            _notify("JAOfilm DMCA", f"新案件已調查完成：{inv['domain']}")
        except Exception as e:
            print(f"[investigate error] {e}")

    import threading
    threading.Thread(target=do_investigate, daemon=True).start()

    return jsonify({"ok": True, "message": f"正在調查 {url}，稍後重新整理查看結果"})


@app.route("/update/<int:case_id>", methods=["POST"])
def update_case(case_id):
    status = request.form.get("status")
    notes  = request.form.get("notes", "")
    if status:
        tracker.update(case_id, status, notes or None)
    return redirect(url_for("index"))


@app.route("/run-monitor", methods=["POST"])
def run_monitor():
    """手動觸發 monitor.py"""
    result = subprocess.run(
        [sys.executable, "monitor.py"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).parent)
    )
    return jsonify({"output": result.stdout[-2000:] if result.stdout else "（無輸出）"})


@app.route("/fill-google/<int:case_id>", methods=["POST"])
def fill_google(case_id):
    """觸發 google_dmca.py 填表"""
    rows = tracker.list_all()
    case = next((r for r in rows if r["id"] == case_id), None)
    if not case:
        return jsonify({"error": "案件不存在"}), 404

    notice = _find_google_notice(dict(case))
    if not notice:
        return jsonify({"error": "找不到 Google notice 檔案"}), 404

    # ── 重複 Google 送出防呆 ──────────────────────────────────────────────────
    try:
        from google_dmca import parse_notice as _parse_notice
        notice_data = _parse_notice(str(notice))
        notice_urls = notice_data.get("infringing_urls") or [notice_data.get("infringing_url")]
        submitted   = tracker.get_google_submitted_urls()
        conflicts   = [
            f"case #{submitted[u][0]} report {submitted[u][1]}: {u}"
            for u in notice_urls if u in submitted
        ]
        if conflicts:
            # 回傳結構化資料供前端自動同步 report ID
            structured = [
                {"url": u, "existing_case_id": submitted[u][0], "report_id": submitted[u][1]}
                for u in notice_urls if u in submitted
            ]
            return jsonify({
                "error": "duplicate_google",
                "conflicts": structured,
            }), 409
    except Exception as e:
        print(f"[fill-google] pre-check 例外（跳過）: {e}")

    subprocess.Popen(
        ["/opt/homebrew/bin/python3.11", "google_dmca.py", str(notice), str(case_id)],
        cwd=str(Path(__file__).parent)
    )
    return jsonify({"ok": True, "message": "已啟動 Google DMCA 填表，請查看 Chrome"})


@app.route("/fill-twitter/<int:case_id>", methods=["POST"])
def fill_twitter(case_id):
    """觸發 twitter_dmca.py 填表（自動合併所有待送 Twitter cases）"""
    rows = tracker.list_all()

    # 找觸發的 case
    _row = next((r for r in rows if r["id"] == case_id), None)
    if not _row:
        return jsonify({"error": "案件不存在"}), 404
    trigger = dict(_row)

    if trigger.get("twitter_report_id"):
        return jsonify({
            "error": "duplicate_twitter",
            "report_id": trigger["twitter_report_id"],
        }), 409

    # 收集待送 Twitter cases：若觸發 case 有 batch_id，只取同 batch；否則只取這一筆
    trigger_batch = trigger.get("batch_id")

    def _is_pending_twitter(r):
        d = dict(r)
        platform  = (d.get("platform") or "").lower()
        is_tw     = platform in ("twitter/x", "twitter", "x")
        status_ok = d.get("status") in ("submitted",)
        no_report = not d.get("twitter_report_id")
        same_batch = (d.get("batch_id") == trigger_batch) if trigger_batch else (d["id"] == case_id)
        return is_tw and status_ok and no_report and same_batch

    pending = sorted(
        [dict(r) for r in rows if _is_pending_twitter(r)],
        key=lambda x: x["id"]
    )

    if not pending:
        pending = [trigger]

    cases_payload = [
        {"id": c["id"], "url": c["url"], "title": c["film_title"] or "JAOfilm series"}
        for c in pending
    ]

    subprocess.Popen(
        ["/opt/homebrew/bin/python3.11", "-u", "twitter_dmca.py",
         json.dumps(cases_payload)],
        cwd=str(Path(__file__).parent)
    )

    urls_preview = ", ".join(f"#{c['id']}" for c in pending)
    return jsonify({
        "ok": True,
        "message": f"已啟動 Twitter/X DMCA 填表，共 {len(pending)} 個案件（{urls_preview}），請查看 Chrome",
        "case_count": len(pending),
    })


@app.route("/set-twitter-report/<int:case_id>", methods=["POST"])
def set_twitter_report(case_id):
    """手動設定 twitter_report_id"""
    data      = request.get_json(force=True)
    report_id = (data.get("report_id") or "").strip()
    if not report_id:
        return jsonify({"error": "report_id 不能為空"}), 400
    tracker.set_twitter_report_id(case_id, report_id)
    rows = tracker.list_all()
    case = next((r for r in rows if r["id"] == case_id), None)
    if case:
        notes_add = f" | Twitter/X DMCA submitted {date.today().isoformat()}"
        tracker.update(case_id, case["status"], (case["notes"] or "") + notes_add)
    return jsonify({"ok": True})


@app.route("/twitter-dmca-reported", methods=["POST"])
def twitter_dmca_reported():
    """twitter_dmca.py 自動回報案件編號（支援單一 case_id 或多個 case_ids）"""
    data      = request.get_json(force=True)
    report_id = data.get("report_id")
    if not report_id:
        return jsonify({"error": "缺少 report_id"}), 400

    # 支援 case_ids（list）或舊版 case_id（單一）
    case_ids = data.get("case_ids") or ([int(data["case_id"])] if data.get("case_id") else None)
    if not case_ids:
        return jsonify({"error": "缺少 case_id 或 case_ids"}), 400

    for cid in case_ids:
        tracker.set_twitter_report_id(int(cid), report_id)

    return jsonify({"ok": True, "report_id": report_id, "updated": case_ids})


@app.route("/set-google-report/<int:case_id>", methods=["POST"])
def set_google_report(case_id):
    """手動設定 google_report_id（重複偵測時同步現有 report ID 用）"""
    data      = request.get_json(force=True)
    report_id = (data.get("report_id") or "").strip()
    if not report_id:
        return jsonify({"error": "report_id 不能為空"}), 400
    tracker.set_google_report_id(case_id, report_id)
    notes_add = f" | Google report ID 同步自重複偵測 {date.today().isoformat()}"
    rows = tracker.list_all()
    case = next((r for r in rows if r["id"] == case_id), None)
    if case:
        tracker.update(case_id, case["status"], (case["notes"] or "") + notes_add)
    return jsonify({"ok": True})


@app.route("/send-pending/<int:case_id>", methods=["POST"])
def send_pending(case_id):
    """確認送出 pending_action（目前支援 x_reply）"""
    import json as _json
    rows = tracker.list_all()
    case = next((r for r in rows if r["id"] == case_id), None)
    if not case or not case["pending_action"]:
        return jsonify({"error": "找不到待送出草稿"}), 404

    action = _json.loads(case["pending_action"])
    notice = {
        "subject": action["subject"],
        "to":      action["to"],
        "body":    action["body"],
        "path":    None,
    }
    ok = mailer.send_email(notice)
    if ok:
        tracker.clear_pending_action(case_id)
        notes = (case["notes"] or "") + f" | {action.get('type','reply')} 已送出 {date.today().isoformat()}"
        tracker.update(case_id, case["status"], notes)
        return jsonify({"ok": True, "message": f"已送出至 {action['to']}"})
    return jsonify({"error": "寄信失敗"}), 500


@app.route("/add-bulk", methods=["POST"])
def add_bulk():
    """批量新增侵權 URL（一次最多 20 個）"""
    data       = request.get_json(force=True)
    urls       = [u.strip() for u in (data.get("urls") or []) if u.strip()][:20]
    film_title = data.get("film_title", "JAOfilm series").strip() or "JAOfilm series"

    if not urls:
        return jsonify({"error": "沒有 URL"}), 400

    # 只有 > 1 個 URL 時才賦予 batch_id（單一 URL 不需要群組）
    batch_id = f"b{date.today().strftime('%Y%m%d')}{uuid.uuid4().hex[:6]}" if len(urls) > 1 else None

    def process_all():
        all_cases = tracker.list_all()
        existing_urls  = {r["url"] for r in all_cases}
        existing_norms = {tracker.normalize_url(r["url"]): r for r in all_cases}
        for url in urls:
            try:
                norm = tracker.normalize_url(url)
                if url in existing_urls or norm in existing_norms:
                    dup = next(
                        (r for r in all_cases if r["url"] == url or tracker.normalize_url(r["url"]) == norm),
                        None
                    )
                    print(f"[bulk skip] #{dup['id']} 重複 URL: {url[:60]}")
                    continue
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.lower().lstrip("www.")
                if any(s in domain for s in LEGITIMATE_SOURCES):
                    print(f"[bulk skip] {url} — 合法來源")
                    continue
                inv     = investigate(url)
                case_id = tracker.add(url, film_title, inv, batch_id=batch_id)
                today   = date.today().strftime("%Y-%m-%d")
                safe    = inv["domain"].replace(".", "_").replace("/", "_")
                notices_dir = Path(__file__).parent / "notices"
                os.makedirs(notices_dir, exist_ok=True)
                is_platform = bool(inv.get("platform"))
                if is_platform:
                    p = inv["platform"]
                    if p.get("email"):
                        from generate import generate_platform
                        path = notices_dir / f"{today}_{safe}_platform.txt"
                        path.write_text(generate_platform(url, inv["domain"], film_title, p["name"]))
                else:
                    if inv["abuse_emails"]:
                        path = notices_dir / f"{today}_{safe}_host.txt"
                        path.write_text(generate_host(url, inv["domain"], film_title,
                            inv["hosting_org"], inv["abuse_emails"][0]))
                    if inv["is_cloudflare"]:
                        path = notices_dir / f"{today}_{safe}_cloudflare.txt"
                        path.write_text(generate_cloudflare(url, inv["domain"], film_title))
                path = notices_dir / f"{today}_{safe}_c{case_id}_google.txt"
                path.write_text(generate_google_checklist(url, film_title))
                subprocess.run([sys.executable, "mailer.py", "--auto-send"],
                    capture_output=True, text=True, cwd=str(Path(__file__).parent))
                tracker.update(case_id, "submitted",
                    f"批量送出 {date.today().isoformat()}")
                print(f"[bulk] #{case_id} {inv['domain']} done")
            except Exception as e:
                print(f"[bulk error] {url}: {e}")

    import threading
    threading.Thread(target=process_all, daemon=True).start()
    return jsonify({"ok": True, "message": f"正在處理 {len(urls)} 個 URL，稍後重整查看結果"})


@app.route("/google-dmca-reported", methods=["POST"])
def google_dmca_reported():
    """google_dmca.py 自動回報檢舉 ID"""
    data = request.get_json(force=True)
    case_id   = data.get("case_id")
    report_id = data.get("report_id")
    if not case_id or not report_id:
        return jsonify({"error": "缺少 case_id 或 report_id"}), 400
    tracker.set_google_report_id(int(case_id), report_id)
    return jsonify({"ok": True, "report_id": report_id})


def _ping_url(url: str) -> int:
    """回傳 HTTP status code；連線失敗回傳負數"""
    import requests as _req
    try:
        resp = _req.get(
            url, timeout=12, allow_redirects=True,
            headers={"User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )},
            verify=True,
        )
        return resp.status_code
    except _req.exceptions.SSLError:
        return -1
    except _req.exceptions.Timeout:
        return -2
    except _req.exceptions.ConnectionError:
        return -3
    except Exception:
        return -9

def _code_to_verdict(code: int):
    """(verdict, label) from HTTP status code"""
    if code == 404:
        return "removed", "404 — 已刪除"
    if code == 410:
        return "removed", "410 — 永久移除"
    if code == 200:
        return "up", "200 — 仍在線"
    if code in (301, 302, 307, 308):
        return "up", f"{code} — 重新導向（仍活著）"
    if code == 403:
        return "unknown", "403 — 拒絕存取（無法確認）"
    if code == -1:
        return "unknown", "SSL 錯誤（無法確認）"
    if code == -2:
        return "unknown", "連線逾時（無法確認）"
    if code == -3:
        return "check", "連線拒絕（可能下架，請手動確認）"
    return "unknown", f"HTTP {code}（無法確認）"

def _get_extra_urls_from_notice(case_id: int, domain: str) -> list:
    """從 notice 檔案解析 extra URLs（DB 無記錄時的 fallback）"""
    import re as _re
    notices_dir = Path(__file__).parent / "notices"
    domain_safe = (domain or "").replace(".", "_")
    # 優先找 case-ID 命名的檔案
    candidates = list(notices_dir.glob(f"*_c{case_id}_google.txt"))
    if not candidates:
        candidates = list(notices_dir.glob(f"*_{domain_safe}_google.txt"))
    if not candidates:
        return []
    text = candidates[0].read_text(encoding="utf-8", errors="ignore")
    urls = _re.findall(r'https?://\S+', text)
    return [u.rstrip('.,;\n') for u in urls
            if "google.com" not in u.lower() and "support.google" not in u.lower()]

@app.route("/check-all", methods=["POST"])
def check_all():
    """ping 所有 submitted 案件的全部 URL（主 URL + extra_urls），回傳結果"""
    rows = tracker.list_all()
    results = []

    for r in rows:
        if r["status"] not in ("submitted", "pending"):
            continue
        domain = r["domain"] or ""

        # 收集全部 URL（DB extra_urls → fallback 解析 notice 檔案）
        all_urls = tracker.get_all_urls(r)
        if len(all_urls) == 1:
            extras_from_notice = _get_extra_urls_from_notice(r["id"], domain)
            if extras_from_notice:
                # 寫入 DB 供下次使用
                extras_new = [u for u in extras_from_notice if u != r["url"]]
                if extras_new and not r["extra_urls"]:
                    tracker.set_extra_urls(r["id"], extras_new)
                all_urls = list(dict.fromkeys([r["url"]] + extras_from_notice))

        # 逐一 ping
        url_results = []
        for u in all_urls:
            code = _ping_url(u)
            v, lbl = _code_to_verdict(code)
            url_results.append((u, code, v, lbl))

        # 主 URL 決定整體 verdict（其餘 URL 僅統計）
        primary_code    = next((code for u, code, v, lbl in url_results if u == r["url"]), -9)
        verdict, label  = _code_to_verdict(primary_code)

        n_total = len(url_results)
        n_down  = sum(1 for _, _, v, _ in url_results if v == "removed")

        if n_total > 1:
            label = f"{label}（{n_down}/{n_total} URL 已下線）"

        # 只有主 URL 404/410 才自動標記 removed
        if verdict == "removed":
            tracker.update(r["id"], "removed",
                           f"自動偵測 {label} ({date.today().isoformat()})")
            _notify("JAOfilm DMCA ✅", f"{domain} 已確認下架（{n_down}/{n_total}）")

        results.append({
            "id": r["id"], "domain": domain, "url": r["url"],
            "code": primary_code, "verdict": verdict, "label": label,
            "n_total": n_total, "n_down": n_down,
        })

    confirmed = sum(1 for r in results if r["verdict"] == "removed")
    up        = sum(1 for r in results if r["verdict"] == "up")
    need_check = sum(1 for r in results if r["verdict"] == "check")
    return jsonify({
        "results": results,
        "confirmed": confirmed,
        "up": up,
        "need_check": need_check,
    })


@app.route("/api/cases")
def api_cases():
    rows  = tracker.list_all()
    cases = enrich_cases(rows)
    return jsonify(cases)

# ── macOS 通知 ────────────────────────────────────────────────────────────────

def _notify(title, message):
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{message}" with title "{title}"'
        ], check=False)
    except Exception:
        pass

# ── 背景排程 ──────────────────────────────────────────────────────────────────

def scheduled_monitor():
    """每小時自動跑 monitor.py"""
    result = subprocess.run(
        [sys.executable, "monitor.py"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).parent)
    )
    if "處理了" in result.stdout and "0 封" not in result.stdout:
        _notify("JAOfilm DMCA", "✅ 自動處理了新的 Cloudflare 回信")
    print(f"[scheduler] monitor ran: {result.stdout.strip()[-200:]}")


def check_human_actions():
    """每天檢查是否有需要人工處理的案件"""
    rows = tracker.list_all()
    cases = enrich_cases(rows)
    human_needed = [c for c in cases if c["action"]["type"] == "human"]
    if human_needed:
        labels = ", ".join(c["domain"] for c in human_needed[:3])
        _notify("JAOfilm DMCA ⚠️", f"{len(human_needed)} 個案件需要你處理：{labels}")

# ── 啟動 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 加 mailer.py --auto-send 支援
    scheduler.add_job(scheduled_monitor,   "interval", hours=1,   id="monitor")
    scheduler.add_job(check_human_actions, "interval", hours=8,   id="human_check")
    scheduler.start()

    print("\n🚀  JAOfilm DMCA Dashboard")
    print("    http://localhost:5002\n")
    app.run(host="127.0.0.1", port=5002, debug=False)
