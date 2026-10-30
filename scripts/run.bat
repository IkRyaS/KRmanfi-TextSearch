@echo off
cd /d "%~dp0.."
where uv >nul 2>nul
if errorlevel 1 (
    echo uv not found: winget install --id astral-sh.uv -e
    pause
    exit /b 1
)
uv run --python 3.13 krmanfi-search %*
