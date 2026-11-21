# Starts the test camera and watches it with the agent, with a live preview window (press q in it to stop).
$root = Split-Path $PSScriptRoot -Parent
& (Join-Path $PSScriptRoot 'start-test-camera.ps1')
Start-Sleep -Seconds 2
& (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $root 'run.py') --source rtsp://127.0.0.1:8554/cctv_sub --show --demo
& (Join-Path $PSScriptRoot 'stop-test-camera.ps1')
