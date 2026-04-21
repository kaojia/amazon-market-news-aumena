@echo off
chcp 65001 >nul
setlocal

:: 設定 Git 路徑
set "PATH=%LOCALAPPDATA%\Programs\Git\cmd;%PATH%"

:: 取得今天日期
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set dt=%%I
set TODAY=%dt:~0,4%-%dt:~4,2%-%dt:~6,2%

echo.
echo ========================================
echo   Amazon Market News - Auto Publish
echo ========================================
echo.

:: 檢查是否有新的日報檔案
git status --porcelain daily-report-*.html > nul 2>&1
set found=0
for /f "delims=" %%F in ('git status --porcelain daily-report-*.html 2^>nul') do set found=1

if %found%==0 (
    echo [!] 沒有偵測到新的日報檔案。
    echo     請先將 daily-report-YYYY-MM-DD.html 放入此資料夾。
    echo.
    pause
    exit /b
)

echo [1/4] 偵測到新日報檔案：
git status --short daily-report-*.html
echo.

echo [2/4] 加入 Git 並提交...
git add daily-report-*.html
git commit -m "Add daily report %TODAY%"
echo.

echo [3/4] 推送到 GitHub...
git push
echo.

echo [4/4] 完成！
echo.
echo     GitHub Actions 將自動執行：
echo       - 解析新日報內容
echo       - 更新 index.html
echo       - 部署到 GitHub Pages
echo.
echo     約 1-2 分鐘後網站自動更新：
echo     https://kaojia.github.io/amazon-market-news-aumena/
echo.
pause
