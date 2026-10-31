@echo off
setlocal
cd /d "%~dp0.."
set PYTHONUTF8=1

echo ============================================================
echo   Build for Windows (uv only)
echo ============================================================

where uv >nul 2>nul
if errorlevel 1 goto no_uv

if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" goto build
where tesseract >nul 2>nul
if not errorlevel 1 goto build
where winget >nul 2>nul
if errorlevel 1 goto build
echo.
echo Tesseract not found, installing via winget (needed for scanned PDFs)...
winget install --id UB-Mannheim.TesseractOCR -e --silent --accept-package-agreements --accept-source-agreements

:build
echo.
echo Building. The first run downloads Python and libraries.
uv run --python 3.13 --extra dev python scripts\build.py
if errorlevel 1 goto failed

echo.
echo Done. Archive: dist\KRmanfi-Search-win64.zip
echo Run without unpacking: dist\KRmanfi-Search\KRmanfiSearch.exe
if not "%~1"=="--no-pause" pause
exit /b 0

:no_uv
echo.
echo [!] uv not found. Install it and run this file again:
echo     winget install --id astral-sh.uv -e
if not "%~1"=="--no-pause" pause
exit /b 1

:failed
echo.
echo [!] Build failed. See the error above.
if not "%~1"=="--no-pause" pause
exit /b 1
