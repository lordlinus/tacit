#!/usr/bin/env bash
# Vendor the core package into the Functions app before packaging.
# (Remote build installs requirements.txt only; local path deps don't survive
# the zip, so the package is copied in. Run by azd's prepackage hook.)
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
rm -rf "$repo_root/functions/foundry_memory"
cp -r "$repo_root/src/foundry_memory" "$repo_root/functions/foundry_memory"
echo "synced src/foundry_memory -> functions/foundry_memory"
