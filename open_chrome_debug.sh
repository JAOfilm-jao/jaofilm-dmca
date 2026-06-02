#!/bin/bash
# 關閉現有 Chrome，用 remote debugging 模式重開
# 只需要做一次，之後這個視窗保持開著

pkill -x "Google Chrome" 2>/dev/null
sleep 1

/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --profile-directory="Default" \
  &

echo "✅ Chrome 已用 debug 模式開啟（port 9222）"
echo "   請在 Chrome 確認 Google 已登入，然後再跑 browser_filler.py"
