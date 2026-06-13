#!/usr/bin/env python3
"""
JAOfilm Twitter/X DMCA Playwright Filler
自動填寫 https://help.x.com/en/forms/ipi/dmca/copyright-owner
填完停下，讓你手動按 Submit。

用法：
  python3 twitter_dmca.py '<JSON>'
  JSON 格式：[{"id": 69, "url": "https://x.com/...", "title": "JAOfilm series"}, ...]

舊式（單一，向下相容）：
  python3 twitter_dmca.py <case_id> <infringing_url> [<film_title>]

前提：Chrome Debug Mode 開著（bash open_chrome_debug.sh）
"""

import sys
import re
import asyncio
import json
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from playwright.async_api import async_playwright

# ── 固定申請人資料 ────────────────────────────────────────────────────────────
# Chrome 必須以 @jaofilm_DMCA（dmca@jaofilm.com）登入，才能讓 email 欄位自動帶入
# 正確的 domain（jaofilm.com）是推特確認版權所有人身分的關鍵
FULL_NAME      = "CHIH WEI JAO"
COMPANY        = "JAOfilm"
JOB_TITLE      = "Film Director"
EMAIL          = "dmca@jaofilm.com"   # @jaofilm_DMCA 帳號的 email（表單由 X 自動填入）
STREET_ADDRESS = "Ln 150 4F Sec 1 Xinsheng S Rd"
CITY           = "Taipei"
PHONE          = ""                   # 不填電話（成功表單為空）
COUNTRY_CODE   = "TW"
COPYRIGHT_URL  = "https://jaofilm.com/films"
FORM_URL       = "https://help.x.com/en/forms/ipi/dmca"

# 送表前移除 Twitter 追蹤參數（?s=XX ?t=XX ?ref_src=XX 等），只保留 status ID
_TWITTER_TRACKING_PARAMS = {"s", "t", "ref_src", "ref_url", "src", "cxt"}

def clean_tweet_url(url: str) -> str:
    """去掉 Twitter 追蹤參數，只保留 /status/ID 識別的部份。"""
    try:
        p = urlparse(url)
        qs = parse_qs(p.query, keep_blank_values=True)
        cleaned = {k: v for k, v in qs.items() if k.lower() not in _TWITTER_TRACKING_PARAMS}
        new_query = urlencode(cleaned, doseq=True)
        return urlunparse(p._replace(query=new_query))
    except Exception:
        return url


