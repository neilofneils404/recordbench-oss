#!/usr/bin/env bash
set -Eeuo pipefail
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/recordbench_backup.py" restore "$@"
