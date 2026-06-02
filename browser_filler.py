#!/usr/bin/env python3
"""
JAOfilm DMCA Browser Filler — browser-use
用真實 Chrome 自動填 Google DMCA 表單，填完停下讓你按送出。

用法：
  python3.11 browser_filler.py google notices/2026-05-30_gaydudesfucking_com_google.txt
  python3.11 browser_filler.py google notices/2026-05-30_gaymaletube_com_google.txt
"""

import sys
import re
import os
import asyncio
from pathlib import Path

# 載入 .env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from browser_use import Agent
from browser_use.llm import ChatAnthropic
from browser_use.browser.profile import BrowserProfile

from config import COPYRIGHT_OWNER, BRAND_NAME, CONTACT_EMAIL, WEBSITE

# ── 資料解析 ──────────────────────────────────────────────────────────────────

def parse_google_notice(path):
    text = Path(path).read_text(encoding="utf-8")

    def extract(label):
        m = re.search(rf"{label}:\s*(.+)", text)
        return m.group(1).strip() if m else ""

    return {
        "name":           extract("Your name"),
        "company":        extract("Company"),
        "email":          CONTACT_EMAIL,
        "country":        extract("Country"),
        "work_title":     extract("Copyrighted work"),
        "description":    extract("Description"),
        "infringing_url": extract("Infringing URL"),
        "signature":      extract("Signature"),
    }

# ── 主流程 ────────────────────────────────────────────────────────────────────

async def fill_google_dmca(notice_path: str):
    data = parse_google_notice(notice_path)

    print(f"\n📄  Notice: {notice_path}")
    print(f"    片名:  {data['work_title']}")
    print(f"    URL:   {data['infringing_url'][:80]}")
    print(f"\n⚠️   瀏覽器開啟後請不要碰滑鼠鍵盤")
    print(f"    填完後你自己按最後的送出鍵\n")

    api_key = os.environ.get("JAO_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌  請在 .env 加入：JAO_ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    task = f"""
Fill out the Google DMCA copyright infringement report form for Google Search results.

Start at: https://support.google.com/legal/troubleshooter/1114905

Navigate through the multi-step wizard using these details:
- First name: CHIH WEI
- Last name: JAO
- Digital signature: CHIH WEI JAO (must exactly match First name + Last name combined)
- Company/Organization: JAOfilm
- Email: {data['email']}
- Country: {data['country']}
- I am: The copyright owner
- Copyrighted work title: {data['work_title']}
- Work description: {data['description']}
- Infringing URL: {data['infringing_url']}
- Digital signature: CHIH WEI JAO (must exactly match First name + Last name combined, not just one word)

Rules:
1. When asked what type of legal issue, choose copyright-related options
2. When asked what Google product, choose Google Search
3. Fill every required field with the information above
4. Check all required acknowledgment checkboxes
5. STOP just before the final Submit button — do NOT click Submit
6. When all fields are complete and ready for human review, say: FORM_COMPLETE
"""

    llm = ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=api_key,
    )

    # 連接已開著的 Chrome（CDP）
    profile = BrowserProfile(
        cdp_url="http://127.0.0.1:9222",
    )

    agent = Agent(
        task=task,
        llm=llm,
        browser_profile=profile,
        max_actions_per_step=5,
        use_vision=True,
        initial_actions=[
            {"navigate": {"url": "https://support.google.com/legal/troubleshooter/1114905"}}
        ],
    )

    print("🤖  browser-use 啟動中...")
    result = await agent.run(max_steps=40)

    output = str(result)
    print(f"\n{'='*60}")
    if "FORM_COMPLETE" in output:
        print("✅  表單填完！請確認所有欄位後自己按送出。")
    else:
        print("⚠️   請確認表單狀態，可能需要手動補填。")
    print(f"{'='*60}\n")

    try:
        input("確認後按 Enter 結束...")
    except EOFError:
        pass

# ── 入口 ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("用法：python3.11 browser_filler.py google <notice_file>")
        sys.exit(1)

    form_type   = sys.argv[1]
    notice_path = sys.argv[2]

    if form_type == "google":
        asyncio.run(fill_google_dmca(notice_path))
    else:
        print(f"❌  未知類型：{form_type}（目前支援：google）")
        sys.exit(1)

if __name__ == "__main__":
    main()
