#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --frozen python scripts/prepare_evolution.py "$@"
docker compose --profile calling build evolution
docker compose --profile calling up -d --wait --wait-timeout 120
uv run --frozen python scripts/evolution_status.py
