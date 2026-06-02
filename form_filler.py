#!/usr/bin/env python3
"""
JAOfilm DMCA Form Filler — Claude Computer Use
自動填寫 Cloudflare / Twitter DMCA 表單，填完停下來等你按送出。

用法：
  python3 form_filler.py cloudflare notices/2026-05-30_pornone_com_cloudflare.txt
  python3 form_filler.py twitter notices/2026-05-30_xxx_twitter.txt
"""

import sys
import os
import time
import base64
import subprocess
import anthropic

# ── 設定 ──────────────────────────────────────────────────────────────────────

FORM_URLS = {
    "cloudflare": "https://abuse.cloudflare.com/copyright",
    "twitter":    "https://help.twitter.com/forms/dmca",
}

MODEL = "claude-opus-4-8"
BETA  = "computer-use-2024-10-22"

# ── Screenshot ────────────────────────────────────────────────────────────────

def screenshot() -> str:
    """Take screenshot, return base64 PNG."""
    path = "/tmp/cu_shot.png"
    subprocess.run(["screencapture", "-x", "-t", "png", path], check=True)
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode()

# ── Mouse / Keyboard ──────────────────────────────────────────────────────────

import pyautogui
pyautogui.FAILSAFE = True
pyautogui.PAUSE    = 0.4

KEY_MAP = {
    "Return": "enter", "Tab": "tab", "Escape": "esc",
    "BackSpace": "backspace", "Delete": "delete",
    "space": "space", "ctrl+a": ["ctrl", "a"],
}

def do_action(action: dict):
    t = action.get("action") or action.get("type")
    coord = action.get("coordinate", [0, 0])
    x, y  = coord[0], coord[1]

    if t == "screenshot":
        return screenshot()
    elif t == "mouse_move":
        pyautogui.moveTo(x, y, duration=0.25)
    elif t == "left_click":
        pyautogui.click(x, y)
    elif t == "left_click_drag":
        sx, sy = action.get("start_coordinate", coord)
        pyautogui.mouseDown(sx, sy); time.sleep(0.1)
        pyautogui.moveTo(x, y, duration=0.4); pyautogui.mouseUp()
    elif t == "double_click":
        pyautogui.doubleClick(x, y)
    elif t == "right_click":
        pyautogui.rightClick(x, y)
    elif t == "middle_click":
        pyautogui.middleClick(x, y)
    elif t == "type":
        text = action.get("text", "")
        pyautogui.write(text, interval=0.04)
    elif t == "key":
        key = action.get("key", "")
        mapped = KEY_MAP.get(key, key)
        if isinstance(mapped, list):
            pyautogui.hotkey(*mapped)
        else:
            pyautogui.press(mapped)
    elif t == "scroll":
        pyautogui.moveTo(x, y)
        direction = action.get("direction", "down")
        amount    = action.get("amount", 3)
        pyautogui.scroll(-amount if direction == "down" else amount)

    time.sleep(0.3)
    return screenshot()   # 每個動作後截圖回傳

# ── Computer Use loop ─────────────────────────────────────────────────────────

def run(form_type: str, notice_path: str):
    if form_type not in FORM_URLS:
        print(f"❌ 未知表單類型：{form_type}（可用：{list(FORM_URLS)}）")
        sys.exit(1)

    with open(notice_path, encoding="utf-8") as f:
        notice = f.read()

    url = FORM_URLS[form_type]
    w, h = pyautogui.size()

    print(f"\n🤖  Claude Computer Use 啟動")
    print(f"    表單：{form_type.upper()} → {url}")
    print(f"    Notice：{notice_path}")
    print(f"    螢幕：{w}×{h}")
    print(f"\n⚠️   請把 Chrome/Safari 放到前景，填表期間不要碰滑鼠鍵盤")
    print(f"    Ctrl+C 可隨時中止\n")
    time.sleep(4)

    # 開瀏覽器
    subprocess.run(["open", url])
    time.sleep(3)

    client = anthropic.Anthropic()

    system_prompt = """You are a precise form-filling assistant. Your job is to fill out DMCA takedown forms accurately using the provided notice information.

Rules:
- ALWAYS take a screenshot first to see the current state of the page
- If there is a dropdown to choose an abuse type, select "Copyright Infringement" or "Copyright / DMCA" or the closest copyright option
- Wait for the form fields to appear after selecting the abuse type, then fill every required field
- For "Digital signature" or "Your name" fields, type: JAO
- For email fields, use: info@jaofilm.com
- Check all acknowledgment/agreement checkboxes
- NEVER click Submit, Send, or any final submission button
- Keep taking screenshots and acting until ALL visible fields are filled
- Only say "FORM_COMPLETE" when every field on the page is filled and you are confident nothing is missing
- If you encounter a CAPTCHA, say "CAPTCHA_DETECTED" and stop
- Do not stop early — keep using the computer tool until the form is truly complete"""

    user_prompt = f"""Please fill out this {form_type.upper()} DMCA abuse form.

The browser is already open. Take a screenshot first to see the current state.

Use this notice information to fill the form:

{notice}

Remember: Fill everything but DO NOT submit. Say FORM_COMPLETE when done."""

    messages = [{"role": "user", "content": user_prompt}]

    tools = [{
        "type": "computer_20241022",
        "name": "computer",
        "display_width_px":  w,
        "display_height_px": h,
    }]

    iteration = 0
    max_iter  = 60

    while iteration < max_iter:
        iteration += 1
        print(f"  [{iteration:02d}] 思考中...", end="\r")

        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=tools,
            messages=messages,
            betas=[BETA],
        )

        # 印出文字回應
        text_parts = [b.text for b in resp.content if hasattr(b, "text") and b.text]
        if text_parts:
            msg = " ".join(text_parts)
            print(f"  [{iteration:02d}] {msg[:120]}")
            if "FORM_COMPLETE" in msg:
                print("\n✅  Claude 填完了！請確認表單內容後自己按送出。")
                break
            if "CAPTCHA_DETECTED" in msg:
                print("\n⚠️  遇到 CAPTCHA，請手動處理後繼續。")
                break

        # 只有在沒有任何 tool_use 時才視為真正結束
        has_tool_use = any(b.type == "tool_use" for b in resp.content)
        if resp.stop_reason == "end_turn" and not has_tool_use:
            print("\n⚠️  Claude 停止但未完成表單，請手動確認。")
            break

        # 處理 tool_use
        tool_results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            action = block.input
            action_t = action.get("action", "")
            print(f"  [{iteration:02d}] {action_t} {action.get('coordinate','')}", end="")

            shot_b64 = do_action(action)
            print("  📸")

            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": block.id,
                "content": [{
                    "type":   "image",
                    "source": {
                        "type":       "base64",
                        "media_type": "image/png",
                        "data":       shot_b64,
                    }
                }]
            })

        if not tool_results:
            break

        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user",      "content": tool_results})

    else:
        print("\n⚠️  超過最大迭代次數，請手動確認表單狀態。")


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法：python3 form_filler.py <cloudflare|twitter> <notice_file>")
        print("範例：python3 form_filler.py cloudflare notices/2026-05-30_pornone_com_cloudflare.txt")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌  需要 ANTHROPIC_API_KEY 環境變數")
        print("    執行：export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    run(sys.argv[1], sys.argv[2])
