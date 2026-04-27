#!/usr/bin/env bash
# Re-pull tokens.css from AbstractNucleus/design.
# Run when the upstream tokens are updated and you want mcontrol to track.

set -euo pipefail

cd "$(dirname "$0")/.."

gh api repos/AbstractNucleus/design/contents/tokens.css --jq .content \
    | base64 -d \
    > src/mcontrol/static/tokens.css

echo "Synced tokens.css ($(wc -l < src/mcontrol/static/tokens.css) lines)"
