#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
command -v arduino-cli >/dev/null || {
  echo "Install Arduino CLI 1.3.1 before building (see README.md)." >&2
  exit 1
}
arduino-cli core update-index
arduino-cli core install arduino:renesas_uno@1.6.0
mkdir -p "$repo_dir/build"
arduino-cli compile \
  --fqbn arduino:renesas_uno:unor4wifi \
  --output-dir "$repo_dir/build" \
  "$repo_dir/examples/arduino/arduino_ci_bench"
test -s "$repo_dir/build/arduino_ci_bench.ino.bin"
