#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bash "$repo_dir/examples/arduino/build.sh"
exec ecw-ci run --config "$repo_dir/examples/arduino/run.toml" "$@"
