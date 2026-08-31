#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scratch="$(mktemp -d)"
cleanup() {
  rm -rf -- "$scratch"
}
trap cleanup EXIT

install -d -m 0700 \
  "$scratch/config" \
  "$scratch/secrets" \
  "$scratch/runtime" \
  "$scratch/matter-storage" \
  "$scratch/transcription" \
  "$scratch/state" \
  "$scratch/models" \
  "$scratch/tls"
install -m 0600 "$project_root/config/recordbench.env.example" "$scratch/config/recordbench.env"
install -m 0600 "$project_root/config/transcription.env.example" "$scratch/config/transcription.env"
for name in postgres-password postgres-dsn transcription-token kerberos-proxy-secret recordbench.keytab; do
  install -m 0600 /dev/null "$scratch/secrets/$name"
done
install -m 0600 /dev/null "$scratch/tls/tls.crt"
install -m 0600 /dev/null "$scratch/tls/tls.key"

export RECORDBENCH_CONFIG_ROOT="$scratch/config"
export RECORDBENCH_SECRETS_ROOT="$scratch/secrets"
export RECORDBENCH_RUNTIME_ROOT="$scratch/runtime"
export RECORDBENCH_STORAGE_ROOT="$scratch/matter-storage"
export RECORDBENCH_TRANSCRIPTION_ROOT="$scratch/transcription"
export RECORDBENCH_STATE_ROOT="$scratch/state"
export RECORDBENCH_MODEL_ROOT="$scratch/models"
export RECORDBENCH_TLS_CERT="$scratch/tls/tls.crt"
export RECORDBENCH_TLS_KEY="$scratch/tls/tls.key"

docker compose \
  --env-file "$project_root/.env.example" \
  -f "$project_root/compose.yaml" \
  config --quiet

RECORDBENCH_KERBEROS_PRINCIPAL=HTTP/recordbench.example.test@EXAMPLE.TEST \
docker compose \
  --env-file "$project_root/.env.example" \
  -f "$project_root/compose.yaml" \
  -f "$project_root/compose.kerberos.yaml" \
  config --quiet

printf 'Standard and Kerberos Compose graphs are valid.\n'
