#!/usr/bin/env bash
# Stand-in deploy target: prints the steps a real deploy would take.
# Deliberately writes no files so the worktree digest stays stable.
set -euo pipefail

echo "→ Building release bundle..."
echo "→ Pushing image to registry..."
echo "→ Releasing to production..."
echo "✅ Deployed (stand-in)"
