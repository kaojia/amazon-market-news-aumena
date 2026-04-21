# Amazon Market News AU/MENA

跨境電商情報站 — 自動彙整 AU / AE / SA 市場每日新聞

🔗 **網站：https://kaojia.github.io/amazon-market-news-aumena/**

---

## 網站功能

- 📰 每日新聞卡片，含摘要、Amazon 經營影響分析、Action 建議、原始來源連結
- 🏷️ 分類篩選：稅務、合規、總經、物流、貿易、地緣政治、平台
- 🔍 全文搜尋
- 📱 響應式設計（桌面 / 平板 / 手機）
- 📅 側邊欄：關鍵日期總覽 + Amazon AU/MENA 大促檔期

---

## 運作機制

```
daily-report-*.html  →  build.py  →  index.html  →  GitHub Pages
     (日報資料)          (解析注入)      (網站頁面)       (自動部署)
```

### 架構說明

| 檔案 | 用途 |
|------|------|
| `daily-report-YYYY-MM-DD.html` | 每日新聞日報（HTML 格式，含新聞卡片） |
| `index.html` | 網站主頁（模板 + 資料，由 build 腳本產生） |
| `scripts/build.py` | Python 建置腳本，掃描所有日報並注入資料到 index.html |
| `.github/workflows/build.yml` | GitHub Actions CI/CD，自動建置 + 部署 |

### 自動化流程

1. **新增日報**：將 `daily-report-YYYY-MM-DD.html` 放入 repo 根目錄
2. **Push 到 main**：`git add` → `git commit` → `git push`
3. **GitHub Actions 自動觸發**：
   - 執行 `python scripts/build.py`
   - 腳本掃描所有 `daily-report-*.html`，解析每張新聞卡片
   - 將解析結果（JSON）注入 `index.html` 的 `/*__ARTICLES_JSON__*/` 佔位符
   - 自動 commit 更新後的 `index.html`
   - 部署到 GitHub Pages

### build.py 解析邏輯

- 使用 Python 標準庫 `html.parser`（零依賴）
- 從每張 `.card` div 中提取：標題、摘要、影響分析、Action 建議、來源連結、優先級
- 自動對應分類標籤：

| 日報關鍵字 | 網站標籤 |
|-----------|---------|
| 供應鏈、物流 | 物流、地緣政治 |
| 總經、利率、消費 | 總經 |
| 稅務、VAT、電子發票 | 稅務 |
| 法規、消費者保護、AML | 合規 |
| 貿易、關稅 | 貿易 |
| 電商市場、競爭 | 平台 |

- 優先級顏色：🔴 high → `#dc2626`、🟡 medium → `#f59e0b`、🔵 default → `#0369a1`

---

## 本地開發

```bash
# 執行建置（需要 Python 3.x）
python scripts/build.py

# 預覽：直接用瀏覽器開啟 index.html
```

---

## 每日更新 Quick Start

```bash
# 1. 把新日報放進資料夾
# 2. 執行以下指令
git add daily-report-2026-XX-XX.html
git commit -m "Add daily report XX-XX"
git push

# GitHub Actions 會自動 build + 部署，約 1-2 分鐘後網站更新
```

---

> 此為內部參考資訊，由 AU/MENA 招商團隊整理。
