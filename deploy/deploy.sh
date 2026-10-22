#!/usr/bin/env bash
# Build the image for the server, ship it over SSH, and restart the bot.
#
#   deploy/deploy.sh [ssh-host]          # default host: aeza (from ~/.ssh/config)
#   ENV_FILE=1 deploy/deploy.sh          # also upload the local .env
#
# The server needs Docker with the compose plugin. No registry is involved:
# the image goes through `docker save | ssh docker load`.
set -euo pipefail

HOST="${1:-aeza}"
DIR="${REMOTE_DIR:-/opt/zvonilka}"
IMAGE="ghcr.io/telegins/zvonilka:latest"

cd "$(dirname "$0")/.."

arch=$(ssh "$HOST" uname -m)
case "$arch" in
  x86_64) platform=linux/amd64 ;;
  aarch64 | arm64) platform=linux/arm64 ;;
  *) echo "unsupported server architecture: $arch" >&2; exit 1 ;;
esac

echo "==> building $IMAGE for $platform"
docker buildx build --platform "$platform" -t "$IMAGE" --load .

echo "==> shipping the image to $HOST"
docker save "$IMAGE" | gzip | ssh "$HOST" 'gunzip | docker load'

echo "==> uploading compose.yaml"
ssh "$HOST" "mkdir -p '$DIR'"
scp -q compose.yaml "$HOST:$DIR/compose.yaml"

if [[ "${ENV_FILE:-0}" == 1 ]] || ! ssh "$HOST" "test -f '$DIR/.env'"; then
  echo "==> uploading .env"
  scp -q .env "$HOST:$DIR/.env"
  ssh "$HOST" "chmod 600 '$DIR/.env'"
fi

echo "==> restarting the bot"
ssh "$HOST" "cd '$DIR' && docker compose up -d --no-build --force-recreate && sleep 8 && docker compose logs --no-color --tail 5 bot"
