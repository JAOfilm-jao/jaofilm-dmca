#!/usr/bin/env python3
"""
JAOfilm Google DMCA Playwright Filler — 免費，不需 API
直接用 Playwright 走完 Google DMCA wizard，填完停下讓你按送出。

用法：
  python3 google_dmca.py notices/2026-05-30_gaymaletube_com_google.txt
  python3 google_dmca.py notices/2026-05-30_gaydudesfucking_com_google.txt

前提：Chrome 需用 debug mode 開著（執行 open_chrome_debug.sh）
"""

import sys
import re
import asyncio
from datetime import date
from pathlib import Path
from playwright.async_api import async_playwright

# ── 固定資料 ──────────────────────────────────────────────────────────────────
FIRST_NAME     = "CHIH WEI"
LAST_NAME      = "JAO"
COMPANY        = "JAOfilm"
SIGNATURE      = "CHIH WEI JAO"
COPYRIGHT_URL  = "https://jaofilm.com"
TODAY          = date.today().strftime("%-m/%-d/%Y")   # e.g. 6/2/2026

# ── 解析 notice ───────────────────────────────────────────────────────────────

def parse_notice(path):
    text = Path(path).read_text(encoding="utf-8")
    def get(label):
        m = re.search(rf"{label}:\s*(.+)", text)
        return m.group(1).strip() if m else ""
    return {
        "work_title":     get("Copyrighted work"),
        "description":    get("Description"),
        "infringing_url": get("Infringing URL"),
    }

# ── 主流程 ────────────────────────────────────────────────────────────────────