async def run(cases: list):
    """
    cases: list of {"id": int, "url": str, "title": str}
    """
    # ── 重複防呆 ─────────────────────────────────────────────────────────────
    try:
        import tracker as _tracker
        submitted = _tracker.get_twitter_submitted_urls()
        filtered = []
        for c in cases:
            if c["url"] in submitted:
                cid, rid = submitted[c["url"]]
                print(f"🚫 跳過已送出 case #{c['id']}：{rid}  {c['url'][:60]}")
            else:
                filtered.append(c)
        cases = filtered
    except Exception as e:
        print(f"⚠️  pre-check 例外（繼續填表）: {e}")

    if not cases:
        print("✅  所有 URL 均已送出，無需填表。")
        return

    # 使用第一個案件的標題作為描述基礎
    primary = cases[0]
    film_title = primary.get("title") or "JAOfilm series"
    # 每個 case 可帶 original_url 欄位指向具體影片頁；預設用總覽頁
    original_url = primary.get("original_url") or COPYRIGHT_URL

    # 清理所有 case URL（移除追蹤參數）
    for c in cases:
        c["url"] = clean_tweet_url(c["url"])

    # 若 film_title 是泛稱，描述也保持通用；否則用成功下架的措辭格式
    is_generic = film_title.lower() in ("jaofilm series", "jaofilm", "")
    film_page  = original_url if original_url != COPYRIGHT_URL else None

    if is_generic:
        work_desc = (
            "This is an original film/video production by JAOfilm. "
            "I am the original creator and the exclusive copyright holder of this video. "
            "The official source page can be verified at: https://jaofilm.com/films"
        )
    else:
        page_line = f" The official source page, which includes the trailer, can be verified at: {film_page}" if film_page else ""
        work_desc = (
            f'This is an original film/video production titled "{film_title}". '
            f"I am the original creator and the exclusive copyright holder of this video."
            f"{page_line}"
        )

    if is_generic:
        infringement_desc = (
            "The infringement consists of the direct uploading and distribution of my complete "
            "video production within the user's tweet. The media attached to this post is exactly "
            "the copyrighted material I own. I have not authorized this user to upload, share, or "
            "distribute my full video. I request the immediate takedown of this post and the "
            "associated media file."
        )
    else:
        infringement_desc = (
            f'The infringement consists of the direct uploading and distribution of my complete '
            f'video production, "{film_title}", within the user\'s tweet. The media attached to '
            f"this post is exactly the copyrighted material I own. I have not authorized this user "
            f"to upload, share, or distribute my full video. I request the immediate takedown of "
            f"this post and the associated media file."
        )

    ids_str = ", ".join(f"#{c['id']}" for c in cases)
    print(f"\n🐦  Twitter/X DMCA 填表（{len(cases)} 個 URL）")
    print(f"    案件 {ids_str}")
    for c in cases:
        print(f"    ▸ #{c['id']} {c['url'][:70]}")
    print(f"\n⚠️   填表中，請不要碰 Chrome\n")

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx  = browser.contexts[0]
        page = await ctx.new_page()

        # ── [1] 開表單 ────────────────────────────────────────────────────────
        print("🔹 [1/7] 開啟 Twitter/X DMCA 表單...")
        await page.goto(FORM_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        print(f"       URL: {page.url}")

        # ── [2] 選 Copyright infringement ────────────────────────────────────
        print("🔹 [2/7] 選擇「Copyright infringement」...")
        selects = page.locator("select")
        await selects.nth(0).select_option(value="/en/forms/ipi/dmca")
        await page.wait_for_timeout(1500)
        print(f"       select[0] → /en/forms/ipi/dmca ✅")

        # ── [3] 選 I am the copyright owner ──────────────────────────────────
        print("🔹 [3/7] 選擇「I am the copyright owner」...")
        await selects.nth(1).select_option(value="/en/forms/ipi/dmca/copyright-owner")
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)
        print(f"       URL: {page.url}")

        # ── [4] 個人資料欄位 ──────────────────────────────────────────────────
        print("\n📝 [4/7] 填寫個人資料...")

        async def fill_by_name(name_suffix, value):
            """用 name*= 找 input/textarea，以 JS native setter 填值（React SPA 必須）"""
            result = await page.evaluate(f"""(val) => {{
                const el = document.querySelector('[name*="{name_suffix}"]');
                if (!el) return false;
                el.focus();
                const tag = el.tagName.toLowerCase();
                const proto = tag === 'textarea'
                    ? window.HTMLTextAreaElement.prototype
                    : window.HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                if (setter) setter.call(el, val); else el.value = val;
                el.dispatchEvent(new Event('input',  {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                el.blur();
                return true;
            }}""", value)
            return bool(result)

        async def select_by_name(name_suffix, value):
            """用 name*= 找 select，選值"""
            loc = page.locator(f"select[name*='{name_suffix}']")
            if await loc.count() > 0:
                await loc.first.select_option(value=value)
                return True
            return False

        # 版權所有人全名（Copyright owner's full name）
        ok = await fill_by_name("Content_Owner_Name__c", FULL_NAME)
        print(f"  {'✅' if ok else '⚠️ '} Copyright owner's full name: {FULL_NAME}")

        # 申請人全名（Your full name）
        ok = await fill_by_name("Form_Name__c", FULL_NAME)
        print(f"  {'✅' if ok else '⚠️ '} Your full name: {FULL_NAME}")

        # 公司
        ok = await fill_by_name("company", COMPANY)
        print(f"  {'✅' if ok else '⚠️ '} Company: {COMPANY}")

        # Job title (required)
        ok = await fill_by_name("jobTitle", JOB_TITLE)
        print(f"  {'✅' if ok else '⚠️ '} Job title: {JOB_TITLE}")

        # Email — X 帳號自動帶入並鎖定，不覆寫（覆寫會破壞 React 驗證）
        auto_email = await page.evaluate("""() => {
            const el = document.querySelector('[name*="Form_Email__c"]');
            return el ? (el.value || '') : '';
        }""")
        print(f"  ℹ️  Email: 由 X 帳號自動帶入（{auto_email}），跳過覆寫")

        # Street address (required) — 慣例只填城市，不填完整地址
        ok = await fill_by_name("streetAddress", STREET_ADDRESS)
        print(f"  {'✅' if ok else '⚠️ '} Street address: {STREET_ADDRESS}")

        # City (required)
        ok = await fill_by_name("city", CITY)
        print(f"  {'✅' if ok else '⚠️ '} City: {CITY}")

        # Phone（選填，成功表單為空，跳過）
        if PHONE:
            ok = await fill_by_name("Form_number__c", PHONE)
            print(f"  {'✅' if ok else '⚠️ '} Phone: {PHONE}")
        else:
            print(f"  ℹ️  Phone: 空白（略過）")

        # 國家（required）
        ok = await select_by_name("country", COUNTRY_CODE)
        print(f"  {'✅' if ok else '⚠️ '} Country: Taiwan (TW)")

        # ── [5] Radio 按鈕 ────────────────────────────────────────────────────
        print("\n📝 [5/7] 選擇選項...")

        # Where is this infringement? → Twitter（唯一選項，直接點）
        loc_twitter = page.locator("input[type=radio][name*='Type_of_Issue__c'][value='Twitter']")
        if await loc_twitter.count() > 0:
            await loc_twitter.click()
            print(f"  ✅ Where is this infringement? → Twitter")
        else:
            print(f"  ⚠️  Type_of_Issue radio 找不到（可能已預設）")

        # Type of copyrighted work → Video/Audiovisual Recording
        loc_video = page.locator("input[type=radio][value='Video/Audiovisual Recording']")
        if await loc_video.count() > 0:
            await loc_video.click()
            print(f"  ✅ Type of copyrighted work → Video/Audiovisual Recording")
        else:
            print(f"  ⚠️  Video radio 找不到，嘗試備用值...")
            loc_other = page.locator("input[type=radio][value='Other']")
            if await loc_other.count() > 0:
                await loc_other.click()
                print(f"  ✅ → Other（備用）")

        # ── [6] 著作與侵權欄位 ───────────────────────────────────────────────
        print("\n📝 [6/7] 填寫著作與侵權資料...")

        # Description of the original work
        ok = await fill_by_name("DescriptionText", work_desc)
        print(f"  {'✅' if ok else '⚠️ '} Description of original work")

        # Link(s) to the original work（優先用具體影片頁，否則用總覽頁）
        ok = await fill_by_name("originalWork[0].value", original_url)
        print(f"  {'✅' if ok else '⚠️ '} Link to original work: {original_url}")

        # ── 多個侵權 URL ─────────────────────────────────────────────────────
        async def fill_infringing_url(index, url):
            """
            index=0：直接填第一個欄位
            index>0：點「Add another link」→ 等新欄位確實出現 → 填入
            """
            if index == 0:
                ok = await fill_by_name("Infringing_Urls__c[0].value", url)
                return ok

            # 記錄目前欄位數（期望新增後 +1）
            count_before = await page.evaluate(
                "() => document.querySelectorAll('[name*=\"Infringing_Urls__c\"]').length"
            )
            expected = count_before + 1

            # 點擊在最後一個 Infringing_Urls__c 欄位「之後」的 Add another link 按鈕
            clicked = await page.evaluate("""() => {
                const inputs = document.querySelectorAll('[name*="Infringing_Urls__c"]');
                if (!inputs.length) return false;
                const lastInput = inputs[inputs.length - 1];
                const btns = Array.from(document.querySelectorAll('button, [role="button"]'))
                    .filter(b => {
                        const t = (b.textContent || '').trim().toLowerCase();
                        return t.includes('add another') || t.includes('add link') || t.includes('add url');
                    });
                for (const b of btns) {
                    if (lastInput.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) {
                        b.click();
                        return true;
                    }
                }
                return false;
            }""")

            if not clicked:
                print(f"  ⚠️  找不到「Add another」按鈕（index {index}），跳過此 URL")
                return False

            # 等待新欄位出現（最多 8 秒，每 200ms 檢查一次）
            appeared = False
            for _ in range(40):
                await page.wait_for_timeout(200)
                count_now = await page.evaluate(
                    "() => document.querySelectorAll('[name*=\"Infringing_Urls__c\"]').length"
                )
                if count_now >= expected:
                    appeared = True
                    break

            if not appeared:
                print(f"  ⚠️  新欄位 {expected} 秒內未出現（index {index}），跳過此 URL")
                return False

            print(f"  ✅ Add another link 成功，填第 {expected} 個欄位")

            # 填剛出現的最後一個欄位
            result = await page.evaluate("""(val) => {
                const els = document.querySelectorAll('[name*="Infringing_Urls__c"]');
                if (!els.length) return false;
                const el = els[els.length - 1];
                el.focus();
                const proto = window.HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                if (setter) setter.call(el, val); else el.value = val;
                el.dispatchEvent(new Event('input',  {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                el.blur();
                return true;
            }""", url)
            return bool(result)

        for i, c in enumerate(cases):
            ok = await fill_infringing_url(i, c["url"])
            print(f"  {'✅' if ok else '⚠️ '} Infringing URL [{i+1}/{len(cases)}]: {c['url'][:70]}")

        # Describe infringement
        ok = await fill_by_name("describeInfringement", infringement_desc)
        print(f"  {'✅' if ok else '⚠️ '} Describe infringement")

        # ── Checkboxes ────────────────────────────────────────────────────────
        for cb_name in ["acknowledgement", "good-faith-belief", "authority-to-act"]:
            loc = page.locator(f"input[type=checkbox][name='{cb_name}']")
            if await loc.count() > 0:
                if not await loc.first.is_checked():
                    await loc.first.click()
                    await page.wait_for_timeout(200)
                print(f"  ✅ Checkbox: {cb_name}")
            else:
                print(f"  ⚠️  Checkbox 找不到: {cb_name}")

        # ── Signature ─────────────────────────────────────────────────────────
        ok = await fill_by_name("signature", FULL_NAME)
        print(f"  {'✅' if ok else '⚠️ '} Signature: {FULL_NAME}")

        # ── 完成提示 ──────────────────────────────────────────────────────────
        print(f"\n{'='*60}")
        print(f"✅  表單填完（{len(cases)} 個 URL）！請到 Chrome：")
        print(f"    1. 確認所有欄位正確")
        print(f"    2. 按下「Submit」按鈕送出")
        print(f"    系統將自動偵測送出並記錄（最多等 5 分鐘）。")
        print(f"{'='*60}\n")

        # ── [7] 輪詢成功頁 ────────────────────────────────────────────────────
        case_ids  = [c["id"] for c in cases]
        today_str = date.today().strftime("%Y%m%d")
        print(f"⏳ [7/7] 等待你按 Submit（最多 5 分鐘）...")
        report_id = None
        for _ in range(150):
            await asyncio.sleep(2)
            try:
                content     = await page.evaluate("() => document.body.innerText")
                current_url = page.url

                is_success = (
                    re.search(
                        r"thank you|we.?ve received|received your report|"
                        r"report submitted|submission received|your request has been",
                        content, re.I
                    )
                    or "confirmation" in current_url
                    or "thank" in current_url
                    or "success" in current_url
                )

                if is_success:
                    m = re.search(
                        r'(?:case|reference|report|ticket|request|confirmation)\s*'
                        r'(?:number|#|no\.?|id)[:\s#]*([A-Z0-9\-]{4,})',
                        content, re.I
                    )
                    if not m:
                        m = re.search(r'#([0-9]{5,})', content)
                    report_id = m.group(1) if m else f"X-{today_str}-submitted"
                    print(f"\n🎉 偵測到成功頁面！")
                    break
            except Exception:
                pass

        ids_str = ",".join(str(x) for x in case_ids)
        if report_id:
            print(f"   案件編號：{report_id}  |  案件：{ids_str}")
            try:
                payload = json.dumps({"case_ids": case_ids, "report_id": report_id}).encode()
                req = urllib.request.Request(
                    "http://localhost:5002/twitter-dmca-reported",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                urllib.request.urlopen(req, timeout=5)
                print(f"✅  已自動更新 {len(case_ids)} 個案件到儀表板")
            except Exception as e:
                print(f"⚠️  回報失敗，手動指令（逐一執行）：")
                for cid in case_ids:
                    print(f"    curl -X POST http://localhost:5002/set-twitter-report/{cid} "
                          f"-H 'Content-Type: application/json' -d '{{\"report_id\":\"{report_id}\"}}'")
        else:
            print(f"⚠️  5 分鐘內未偵測到成功頁，若已送出請手動更新：")
            for cid in case_ids:
                print(f"    curl -X POST http://localhost:5002/set-twitter-report/{cid} "
                      f"-H 'Content-Type: application/json' -d '{{\"report_id\":\"X-{today_str}-manual\"}}'")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python3 twitter_dmca.py '<JSON cases>'")
        sys.exit(1)

    first_arg = sys.argv[1]
    # 嘗試解析 JSON（新格式）
    try:
        _cases = json.loads(first_arg)
        if isinstance(_cases, dict):
            _cases = [_cases]
    except (json.JSONDecodeError, TypeError):
        # 舊格式向下相容：python3 twitter_dmca.py <case_id> <url> [<title>]
        if len(sys.argv) < 3:
            print("用法：python3 twitter_dmca.py '<JSON cases>'")
            sys.exit(1)
        _cases = [{"id": sys.argv[1], "url": sys.argv[2],
                   "title": sys.argv[3] if len(sys.argv) >= 4 else "JAOfilm series"}]

    asyncio.run(run(_cases))
