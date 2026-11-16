# Starts the WaitLess dev stack in three windows: API (:8000), worker, Angular (:4200).
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
# Prerequisites: PostgreSQL and Memurai services running, backend\.env filled in,
# `alembic upgrade head` already applied (see README).

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$python = Join-Path $backend '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) { Write-Error "Backend venv missing. Run the setup steps in README.md first."; exit 1 }
if (-not (Test-Path (Join-Path $backend '.env'))) { Write-Error "backend\.env missing. Copy backend\.env.example and fill DB_PASSWORD."; exit 1 }

Start-Process powershell -WorkingDirectory $backend -ArgumentList '-NoExit', '-Command', "& '$python' -m uvicorn app.main:app --reload --port 8000"
Start-Process powershell -WorkingDirectory $backend -ArgumentList '-NoExit', '-Command', "& '$python' -m app.worker"
Start-Process powershell -WorkingDirectory $frontend -ArgumentList '-NoExit', '-Command', 'npm start'

Write-Host "API      http://localhost:8000/api/docs"
Write-Host "Web      http://localhost:4200"
Write-Host "Status   http://localhost:4200/status"
