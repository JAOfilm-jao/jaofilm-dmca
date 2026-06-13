#!/bin/bash
# 開啟 @jaofilm_DMCA 專用 Chrome（remote debugging 模式）
# user-data-dir：~/.jaofilm-dmca-chrome（獨立 profile，與個人 Chrome 互不干擾）
#
# 首次使用前：
#   1. 執行此腳本開啟 Chrome
#   2. 登入 Twitter/X → @jaofilm_DMCA（使用 dmca@jaofilm.com 帳號）
#   3. 之後每次填表前直接跑此腳本，Chrome 會記住登入狀態
#
# 注意：此 Chrome 視窗必須保持開著，才能讓 twitter_dmca.py 連線

pkill -x "Google Chrome" 2>/dev/null
sleep 1

/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.jaofilm-dmca-chrome" \
  --profile-directory="Default" \
  "https://x.com" \
  &

echo "✅ Chrome（Wilson DMCA）已開啟（port 9222）"
echo ""
echo "   user-data-dir: ~/.jaofilm-dmca-chrome（從 Profile 13 複製 session）"
echo "   請確認 Twitter 已登入 @jaofilm_DMCA，然後再按填表"
echo ""
echo "   驗證連線：curl -s http://127.0.0.1:9222/json/version | python3 -m json.tool"
