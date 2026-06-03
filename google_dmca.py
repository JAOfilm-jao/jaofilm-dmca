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
import json
import urllib.request
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

    # 收集所有 https:// 開頭的 URL（含 Additional infringing URLs 區塊）
    all_urls = re.findall(r'https?://\S+', text)
    # 排除非侵權 URL：版權著作頁、Google 本身的支援頁、notice 範本連結
    EXCLUDE = ('jaofilm.com', 'support.google.com', 'google.com/legal',
               'help.x.com', 'help.twitter.com', 'icann.org', 'lumen.systems')
    infringing_urls = [u for u in all_urls if not any(e in u for e in EXCLUDE)]
    # 去重保序
    seen = set()
    deduped = []
    for u in infringing_urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)

    return {
        "work_title":      get("Copyrighted work"),
        "description":     get("Description"),
        "infringing_url":  deduped[0] if deduped else get("Infringing URL"),
        "infringing_urls": deduped,   # 全部 URL，用於多 URL 填表
    }

# ── 主流程 ────────────────────────────────────────────────────────────────────

async def run(notice_path: str, case_id: str = None):
    data = parse_notice(notice_path)
    desc = f"{data['description']}. Title: {data['work_title']}"

    url_count = len(data.get('infringing_urls', [data['infringing_url']]))
    print(f"\n📄  {notice_path}")
    print(f"    片名: {data['work_title']}")
    print(f"    URL:  {data['infringing_url'][:80]}")
    if url_count > 1:
        print(f"    ⚡ 多 URL 模式：共 {url_count} 個連結將一次填入")
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

        print("🔹 [2/9] 選擇 Google 搜尋（頂層）...")
        await click_radio(r"Google 搜尋|Google Search")

        print("🔹 [3/9] 選擇 Google 搜尋（子類型）...")
        # 頂層點擊後頁面展開子選項（Google 搜尋 / Images / AI Overviews…）
        # nth(0) 就是標準 Google 搜尋結果
        sub_radios = page.get_by_role("radio")
        await sub_radios.nth(0).wait_for(state="visible", timeout=10000)
        await sub_radios.nth(0).click()
        await page.wait_for_timeout(1200)

        print("🔹 [4/9] AI 內容 → 否...")
        # 此時出現「是/否」問「是否為 AI 生成內容」→ 選否
        try:
            await click_radio(r"否")
        except Exception:
            await page.get_by_role("radio").nth(1).click()
            await page.wait_for_timeout(800)

        print("🔹 [5/9] 選擇法律原因...")
        await click_radio(r"法律原因")

        print("🔹 [6/9] 智慧財產...")
        await click_radio(r"智慧財產")

        print("🔹 [7/9] 版權...")
        await click_radio(r"版權")

        print("🔹 [8/9] 是，我是版權所有人...")
        # 第一個 radio 就是「是，我是版權所有人…」
        await page.get_by_role("radio").nth(0).wait_for(state="visible", timeout=10000)
        await page.get_by_role("radio").nth(0).click()
        await page.wait_for_timeout(800)

        print("🔹 [9/9] 內容類型 → 其他（影片）...")
        await click_radio(r"其他")

        print("🔹 [9/9] 點擊「提出申訴」...")
        await page.get_by_role("link", name=re.compile(r"提出申訴")).click()
        await page.wait_for_load_state("networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # ── Phase 2: 填寫表單 ────────────────────────────────────────────────

        print("\n📝 填寫表單欄位...")

        async def fill_by_label(patterns, value):
            # 1. aria-label via get_by_role textbox
            for pat in patterns:
                try:
                    loc = page.get_by_role("textbox", name=re.compile(pat, re.I)).first
                    if await loc.count() > 0:
                        await loc.fill(value)
                        return
                except Exception:
                    pass
            # 2. get_by_label（<label> 元素）
            for pat in patterns:
                try:
                    loc = page.get_by_label(re.compile(pat, re.I)).first
                    if await loc.count() > 0:
                        await loc.fill(value)
                        return
                except Exception:
                    pass
            # 3. placeholder
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
        # aria-label: "在這裡輸入說明" / "在這裡輸入範例" / "在這裡輸入網址"
        await fill_by_label([r"在這裡輸入說明|著作說明|description|work.?description"], desc)
        await fill_by_label([r"在這裡輸入範例|版權著作.*url|authorized.*url|著作.*網址"], COPYRIGHT_URL)

        # 多 URL 模式：一行一個填入 textarea（Google 支援最多 1000 行）
        urls = data.get("infringing_urls") or [data["infringing_url"]]
        infringing_value = "\n".join(urls)
        await fill_by_label([r"在這裡輸入網址|侵權.*url|infringing.*url|侵害.*網址"], infringing_value)
        print(f"  ✅ 侵權 URL 填寫完成（{len(urls)} 個）")

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

        # aria-label 格式："3 6月 2026"（日 月份中文 年）
        _zh_months = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月']
        _today = date.today()
        _today_aria = f"{_today.day} {_zh_months[_today.month - 1]} {_today.year}"

        # 若行事曆停在錯誤月份就按「下個月」箭頭，最多翻 12 次
        clicked = False
        for _ in range(12):
            clicked = await page.evaluate(f"""() => {{
                const cells = document.querySelectorAll('[role=gridcell]');
                for (const c of cells) {{
                    if ((c.getAttribute('aria-label') || '').startsWith('{_today_aria}')) {{
                        c.click(); return true;
                    }}
                }}
                return false;
            }}""")
            if clicked:
                break
            # 點下個月箭頭
            await page.evaluate("""() => {
                const btns = [...document.querySelectorAll('[role=button]')];
                const next = btns.find(b =>
                    (b.getAttribute('aria-label') || '').match(/下個月|next.?month/i)
                );
                if (next) { next.click(); return; }
                // Fallback: 最後一個有 aria-label 的 button（通常是 >）
                const arr = btns.filter(b => b.getAttribute('aria-label'));
                if (arr.length) arr[arr.length - 1].click();
            }""")
            await page.wait_for_timeout(600)

        if not clicked:
            await page.locator('[role=gridcell]').first.click()
        await page.wait_for_timeout(800)
        print(f"  ✅ 日期設定完成（{_today_aria}）")

        # 數位簽名（aria-label: "簽名"）
        await fill_by_label([r"^簽名$|簽章|signature|電子簽名"], SIGNATURE)
        print(f"  ✅ 簽名: {SIGNATURE}")

        print(f"\n{'='*60}")
        print(f"✅  表單填完！請到 Chrome 確認 reCAPTCHA，然後手動按「提交」。")
        print(f"    系統將自動偵測成功頁並記錄檢舉 ID（最多等 5 分鐘）。")
        print(f"{'='*60}\n")

        # ── 輪詢成功頁，抓檢舉 ID ────────────────────────────────────────────
        if case_id:
            report_id = None
            for _ in range(150):   # 150 × 2s = 5 分鐘
                await asyncio.sleep(2)
                try:
                    content = await page.evaluate("() => document.body.innerText")
                    if "感謝你提交檢舉" in content or "檢舉 ID" in content:
                        m = re.search(r'檢舉\s*ID[：:]\s*([\d\-]+)', content)
                        if m:
                            report_id = m.group(1)
                        break
                except Exception:
                    pass

            if report_id:
                print(f"🎉 偵測到檢舉 ID：{report_id}")
                try:
                    payload = json.dumps({"case_id": case_id, "report_id": report_id}).encode()
                    req = urllib.request.Request(
                        "http://localhost:5002/google-dmca-reported",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    urllib.request.urlopen(req, timeout=5)
                    print("✅  已自動更新到儀表板")
                except Exception as e:
                    print(f"⚠️  回報失敗，請手動記錄：{e}")
            else:
                print("⚠️  5 分鐘內未偵測到成功頁，請手動記錄檢舉 ID")

# ── 入口 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python3 google_dmca.py <notice_file> [case_id]")
        sys.exit(1)
    _case_id = sys.argv[2] if len(sys.argv) >= 3 else None
    asyncio.run(run(sys.argv[1], _case_id))
