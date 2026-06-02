#!/usr/bin/env python3
"""
JAOfilm DMCA Web App
執行：python3 app.py
開啟：http://localhost:5002
"""

import os
import sys
import json
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

def next_action(case):
    status = case["status"]
    notes  = case["notes"] or ""

    if status == "pending":
        return {"type": "auto", "label": "待調查 + 寄信", "color": "yellow"}

    if status == "submitted":
        days = (date.today() - date.fromisoformat(case["date_submitted"] or date.today().isoformat())).days
        # 檢查是否有 Google notice 未處理
        domain = (case["domain"] or "").replace(".", "_")
        google_notice = list(Path(__file__).parent.glob(f"notices/*_{domain}_google.txt"))
        if google_notice:
            return {"type": "human", "label": "Google DMCA 表單待送出", "color": "red",
                    "notice": str(google_notice[0])}
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
    cases = []
    for r in rows:
        c = dict(r)
        c["action"] = next_action(c)
        c["days_since"] = ""
        if c["date_found"]:
            days = (date.today() - date.fromisoformat(c["date_found"])).days
            c["days_since"] = f"{days}天前"
        cases.append(c)
    return cases

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

            # 生成 notices
            today = date.today().strftime("%Y-%m-%d")
            safe  = inv["domain"].replace(".", "_").replace("/", "_")
            notices_dir = Path(__file__).parent / "notices"
            os.makedirs(notices_dir, exist_ok=True)

            if inv["abuse_emails"]:
                path = notices_dir / f"{today}_{safe}_host.txt"
                path.write_text(generate_host(url, inv["domain"], film_title,
                    inv["hosting_org"], inv["abuse_emails"][0]))

            if inv["is_cloudflare"]:
                path = notices_dir / f"{today}_{safe}_cloudflare.txt"
                path.write_text(generate_cloudflare(url, inv["domain"], film_title))

            path = notices_dir / f"{today}_{safe}_google.txt"
            path.write_text(generate_google_checklist(url, film_title))

            # 自動寄出 email notices
            result = subprocess.run(
                [sys.executable, "mailer.py", "--auto-send"],
                capture_output=True, text=True,
                cwd=str(Path(__file__).parent)
            )

            # macOS 通知
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

    domain = (case["domain"] or "").replace(".", "_")
    notices = list(Path(__file__).parent.glob(f"notices/*_{domain}_google.txt"))
    if not notices:
        return jsonify({"error": "找不到 Google notice 檔案"}), 404

    subprocess.Popen(
        ["/opt/homebrew/bin/python3.11", "google_dmca.py", str(notices[0])],
        cwd=str(Path(__file__).parent)
    )
    return jsonify({"ok": True, "message": "已啟動 Google DMCA 填表，請查看 Chrome"})


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
