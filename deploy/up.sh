#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(id -u)" == 0 ]]; then
  echo "Run deployment as the existing rootless Docker user, not root." >&2
  exit 1
fi
command -v uv >/dev/null
command -v docker >/dev/null
command -v git >/dev/null
command -v patch >/dev/null
vasa_security_options=$(docker info --format '{{json .SecurityOptions}}')
if [[ "$vasa_security_options" != *'"name=rootless"'* ]]; then
  echo "The selected Docker daemon is not rootless; use the existing rootless context." >&2
  exit 1
fi
uv sync --frozen
uv run --frozen python scripts/prepare_vps.py --check-ports
uv run --frozen python scripts/prepare_evolution.py
compose=(docker compose --env-file .local/vps.env -f deploy/compose.yaml)
"${compose[@]}" config --quiet
"${compose[@]}" build
"${compose[@]}" run --rm --no-deps vasa python scripts/prepare_speech.py
"${compose[@]}" run --rm --no-deps vasa python scripts/prepare_knowledge.py
"${compose[@]}" up -d --wait --wait-timeout 120 postgres redis evolution
"${compose[@]}" run --rm --no-deps vasa alembic upgrade head
"${compose[@]}" up -d --wait --wait-timeout 120 vasa
"${compose[@]}" exec -T vasa python scripts/evolution_status.py
if [[ "${VASA_START_VOICE:-0}" == 1 ]]; then
  "${compose[@]}" --profile voice up -d voice
fi
echo "Dedicated deployment started. Vendor activation, pairing and real calls are separate gates."
