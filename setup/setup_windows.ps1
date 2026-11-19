# One-time setup on Windows. Run from the repo folder:
#   powershell -ExecutionPolicy Bypass -File setup\setup_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
  Write-Host "Python isn't installed. Get it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run this again."
  exit 1
}
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip -q
.venv\Scripts\python -m pip install -r requirements.txt -q
.venv\Scripts\python tools\doctor.py
