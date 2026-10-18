#!/usr/bin/env bash
# Build the scraper image for the cluster (amd64) and push it to the homelab registry.
# Usage: ./scripts/build-push.sh [tag]     (default tag: git short sha; also pushes "latest")
# Env:   REGISTRY (default 192.168.1.41:30500)
set -euo pipefail
cd "$(dirname "$0")/.."
REGISTRY="${REGISTRY:-192.168.1.41:30500}"
IMAGE="$REGISTRY/google-health-scrapper"
TAG="${1:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"

docker buildx build --platform linux/amd64 \
  -t "$IMAGE:$TAG" -t "$IMAGE:latest" --push .
echo "Pushed $IMAGE:$TAG and $IMAGE:latest"
