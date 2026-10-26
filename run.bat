@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "KRmanfiSearch.exe" (
    start "" "KRmanfiSearch.exe" %*
    exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" (
    set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
    start "" ".venv\Scripts\pythonw.exe" -m krmanfi_search %*
    exit /b 0
)
echo Не найдены ни KRmanfiSearch.exe, ни .venv. Создайте окружение (см. README.md):
echo   python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
pause
exit /b 1