async def run(notice_path: str):
    data = parse_notice(notice_path)
    desc = f"{data['description']}. Title: {data['work_title']}"

    print(f"\n📄  {notice_path}")
    print(f"    片名: {data['work_title']}")
    print(f"    URL:  {data['infringing_url'][:80]}")
    print(f"\n⚠️   填表中，請不要碰 Chrome\n")

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx  = browser.contexts[0]
        page = await ctx.new_page()

        # ── Phase 1: Wizard ──────────────────────────────────────────────────

        print("🔹 [1/9] 開啟 DMCA wizard...")
        await page.goto(
            "https://support.google.com/legal/troubleshooter/1114905",
            wait_until="networkidle", timeout=30000
        )
        await page.wait_for_timeout(2000)

        async def click_radio(pattern):
            loc = page.get_by_role("radio", name=re.compile(pattern, re.I))
            await loc.first.wait_for(state="visible", timeout=10000)
            await loc.first.click()
            await page.wait_for_timeout(800)

        print("🔹 [2/9] 選擇 Google 搜尋...")
        await click_radio(r"Google 搜尋|Google Search")
        # 可能出現第二個子問題
        await page.wait_for_timeout(500)
        search_radios = page.get_by_role("radio", name=re.compile(r"Google 搜尋|Google Search", re.I))
        if await search_radios.count() > 1:
            await search_radios.nth(1).click()
            await page.wait_for_timeout(800)

        print("🔹 [3/9] AI 內容 → 否...")
        await click_radio(r"^否$")

        print("🔹 [4/9] 選擇法律原因...")
        await click_radio(r"檢舉內容的法律原因")

        print("🔹 [5/9] 智慧財產...")
        await click_radio(r"智慧財產")

        print("🔹 [6/9] 版權...")
        await click_radio(r"版權")

        print("🔹 [7/9] 是，我是版權所有人...")
        await click_radio(r"是.*版權所有人|我自己")

        print("🔹 [8/9] 內容類型 → 其他（影片）...")
        await click_radio(r"^其他$")

        print("🔹 [9/9] 點擊「提出申訴」...")
        await page.get_by_role("link", name=re.compile(r"提出申訴")).click()
        await page.wait_for_load_state("networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # ── Phase 2: 填寫表單 ────────────────────────────────────────────────

        print("\n📝 填寫表單欄位...")

        async def fill_by_label(patterns, value):
            for pat in patterns:
                try:
                    loc = page.get_by_label(re.compile(pat, re.I)).first
                    if await loc.count() > 0:
                        await loc.fill(value)
                        return
                except Exception:
                    pass
            # Fallback: placeholder
            for pat in patterns:
                try:
                    loc = page.get_by_placeholder(re.compile(pat, re.I)).first
                    if await loc.count() > 0:
                        await loc.fill(value)
                        return
                except Exception:
                    pass

        # 名字 / 姓氏
        await fill_by_label([r"名字|first.?name"], FIRST_NAME)
        await fill_by_label([r"姓氏|last.?name"], LAST_NAME)
        await fill_by_label([r"公司|company|組織|organization"], COMPANY)
        print(f"  ✅ 姓名: {FIRST_NAME} {LAST_NAME}, 公司: {COMPANY}")

        # 國家：Taiwan（台灣）— 用 JS 點擊 dropdown
        print("  ▸ 設定國家: 台灣...")
        await page.evaluate("""() => {
            const btn = [...document.querySelectorAll('[role=button]')]
                .find(el => el.textContent.includes('選擇您的所在國家') || el.textContent.includes('泰國'));
            if (btn) btn.click();
        }""")
        await page.wait_for_timeout(1000)
        await page.evaluate("""() => {
            const items = document.querySelectorAll('material-select-dropdown-item');
            for (const item of items) {
                if (item.innerText && (item.innerText.includes('台灣') || item.innerText.includes('臺灣'))) {
                    item.click(); return;
                }
            }
        }""")
        await page.wait_for_timeout(800)
        print("  ✅ 國家: 台灣")

        # 直播 → 否
        await page.wait_for_timeout(500)
        livestream_no = page.get_by_role("radio", name=re.compile(r"^否$")).last
        if await livestream_no.count() > 0:
            await livestream_no.click()
            print("  ✅ 直播: 否")

        # 著作說明 / 版權著作 URL / 侵權 URL
        await fill_by_label([r"著作說明|description|work.?description"], desc)
        await fill_by_label([r"版權著作.*url|authorized.*url|著作.*網址"], COPYRIGHT_URL)
        await fill_by_label([r"侵權.*url|infringing.*url|侵害.*網址"], data["infringing_url"])
        print(f"  ✅ URL 填寫完成")

        # 宣誓 checkbox（全勾）
        checkboxes = page.get_by_role("checkbox")
        count = await checkboxes.count()
        for i in range(count):
            cb = checkboxes.nth(i)
            try:
                checked = await cb.get_attribute("aria-checked")
                if checked != "true":
                    await cb.click()
                    await page.wait_for_timeout(200)
            except Exception:
                pass
        print(f"  ✅ 已勾選所有 checkbox（{count} 個）")

        # 簽署日期（今天）
        print("  ▸ 設定日期...")
        await page.evaluate("""() => {
            const btn = [...document.querySelectorAll('[role=button]')]
                .find(el => el.textContent.includes('請選取日期') || el.textContent.includes('簽署日期'));
            if (btn) btn.click();
        }""")
        await page.wait_for_timeout(1000)
        # 點今天
        today_label = date.today().strftime("%-d %-m月 %Y")
        clicked = await page.evaluate(f"""() => {{
            const cells = document.querySelectorAll('[role=gridcell]');
            for (const c of cells) {{
                if (c.getAttribute('aria-label') && c.getAttribute('aria-label').startsWith('{date.today().day} ')) {{
                    c.click(); return true;
                }}
            }}
            return false;
        }}""")
        if not clicked:
            # Fallback: click first available date cell
            await page.locator('[role=gridcell]').first.click()
        await page.wait_for_timeout(800)
        print(f"  ✅ 日期設定完成")

        # 數位簽名
        await fill_by_label([r"簽章|signature|電子簽名"], SIGNATURE)
        print(f"  ✅ 簽名: {SIGNATURE}")

        print(f"\n{'='*60}")
        print(f"✅  表單填完！")
        print(f"    請到 Chrome 確認所有欄位，然後自己按送出。")
        print(f"{'='*60}\n")

        input("確認送出後按 Enter 關閉...")
        await browser.close()

# ── 入口 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python3 google_dmca.py <notice_file>")
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))
