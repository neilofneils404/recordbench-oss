#!/bin/sh
# FreshClam validates downloaded databases; offline imports verify signed CVDs.
# Freshness comes from the database header, never a copied file's modification time.
set -eu
database=${RECORDBENCH_SIGNATURE_DIR:-/var/lib/clamav}
if [ -e "$database/.recordbench-import-pending" ]; then
    echo 'signature-import-incomplete'
    exit 1
fi
if ! { [ -s "$database/main.cvd" ] || [ -s "$database/main.cld" ]; }; then
    echo 'signature-main-missing'
    exit 1
fi
now=$(date +%s)
for suffix in cvd cld; do
    candidate="$database/daily.$suffix"
    [ -f "$candidate" ] && [ ! -L "$candidate" ] || continue
    # The ninth field of a ClamAV CVD/CLD header is its build epoch.
    header=$(dd if="$candidate" bs=512 count=1 2>/dev/null)
    case "$header" in ClamAV-VDB:*) ;; *) continue ;; esac
    built=$(printf '%s' "$header" | awk -F: 'NF == 9 {gsub(/ +$/, "", $9); print $9}')
    case "$built" in ''|*[!0-9]*) continue ;; esac
    [ ${#built} -le 10 ] || continue
    if [ "$built" -le "$((now + 300))" ] && [ "$built" -ge "$((now - 259200))" ]; then
        echo 'signatures-fresh'
        exit 0
    fi
done
echo 'signature-daily-missing-invalid-or-stale'
exit 1
