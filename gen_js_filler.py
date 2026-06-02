#!/usr/bin/env python3
"""
JAOfilm DMCA JS Filler Generator
生成一段 JavaScript，貼到瀏覽器 Console 自動填表。

用法：
  python3 gen_js_filler.py cloudflare notices/2026-05-30_pornone_com_cloudflare.txt
"""

import sys
import re
import os
import subprocess

from config import COPYRIGHT_OWNER, BRAND_NAME, CONTACT_EMAIL, WEBSITE


def parse_notice(path):
    with open(path, encoding='utf-8') as f:
        text = f.read()

    all_urls = re.findall(r'https?://[^\s\n,]+', text)
    infringing = [u for u in all_urls
                  if 'jaofilm.com' not in u
                  and 'abuse.cloudflare.com' not in u
                  and 'support.google.com' not in u]

    m = re.search(r'at\s+([\w.-]+\.\w+)', text)
    domain = m.group(1) if m else 'unknown'

    return {
        'domain': domain,
        'infringing_urls': infringing,
    }


def gen_cloudflare_js(data):
    urls_str = r'\n'.join(data['infringing_urls'])
    desc = (
        f"Original audiovisual works produced exclusively by {BRAND_NAME} ({WEBSITE}). "
        f"The listed URLs distribute JAOfilm copyrighted content without any license or authorization. "
        f"These films are only available through official channels: fansone.co and onlyfans.com/jaofilm."
    )

    js = f"""
(function() {{
  // 填表函式：嘗試多種 selector
  function fill(selectors, value) {{
    for (var s of selectors) {{
      var el = document.querySelector(s);
      if (el) {{
        var nativeSetter = Object.getOwnPropertyDescriptor(
          el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
          'value'
        ).set;
        nativeSetter.call(el, value);
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return true;
      }}
    }}
    console.warn('找不到欄位:', selectors[0]);
    return false;
  }}

  // 姓名
  fill([
    'input[name*="name" i]',
    'input[placeholder*="name" i]',
    'input[id*="name" i]',
  ], {repr(COPYRIGHT_OWNER)});

  // Email
  fill([
    'input[type="email"]',
    'input[name*="email" i]',
    'input[placeholder*="email" i]',
  ], {repr(CONTACT_EMAIL)});

  // 公司
  fill([
    'input[name*="company" i]',
    'input[name*="org" i]',
    'input[placeholder*="company" i]',
    'input[placeholder*="organization" i]',
  ], {repr(BRAND_NAME)});

  // 侵權 URL
  fill([
    'textarea[name*="url" i]',
    'textarea[placeholder*="url" i]',
    'textarea[name*="infringing" i]',
    'textarea[id*="url" i]',
  ], {repr(chr(10).join(data['infringing_urls']))});

  // 著作說明
  fill([
    'textarea[name*="description" i]',
    'textarea[name*="original" i]',
    'textarea[name*="work" i]',
    'textarea[placeholder*="description" i]',
    'textarea[placeholder*="original" i]',
  ], {repr(desc)});

  // 數位簽名
  fill([
    'input[name*="signature" i]',
    'input[placeholder*="signature" i]',
    'input[id*="signature" i]',
    'input[name*="sign" i]',
  ], {repr(COPYRIGHT_OWNER)});

  // 勾選所有 checkbox
  document.querySelectorAll('input[type="checkbox"]').forEach(function(cb) {{
    if (!cb.checked) {{
      cb.click();
    }}
  }});

  console.log('✅ JAOfilm DMCA 填表完成！請確認後自己按送出。');
}})();
""".strip()
    return js


def main():
    if len(sys.argv) < 3:
        print('用法：python3 gen_js_filler.py <cloudflare> <notice_file>')
        sys.exit(1)

    form_type = sys.argv[1]
    notice_path = sys.argv[2]

    data = parse_notice(notice_path)

    print(f"\n📄  Notice: {notice_path}")
    print(f"    Domain : {data['domain']}")
    print(f"    URLs   : {len(data['infringing_urls'])} 個")

    if form_type == 'cloudflare':
        js = gen_cloudflare_js(data)
    else:
        print(f"❌  未知類型：{form_type}")
        sys.exit(1)

    # 複製到剪貼簿
    subprocess.run(['pbcopy'], input=js.encode())

    print(f"""
✅  JS 已複製到剪貼簿！

步驟：
  1. 用 Safari 或 Chrome 開啟 https://abuse.cloudflare.com/copyright
  2. 點下拉選單 → 選「Copyright Infringement」
  3. 等表單展開
  4. 按 ⌘+Option+J（Chrome）或 ⌘+Option+C（Safari）開 Console
  5. 貼上（⌘+V）→ 按 Enter
  6. 確認欄位 → 自己按送出

侵權 URL 清單（供對照）：""")
    for u in data['infringing_urls']:
        print(f"    {u}")
    print()


if __name__ == '__main__':
    main()
