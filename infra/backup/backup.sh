#!/usr/bin/env bash
# PandaTrack A/B 库每日备份（P5 运维）。
# 产出: ~/pandatrack-backups/YYYYMMDD_HHMMSS_{a,b}.sql.gz
# 保留: 默认 14 天（PT_BACKUP_KEEP_DAYS 可覆盖）。
# 由 systemd pandatrack-backup.timer 每日 03:30 触发；
# 手工执行: bash infra/backup/backup.sh
set -euo pipefail

BACKUP_DIR="${PT_BACKUP_DIR:-$HOME/pandatrack-backups}"
KEEP_DAYS="${PT_BACKUP_KEEP_DAYS:-14}"
ENV_FILE="${PT_PANDATRACK_ENV:-$HOME/pandatrack/.env}"

mkdir -p "$BACKUP_DIR"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

STAMP="$(date +%Y%m%d_%H%M%S)"
DATABASE_A_URL="${DATABASE_A_URL:?DATABASE_A_URL 未配置}"
DATABASE_B_URL="${DATABASE_B_URL:?DATABASE_B_URL 未配置}"

for pair in "a:$DATABASE_A_URL" "b:$DATABASE_B_URL"; do
  db="${pair%%:*}"
  url="${pair#*:}"
  out="$BACKUP_DIR/${STAMP}_${db}.sql.gz"
  pg_dump --no-owner --no-privileges "$url" | gzip -9 > "$out"
  echo "backup ${db} -> ${out} ($(du -h "$out" | cut -f1))"
done

# 过期清理：只删本脚本命名模式的旧归档，不动其他文件。
find "$BACKUP_DIR" -name '[0-9]*_[ab].sql.gz' -mtime "+$KEEP_DAYS" -delete
echo "backup done, kept <=${KEEP_DAYS}d in $BACKUP_DIR"
