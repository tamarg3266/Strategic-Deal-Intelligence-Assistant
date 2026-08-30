#!/usr/bin/env bash
set -euo pipefail

python -m build
python -m pytest -q
python -m ruff check src tests scripts
deal-intel doctor --offline
