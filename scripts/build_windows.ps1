# Сборка Windows-версии: окружение -> PyInstaller -> встроенный Tesseract -> архив -> проверки.
# Запуск из корня проекта в PowerShell:  powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
# Нужны: Python 3.13 (или uv) и Tesseract-OCR (winget install UB-Mannheim.TesseractOCR).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Команда завершилась с кодом ${LASTEXITCODE}: $Exe $Arguments" }
}

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Invoke-Checked uv @("sync", "--extra", "dev", "--frozen")
} else {
    Invoke-Checked python @("-m", "venv", ".venv")
    Invoke-Checked ".venv\Scripts\pip.exe" @("install", "-r", "requirements.txt", ".[dev]")
}
$py = ".venv\Scripts\python.exe"

if (-not (Get-Command tesseract -ErrorAction SilentlyContinue) -and
    -not (Test-Path "C:\Program Files\Tesseract-OCR\tesseract.exe")) {
    throw "Tesseract не установлен: winget install UB-Mannheim.TesseractOCR"
}

Invoke-Checked $py @("-m", "ruff", "check", "src", "tests", "scripts")
Invoke-Checked $py @("-m", "pytest")
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist) { Remove-Item -Recurse -Force dist }
Invoke-Checked $py @("-m", "PyInstaller", "--noconfirm", "--clean", "krmanfi_search.spec")
Invoke-Checked $py @("scripts\bundle_tesseract.py", "dist\KRmanfiSearch")
Invoke-Checked $py @("scripts\package.py")
Invoke-Checked $py @("scripts\smoke_test.py", "--exe", "dist\KRmanfi-TextSearch\KRmanfiSearch-console.exe", "--require-ocr")
Invoke-Checked $py @("scripts\make_source_zip.py")
Invoke-Checked $py @("scripts\check_release.py", "dist\KRmanfi-TextSearch-win64.zip", "dist\KRmanfi-TextSearch-source.zip")
Get-Content dist\SHA256SUMS.txt
