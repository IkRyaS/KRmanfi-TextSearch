@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
set PYTHONUTF8=1

echo ============================================================
echo   Сборка "Поиск по документам" для Windows (только uv)
echo ============================================================

where uv >nul 2>nul
if errorlevel 1 goto no_uv

if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" goto build
where tesseract >nul 2>nul
if not errorlevel 1 goto build
where winget >nul 2>nul
if errorlevel 1 goto build
echo.
echo Tesseract не найден, пробую установить через winget (нужен для распознавания сканов)...
winget install --id UB-Mannheim.TesseractOCR -e --silent --accept-package-agreements --accept-source-agreements

:build
echo.
echo Подготовка окружения и сборка. Первый запуск скачивает Python и библиотеки.
uv run --extra dev python scripts\build.py
if errorlevel 1 goto failed

echo.
echo Готово. Архив лежит в папке dist. Для запуска откройте dist\KRmanfi-Search\KRmanfiSearch.exe
if not "%1"=="--no-pause" pause
exit /b 0

:no_uv
echo.
echo [!] Не найден uv. Установите его одной командой и запустите этот файл снова:
echo     winget install --id astral-sh.uv -e
echo     или см. https://docs.astral.sh/uv/getting-started/installation/
if not "%1"=="--no-pause" pause
exit /b 1

:failed
echo.
echo [!] Сборка не удалась. Причина указана выше.
if not "%1"=="--no-pause" pause
exit /b 1
