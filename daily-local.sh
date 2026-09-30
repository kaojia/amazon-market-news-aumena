#!/usr/bin/env bash
#
# daily-local.sh — 本機每日補「真正的 Seller Central 官方公告」到 dashboard。
#
# 為什麼要本機跑：amz-sc news list 打的是 Amazon 官方 /seller-news feed，
# 需要 Midway 驗證，沒辦法在 GitHub Actions 雲端 runner 執行。CI 每天只會用
# 外部 RSS 填 daily-report；這支腳本在你本機 mwinit 後，把真正的 AE 官方公告
# 疊上去（additive/idempotent，不會蓋掉 CI 的外部卡片），再 build + push。
#
# 用法：
#   ./daily-local.sh                 # 今天、AE、預設篇數
#   ./daily-local.sh --date 2026-09-15 --limit 8
#   後面的參數會原封不動傳給 inject_sc_news.py
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO"

# amz-sc 沒在 PATH 上，且 CJK 標題要 utf-8（見 memory: amz-sc PATH workaround / decliner pull gotchas）
SCRIPTS_DIR="$(python -c 'import site,os;print(os.path.join(site.USER_BASE,"Scripts"))')"
export PATH="$SCRIPTS_DIR:$PATH"
export PYTHONIOENCODING=utf-8

echo "==> 1/4 Midway 驗證 (mwinit -f)"
if command -v mwinit >/dev/null 2>&1; then
  mwinit -f || echo "   ⚠️ mwinit 失敗；若既有憑證仍有效可忽略，否則後面 amz-sc 會擋。"
else
  echo "   ⚠️ 找不到 mwinit，跳過；假設既有 Midway 憑證仍有效。"
fi

echo "==> 2/4 先同步遠端 (CI 每天也會 push)"
git pull --rebase --autostash

echo "==> 3/4 抓官方公告並注入 + rebuild (inject_sc_news.py)"
# 額外參數 ($@) 透傳，例如 --date / --limit / --marketplace / --mcid
python scripts/inject_sc_news.py "$@"

echo "==> 4/4 commit & push"
git add daily-report-*.html index.html
if git diff --cached --quiet; then
  echo "   （無變更，略過 commit）"
else
  git commit -m "Local: SC 官方公告注入 $(date +%Y-%m-%d)"
  git push
  echo "   ✅ 已推送，GitHub Pages 幾分鐘內生效。"
fi
