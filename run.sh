#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# ./run.sh exec ollama ollama pull qwen3:8b 2>&1
docker compose -f deploy/docker/docker-compose.yml "${@:-up -d}"
