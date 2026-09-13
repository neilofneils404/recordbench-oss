#!/bin/sh
# Run only through the stopped-node installer import, on a networkless service.
set -eu
umask 077
database=${RECORDBENCH_SIGNATURE_DIR:-/var/lib/clamav}
source=${RECORDBENCH_SIGNATURE_SOURCE:-/recordbench-import}
helpers=${RECORDBENCH_ANTIVIRUS_HELPERS:-/opt/recordbench-antivirus}
stage=$(mktemp -d "$database/.recordbench-import.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
trap 'exit 1' HUP INT TERM
for name in main daily bytecode; do
    test -f "$source/$name.cvd" && test ! -L "$source/$name.cvd"
    cp -- "$source/$name.cvd" "$stage/$name.cvd"
    if ! sigtool --info "$stage/$name.cvd" >/dev/null 2>&1; then
        echo 'signature-import-verification-failed'
        exit 1
    fi
done
RECORDBENCH_SIGNATURE_DIR="$stage" sh "$helpers/signature-health.sh"
# Loading and scanning a harmless file verifies engine compatibility, not just headers.
printf '%s\n' 'RecordBench synthetic antivirus readiness sample.' > "$stage/sample.txt"
if ! clamscan --database="$stage" --no-summary "$stage/sample.txt" >/dev/null 2>&1; then
    echo 'signature-import-engine-load-failed'
    exit 1
fi
rm -- "$stage/sample.txt"
# An interruption during replacement blocks both updater and scanner health.
# Rerunning a fully validated import completes all three files before clearing it.
touch "$database/.recordbench-import-pending"
sync
for name in main daily bytecode; do
    chown clamav:clamav "$stage/$name.cvd"
    chmod 0644 "$stage/$name.cvd"
    mv -f -- "$stage/$name.cvd" "$database/$name.cvd"
    rm -f -- "$database/$name.cld"
done
sync
rm -- "$database/.recordbench-import-pending"
echo 'signature-import-complete'
