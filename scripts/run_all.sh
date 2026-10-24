#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

.venv/bin/python scripts/fetch_cpi.py
.venv/bin/python scripts/fetch_brickranker.py
.venv/bin/python scripts/build_dataset.py \
  --input data/raw/brickranker.json \
  --prices-dir data/raw/brickranker_prices
.venv/bin/python scripts/validate.py
