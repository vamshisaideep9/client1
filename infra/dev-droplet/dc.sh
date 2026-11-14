#!/usr/bin/env bash
# docker compose for the development droplet: base + dev overrides + droplet
# hardening, always in that order. Usage: infra/dev-droplet/dc.sh up -d
set -Eeuo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)

exec docker compose --project-directory "$root" \
  -f "$root/docker-compose.yml" \
  -f "$root/docker-compose.dev.yml" \
  -f "$root/infra/dev-droplet/compose.droplet.yml" \
  "$@"
