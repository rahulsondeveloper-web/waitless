#!/bin/sh
# Nightly WaitLess backup (Phase 12): PostgreSQL (custom format, compressed) + uploaded media (local storage).
# Keeps BACKUP_KEEP_DAYS days locally; copies to S3 when BACKUP_S3_URI is set (e.g. s3://waitless-backups/prod).
#
# Restore (see docs/09-deployment.md):
#   pg_restore --clean --if-exists --no-owner -d "$DB_NAME" /backups/db-YYYYMMDD-HHMMSS.dump
set -eu

: "${DB_HOST:?}" "${DB_NAME:=waitless}" "${DB_MIGRATION_USER:?}" "${DB_MIGRATION_PASSWORD:?}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP="${BACKUP_KEEP_DAYS:-14}"
AT="${BACKUP_AT:-02:30}"   # local time of the nightly run
export PGPASSWORD="$DB_MIGRATION_PASSWORD"

run_backup() {
  stamp=$(date +%Y%m%d-%H%M%S)
  db="$BACKUP_DIR/db-$stamp.dump"
  echo "backup: starting $stamp"
  pg_dump -h "$DB_HOST" -U "$DB_MIGRATION_USER" -d "$DB_NAME" -Fc -Z 6 -f "$db.partial"
  mv "$db.partial" "$db"
  pg_restore --list "$db" > /dev/null   # the file is a readable archive
  if [ -d /uploads ] && [ "$(ls -A /uploads 2>/dev/null)" ]; then
    tar -czf "$BACKUP_DIR/media-$stamp.tar.gz" -C /uploads .
  fi
  if [ -n "${BACKUP_S3_URI:-}" ]; then
    aws s3 cp "$db" "$BACKUP_S3_URI/" --only-show-errors
    [ -f "$BACKUP_DIR/media-$stamp.tar.gz" ] && aws s3 cp "$BACKUP_DIR/media-$stamp.tar.gz" "$BACKUP_S3_URI/" --only-show-errors
  fi
  find "$BACKUP_DIR" -name 'db-*.dump' -mtime +"$KEEP" -delete
  find "$BACKUP_DIR" -name 'media-*.tar.gz' -mtime +"$KEEP" -delete
  echo "backup: done $(du -h "$db" | cut -f1) -> $db"
}

if [ "${1:-}" = "once" ]; then
  run_backup
  exit 0
fi

mkdir -p "$BACKUP_DIR"
while :; do
  now=$(date +%s)
  next=$(date -d "today $AT" +%s 2>/dev/null || date -d "$AT" +%s)
  [ "$next" -le "$now" ] && next=$((next + 86400))
  sleep $((next - now))
  run_backup || echo "backup: FAILED" >&2
done
