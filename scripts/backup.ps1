<#
.SYNOPSIS
  Backs up the local WaitLess development database (and uploaded files) to .\backups.

.EXAMPLE
  .\scripts\backup.ps1            # database + uploads, keeps the last 10 backups
  .\scripts\backup.ps1 -Restore .\backups\db-20261117-180000.dump

  Production backups run in the `backup` container (infra/backup/backup.sh); see docs/09-deployment.md.
#>
param(
  [string]$Restore = "",
  [int]$Keep = 10
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root "backend\.env"
$vars = @{}
Get-Content $envFile | Where-Object { $_ -match '^\s*([A-Z_]+)\s*=\s*(.*)$' } | ForEach-Object {
  $vars[$Matches[1]] = $Matches[2].Trim().Trim('"')
}
$dbHost = if ($vars.DB_HOST) { $vars.DB_HOST } else { "localhost" }
$port = if ($vars.DB_PORT) { $vars.DB_PORT } else { "5432" }
$db = if ($vars.DB_NAME) { $vars.DB_NAME } else { "waitless" }
$user = if ($vars.DB_MIGRATION_USER) { $vars.DB_MIGRATION_USER } else { "postgres" }
$env:PGPASSWORD = $vars.DB_MIGRATION_PASSWORD

$bin = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\pg_dump.exe" -ErrorAction SilentlyContinue |
  Sort-Object FullName -Descending | Select-Object -First 1
if (-not $bin) { throw "pg_dump.exe not found under C:\Program Files\PostgreSQL\<version>\bin" }
$pgDir = Split-Path $bin.FullName

if ($Restore) {
  Write-Host "Restoring $Restore into $db (existing objects are replaced)..."
  & (Join-Path $pgDir "pg_restore.exe") -h $dbHost -p $port -U $user -d $db --clean --if-exists --no-owner $Restore
  if ($LASTEXITCODE -ne 0) { throw "pg_restore failed" }
  Write-Host "Restored. Run 'alembic upgrade head' if the backup is from an older version."
  exit 0
}

$dir = Join-Path $root "backups"
New-Item -ItemType Directory -Force $dir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$file = Join-Path $dir "db-$stamp.dump"
& $bin.FullName -h $dbHost -p $port -U $user -d $db -Fc -Z 6 -f $file
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }
$uploads = Join-Path $root "backend\uploads"
if ((Test-Path $uploads) -and (Get-ChildItem $uploads -Recurse -File | Select-Object -First 1)) {
  Compress-Archive -Path (Join-Path $uploads "*") -DestinationPath (Join-Path $dir "media-$stamp.zip") -Force
}
Get-ChildItem $dir -Filter "db-*.dump" | Sort-Object Name -Descending | Select-Object -Skip $Keep | Remove-Item -Confirm:$false
Get-ChildItem $dir -Filter "media-*.zip" | Sort-Object Name -Descending | Select-Object -Skip $Keep | Remove-Item -Confirm:$false
Write-Host ("Backup written: {0} ({1:N1} MB)" -f $file, ((Get-Item $file).Length / 1MB))
