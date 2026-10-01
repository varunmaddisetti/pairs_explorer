# One-command local demo for Windows PowerShell (synthetic data, no keys).
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
if (Get-Command uv -ErrorAction SilentlyContinue) {
  uv sync --python 3.12 --quiet
  uv run --python 3.12 python scripts/launcher.py @args
  exit $LASTEXITCODE
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  py -3.12 -m venv .venv
  .\.venv\Scripts\pip.exe install --quiet -r requirements.lock
}
.\.venv\Scripts\python.exe scripts\launcher.py @args
