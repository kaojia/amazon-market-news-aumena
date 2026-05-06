# AU/MENA 跨境電商日報工作流

## 整體流程圖

```
排程提醒 (09:00)
    ↓
在 Kiro 中搜尋新聞 & 產生日報 HTML
    ↓
daily-report-YYYY-MM-DD.html 存入 repo 根目錄
    ↓
┌─────────────────────────────────────────────┐
│  路徑 A：發送 Email                          │
│  generate-eml.ps1 → .eml → Outlook 寄出     │
└─────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────┐
│  路徑 B：發佈到網站                          │
│  publish.bat (或手動 git push)               │
│      ↓                                      │
│  GitHub Actions 自動觸發                     │
│      ↓                                      │
│  build.py 解析所有日報 → 注入 index.html     │
│      ↓                                      │
│  部署到 GitHub Pages                         │
└─────────────────────────────────────────────┘
```

---

## 步驟詳解

### 1. 排程提醒

- **工具**：Windows Task Scheduler
- **腳本**：`scripts/setup-task-scheduler.ps1`（需管理員權限執行一次）
- **觸發時間**：
  - 日報：週一～週五 09:00
  - 週報：每週五 16:00
- **行為**：彈出提醒視窗，提示在 Kiro 中產生日報

### 2. 產生日報 HTML

- **工具**：Kiro（手動操作）
- **輸出**：`daily-report-YYYY-MM-DD.html`，存放於 repo 根目錄
- **格式要求**：
  - 每則新聞為一個 `.card` div
  - 包含 `.region`、`.summary`、`.impact`、`.action`、`.source` 子區塊
  - 可加上 `.high` 或 `.medium` class 標示優先級

### 3. 寄送 Email

有兩種方式：

#### 方式 A：產生 .eml 檔案

```powershell
powershell scripts\generate-eml.ps1 -HtmlPath daily-report-YYYY-MM-DD.html -Type daily -OpenOutlook
```

- 產生 RFC 2822 格式的 `.eml` 檔案
- 加上 `-OpenOutlook` 會自動開啟 Outlook 草稿

#### 方式 B：直接透過 Outlook 寄出

```powershell
# 開啟草稿確認
powershell scripts\send-via-outlook.ps1 -HtmlPath daily-report-YYYY-MM-DD.html -Type daily

# 直接寄出
powershell scripts\send-via-outlook.ps1 -HtmlPath daily-report-YYYY-MM-DD.html -Type daily -Send
```

### 4. 發佈到網站

#### 方式 A：使用 publish.bat（推薦）

```cmd
publish.bat
```

自動偵測新日報 → git add → commit → push

#### 方式 B：手動 Git 操作

```bash
git add daily-report-YYYY-MM-DD.html
git commit -m "Add daily report YYYY-MM-DD"
git push
```

### 5. 自動建置 & 部署（GitHub Actions）

Push 到 main 後自動觸發：

1. `build.py` 掃描所有 `daily-report-*.html`
2. 解析每張新聞卡片，提取標題、摘要、影響分析、Action 建議、來源
3. 自動分類標籤（物流、總經、稅務、合規、貿易、平台）
4. 產生 JSON 注入 `index.html`
5. Commit 更新後的 `index.html`
6. 部署到 GitHub Pages

---

## 收件人設定

| 類型 | 收件人 |
|------|--------|
| 日報 | eddiechu, chiawenk, jerrykan, yachilin, tobchen @amazon.com |
| 週報 | twgs@amazon.com（賣家收件人待補充） |

---

## 分類對應表

| 日報關鍵字 | 網站標籤 |
|-----------|---------|
| 供應鏈、物流 | 物流、地緣政治 |
| 總經、利率、消費 | 總經 |
| 稅務、VAT、電子發票 | 稅務 |
| 法規、消費者保護、AML | 合規 |
| 貿易、關稅 | 貿易 |
| 電商市場、競爭 | 平台 |

---

## 優先級顏色

| 優先級 | 顏色 | CSS class |
|--------|------|-----------|
| 🔴 高 | `#dc2626` | `.high` |
| 🟡 中 | `#f59e0b` | `.medium` |
| 🔵 一般 | `#0369a1` | （預設） |

---

## 關鍵檔案一覽

| 檔案 | 用途 |
|------|------|
| `scripts/setup-task-scheduler.ps1` | 設定 Windows 排程提醒（執行一次） |
| `scripts/generate-eml.ps1` | HTML → .eml 轉換 + 可選開啟 Outlook |
| `scripts/send-via-outlook.ps1` | 透過 Outlook COM 直接寄出或開草稿 |
| `publish.bat` | 一鍵 git add / commit / push |
| `scripts/build.py` | 解析日報 HTML → JSON → 注入 index.html |
| `.github/workflows/build.yml` | CI/CD 自動建置 + 部署 GitHub Pages |
| `index.html` | 網站主頁模板 |
| `daily-report-*.html` | 每日新聞日報資料檔 |

---

## 環境需求

- **Python 3.x**：執行 `build.py`（本地測試用，CI 環境已自動安裝）
- **Git**：版本控制 & 推送
- **Windows + Outlook**：Email 寄送功能（僅本機需要）
- **GitHub Pages**：網站託管（已設定）

---

## 每日 Quick Start

```powershell
# 1. 在 Kiro 中產生今日日報 HTML

# 2. 寄送 Email
powershell scripts\generate-eml.ps1 -HtmlPath daily-report-2026-05-06.html -Type daily -OpenOutlook

# 3. 發佈到網站
.\publish.bat
# 或
git add daily-report-2026-05-06.html
git commit -m "Add daily report 2026-05-06"
git push

# 約 1-2 分鐘後網站自動更新：
# https://kaojia.github.io/amazon-market-news-aumena/
```
