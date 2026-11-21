# Turns design\cctv.mp4 into a fake CCTV camera on this laptop:
#   MediaMTX  = the RTSP server (what the camera's own recorder normally is)
#   FFmpeg    = plays the mp4 in a loop into it, as a main stream and a smaller sub-stream
# Then point the agent at   rtsp://127.0.0.1:8554/cctv_sub
$root = Split-Path $PSScriptRoot -Parent
$mtx = Join-Path $root 'tools\mediamtx\mediamtx.exe'
$ff = (Get-ChildItem (Join-Path $root 'tools\ffmpeg') -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName
$video = Join-Path (Split-Path $root -Parent) 'design\cctv.mp4'
foreach ($p in $mtx, $ff, $video) { if (-not (Test-Path $p)) { throw "Missing: $p" } }

& (Join-Path $PSScriptRoot 'stop-test-camera.ps1')
New-Item -ItemType Directory -Force (Join-Path $root 'out') | Out-Null
Start-Process $mtx -WorkingDirectory (Split-Path $mtx) -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'out\mediamtx.log')
Start-Sleep -Seconds 3
$args = @(
  '-hide_banner', '-loglevel', 'warning', '-re', '-stream_loop', '-1', '-i', $video, '-an',
  # main stream: as recorded
  '-map', '0:v', '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-g', '30',
  '-f', 'rtsp', '-rtsp_transport', 'tcp', 'rtsp://127.0.0.1:8554/cctv',
  # sub-stream: smaller and slower, like a real camera's second stream
  '-map', '0:v', '-vf', 'scale=640:360,fps=10', '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-g', '10',
  '-f', 'rtsp', '-rtsp_transport', 'tcp', 'rtsp://127.0.0.1:8554/cctv_sub'
)
Start-Process $ff -ArgumentList $args -WindowStyle Hidden -RedirectStandardError (Join-Path $root 'out\ffmpeg.log')
Write-Host 'Test camera running: rtsp://127.0.0.1:8554/cctv (main) and rtsp://127.0.0.1:8554/cctv_sub (sub-stream)'
