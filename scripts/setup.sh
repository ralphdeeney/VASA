#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null
command -v docker >/dev/null
uv sync --frozen
docker compose up -d --wait --wait-timeout 120
uv run --frozen alembic upgrade head
