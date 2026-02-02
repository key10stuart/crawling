#!/usr/bin/env bash
set -euo pipefail

DATE="$(date +%F)"
JOBS="${JOBS:-4}"
DEPTH="${DEPTH:-2}"
LIMIT="${LIMIT:-60}"

PROFILE="comp_packages"
RUN_ID="${RUN_ID:-comp_packages}"
OUT_DIR="corpus/reports"
OUT_MD="${OUT_DIR}/comp_packages_${DATE}.md"

mkdir -p "${OUT_DIR}"

python scripts/crawl.py --tier 1 --limit "${LIMIT}" --profile "${PROFILE}" --depth "${DEPTH}" --incremental -j "${JOBS}" --run-id "${RUN_ID}"
python scripts/comp_packages_report.py --sites corpus/sites/*.json --out "${OUT_MD}" --out-json
