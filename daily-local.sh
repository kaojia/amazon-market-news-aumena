#!/usr/bin/env bash
#
# daily-local.sh — 本機每日補「真正的 Seller Central 官方公告」到 dashboard。
#
# 為什麼要本機跑：官方 /seller-news feed 需要 Midway 驗證，沒辦法在 GitHub
# Actions 雲端 runner 執行。CI 每天只會用外部 RSS 填 daily-report；這支腳本
# 在你本機把真正的 AE(UAE) + AU 官方公告疊上去（additive/idempotent，不會蓋掉
# CI 的外部卡片），再 build + push。
#
# 抓法（2026-09-30 起改為瀏覽器驅動）：inject_sc_news.py 透過 amz-chromebridge
# 操作你已登入的 Chrome，點 /seller-news 頁面右上角的國家下拉，輪流切到 AE 與
# AU 抓官方 feed。所以需要：Chrome 開著、裝了 amz-chromebridge 擴充、且已登入
# sellercentral.amazon.dev（Midway）。跨市場重複的全球公告會自動合併成 AE·AU。
#
# 用法：
#   ./daily-local.sh                 # 今天、AE+AU、每市場預設篇數
#   ./daily-local.sh --markets AU    # 只抓 AU
#   ./daily-local.sh --date 2026-09-15 --limit 8
#   後面的參數會原封不動傳給 inject_sc_news.py
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO"

# CJK 標題要 utf-8（見 memory: decliner pull gotchas）
export PYTHONIOENCODING=utf-8

echo "==> 1/4 Midway 驗證 (mwinit -f)"
if command -v mwinit >/dev/null 2>&1; then
  mwinit -f || echo "   ⚠️ mwinit 失敗；若既有憑證仍有效可忽略。記得讓 Chrome 也登入 sellercentral.amazon.dev。"
else
  echo "   ⚠️ 找不到 mwinit，跳過；假設既有 Midway 憑證仍有效。"
fi
echo "   （提醒：Chrome 需開著、裝了 amz-chromebridge 擴充、且已登入 sellercentral.amazon.dev）"

echo "==> 2/4 先同步遠端 (CI 每天也會 push)"
git pull --rebase --autostash

echo "==> 3/4 用瀏覽器抓官方公告(AE+AU)並注入 + rebuild (inject_sc_news.py)"
# 額外參數 ($@) 透傳，例如 --date / --limit / --markets
python scripts/inject_sc_news.py "$@"

echo "==> 4/4 commit & push"
git add daily-report-*.html index.html
if git diff --cached --quiet; then
  echo "   （無變更，略過 commit）"
else
  git commit -m "Local: SC 官方公告注入(AE+AU) $(date +%Y-%m-%d)"
  git push
  echo "   ✅ 已推送，GitHub Pages 幾分鐘內生效。"
fi
