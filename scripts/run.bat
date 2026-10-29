@echo off
chcp 65001 >nul
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
    echo Не найден uv: winget install --id astral-sh.uv -e
    pause
    exit /b 1
)
uv run krmanfi-search %*
