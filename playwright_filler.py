#!/usr/bin/env python3
"""
JAOfilm DMCA Playwright Form Filler
不需要 API key。用你電腦裝的真實 Chrome 填表，填完等你按送出。

用法：
  python3 playwright_filler.py cloudflare notices/2026-05-30_pornone_com_cloudflare.txt
  python3 playwright_filler.py cloudflare notices/2026-05-30_gaymaletube_com_cloudflare.txt
"""

import sys
import re
import os
import asyncio
from playwright.async_api import async_playwright

from config import COPYRIGHT_OWNER, BRAND_NAME, CONTACT_EMAIL, WEBSITE

# ── 解析 notice 檔案 ────────────────────────────────────────────────────────────

def parse_notice(path):
    with open(path, encoding='utf-8') as f:
        text = f.read()

    # 找侵權 URL（排除我們自己的網站）
    all_urls = re.findall(r'https?://[^\s\n,]+', text)
    infringing = [u for u in all_urls
                  if 'jaofilm.com' not in u
                  and 'abuse.cloudflare.com' not in u
                  and 'support.google.com' not in u]

    # 從 notice 第一行抓 domain
    m = re.search(r'at\s+([\w.-]+\.\w+)', text)
    domain = m.group(1) if m else os.path.basename(path).split('_')[1].replace('_', '.')

    return {
        'domain': domain,
        'infringing_urls': infringing,
        'text': text,
    }

# ── 填 Cloudflare 版權申訴表單 ────────────────────────────────────────────────

async def fill_cloudflare(page, data):
    print(f"\n🌐  開啟 Cloudflare 表單...")
    await page.goto('https://abuse.cloudflare.com/copyright', wait_until='networkidle')
    await page.wait_for_timeout(1500)

    # Step 1: 點開 "Choose an abuse type" 下拉
    print("  ▸ 選擇申訴類型...")
    dropdown_trigger = page.get_by_text('Choose an abuse type')
    await dropdown_trigger.click()
    await page.wait_for_timeout(800)

    # 點選 Copyright Infringement
    option = page.get_by_text('Copyright Infringement', exact=False).last
    await option.click()
    await page.wait_for_timeout(1500)

    # Step 2: 填表單欄位
    print("  ▸ 填寫欄位...")

    async def try_fill(selectors, value):
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.fill(value)
                    return True
            except Exception:
                continue
        return False

    # 姓名
    await try_fill([
        'input[name*="name" i]',
        'input[placeholder*="name" i]',
        'input[id*="name" i]',
    ], COPYRIGHT_OWNER)

    # Email
    await try_fill([
        'input[type="email"]',
        'input[name*="email" i]',
        'input[placeholder*="email" i]',
    ], CONTACT_EMAIL)

    # 公司（選填）
    await try_fill([
        'input[name*="company" i]',
        'input[name*="org" i]',
        'input[placeholder*="company" i]',
        'input[placeholder*="organization" i]',
    ], BRAND_NAME)

    # 侵權 URL
    urls_text = '\n'.join(data['infringing_urls'])
    await try_fill([
        'textarea[name*="url" i]',
        'textarea[placeholder*="url" i]',
        'textarea[id*="url" i]',
        'textarea[name*="infringing" i]',
    ], urls_text)

    # 原著作說明
    desc = (
        f'Original audiovisual works produced exclusively by {BRAND_NAME} ({WEBSITE}). '
        f'The listed URLs distribute JAOfilm copyrighted content without any license or authorization. '
        f'These films are only available through official channels: fansone.co and onlyfans.com/jaofilm.'
    )
    await try_fill([
        'textarea[name*="description" i]',
        'textarea[name*="original" i]',
        'textarea[name*="work" i]',
        'textarea[placeholder*="description" i]',
        'textarea[placeholder*="original" i]',
    ], desc)

    # 數位簽名
    await try_fill([
        'input[name*="signature" i]',
        'input[placeholder*="signature" i]',
        'input[id*="signature" i]',
        'input[name*="sign" i]',
    ], COPYRIGHT_OWNER)

    # 勾選所有 checkbox
    checkboxes = page.locator('input[type="checkbox"]')
    count = await checkboxes.count()
    for i in range(count):
        cb = checkboxes.nth(i)
        if not await cb.is_checked():
            await cb.check()
            await page.wait_for_timeout(200)

    print(f"\n✅  填完了！({len(data['infringing_urls'])} 個侵權 URL)")
    print(f"    請確認所有欄位 → 自己按送出 → 回來更新狀態")
    print(f"\n    按 Enter 關閉瀏覽器，或直接在瀏覽器送出後再 Enter...")
    input()

# ── 主程式 ──────────────────────────────────────────────────────────────────────

async def main(form_type, notice_path):
    data = parse_notice(notice_path)
    print(f"\n📄  Notice: {notice_path}")
    print(f"    Domain:  {data['domain']}")
    print(f"    URLs:    {len(data['infringing_urls'])} 個侵權連結")

    async with async_playwright() as p:
        # 用真實 Chrome（避開 Cloudflare bot 偵測）
        browser = await p.chromium.launch(
            channel='chrome',
            headless=False,
            slow_mo=200,
        )
        page = await browser.new_page()

        if form_type == 'cloudflare':
            await fill_cloudflare(page, data)
        else:
            print(f"❌  未知表單類型：{form_type}")

        await browser.close()


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('用法：python3 playwright_filler.py <cloudflare> <notice_file>')
        print('範例：python3 playwright_filler.py cloudflare notices/2026-05-30_pornone_com_cloudflare.txt')
        sys.exit(1)

    asyncio.run(main(sys.argv[1], sys.argv[2]))
