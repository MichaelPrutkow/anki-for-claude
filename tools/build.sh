#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

V=$(python3 -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
MV=$(python3 -c "import json;print(json.load(open('manifest.json'))['version'])")
[ "$V" = "$MV" ] || { echo "Version-Drift: pyproject=$V manifest=$MV"; exit 1; }

uv run ruff check src/
uv run ruff format --check src/
uv run python -c "import anki_mcp.server"        # faengt Import-Fehler vor dem Bauen

rm -rf bundle && mkdir -p bundle
cp -R src pyproject.toml uv.lock README.md LICENSE icon.png manifest.json bundle/
find bundle \( -name '__pycache__' -o -name '.DS_Store' -o -name '*.pyc' \) -prune -exec rm -rf {} +

diff -r src bundle/src -x '.DS_Store' -x '__pycache__' >/dev/null \
  || { echo "bundle/src weicht von src ab"; exit 1; }

npx --yes @anthropic-ai/mcpb@2.1.2 pack bundle "anki-mcp-server-${V}.mcpb"
echo "gebaut: anki-mcp-server-${V}.mcpb"