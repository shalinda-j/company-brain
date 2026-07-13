#!/usr/bin/env bash
# ============================================================================
# Company Brain — back up the vault (source of truth) + audit log.
#
#   ./scripts/backup.sh [dest_dir]     # default dest: ./backups
#
# Produces backups/brain-backup-YYYYmmdd-HHMMSS.tar.gz and keeps only the
# newest $KEEP archives (default 7). Cron example (daily at 03:00):
#   0 3 * * * /opt/company-brain/scripts/backup.sh >> /var/log/brain-backup.log 2>&1
#
# Restore: untar into the data dir, then rebuild the index:
#   tar xzf backups/brain-backup-<stamp>.tar.gz -C data
#   make reindex
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

DATA_DIR="${BRAIN_DATA_DIR:-./data}"
DEST="${1:-./backups}"
KEEP="${KEEP:-7}"

if [ ! -d "$DATA_DIR/vault" ]; then
  echo "No vault at $DATA_DIR/vault — nothing to back up." >&2
  exit 1
fi

mkdir -p "$DEST"
STAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$DEST/brain-backup-$STAMP.tar.gz"

# The vault alone is enough to rebuild everything (Qdrant is a rebuildable
# index); audit.log preserves the who-did-what trail.
MEMBERS=(vault)
[ -f "$DATA_DIR/audit.log" ] && MEMBERS+=(audit.log)
tar czf "$ARCHIVE" -C "$DATA_DIR" "${MEMBERS[@]}"
echo "Wrote $ARCHIVE"

# Prune: keep only the newest $KEEP archives.
ls -1t "$DEST"/brain-backup-*.tar.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
