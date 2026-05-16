#!/usr/bin/env bash
# Run the Chewy TUI test harness inside a clean Alpine container.
# Builds the binary fresh for linux/amd64 so we test the actual artifact
# under a stock terminal, not the host's iTerm2.
set -euo pipefail

cd "$(dirname "$0")/.."

docker run --rm \
  -v "$PWD":/work \
  -w /work/tui \
  -e CGO_ENABLED=0 \
  -e GOTOOLCHAIN=auto \
  golang:alpine \
  sh -c '
    set -eu
    apk add --no-cache util-linux >/dev/null
    go build -o /work/bin/sweep-tui-linux .
    BIN=/work/bin/sweep-tui-linux sh ./test-chewy.sh
  '
