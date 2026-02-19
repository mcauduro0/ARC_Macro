#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# ARC Macro Risk OS — DigitalOcean GPU Droplet Runner
# ═══════════════════════════════════════════════════════════════════
#
# This script runs on the DO GPU droplet. It:
#   1. Pulls latest code from GitHub
#   2. Downloads cached CSV data from GH Actions artifact (or uses local)
#   3. Runs the model (skip-collect) — GPU accelerates numpy/scipy
#   4. Uploads results to the Manus dashboard via webhook
#
# Prerequisites on the DO GPU droplet:
#   - Python 3.11+ with numpy, scipy, pandas, scikit-learn, requests
#   - Git configured with repo access
#   - Environment variables: MANUS_WEBHOOK_SECRET, MANUS_DASHBOARD_URL
#
# Usage:
#   ./do_gpu_runner.sh [--data-tar /path/to/data.tar.gz]
#
# The --data-tar flag allows passing a pre-packaged data archive
# (e.g., from GH Actions) instead of using local cached data.
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
MODEL_DIR="$SCRIPT_DIR"
DATA_DIR="$MODEL_DIR/data"
TEMP_DIR="/tmp/arc_macro_run_$$"

# Parse arguments
DATA_TAR=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --data-tar)
            DATA_TAR="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "════════════════════════════════════════════════════════════"
echo "  ARC Macro Risk OS — GPU Runner"
echo "  $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "════════════════════════════════════════════════════════════"

# Step 1: Pull latest code
echo ""
echo "[1/4] Pulling latest code..."
cd "$REPO_DIR"
git pull --ff-only origin main 2>/dev/null || echo "  (git pull skipped — not a git repo or no changes)"

# Step 2: Restore data
echo ""
echo "[2/4] Preparing data..."
if [[ -n "$DATA_TAR" && -f "$DATA_TAR" ]]; then
    echo "  Extracting data from: $DATA_TAR"
    mkdir -p "$DATA_DIR"
    tar -xzf "$DATA_TAR" -C "$DATA_DIR"
    CSV_COUNT=$(ls "$DATA_DIR"/*.csv 2>/dev/null | wc -l)
    echo "  Extracted $CSV_COUNT CSV files"
else
    CSV_COUNT=$(ls "$DATA_DIR"/*.csv 2>/dev/null | wc -l)
    echo "  Using local cached data: $CSV_COUNT CSV files"
    if [[ "$CSV_COUNT" -lt 30 ]]; then
        echo "  WARNING: Only $CSV_COUNT CSV files found. Model quality may be degraded."
        echo "  Consider running data collection first or passing --data-tar"
    fi
fi

# Step 3: Run model (skip-collect)
echo ""
echo "[3/4] Running model (GPU-accelerated)..."
mkdir -p "$TEMP_DIR"

START_TIME=$(date +%s)

cd "$MODEL_DIR"
python3.11 run_model.py --skip-collect \
    > "$TEMP_DIR/model_output.json" \
    2> >(tee "$TEMP_DIR/model_stderr.log" >&2)

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

OUTPUT_SIZE=$(stat -c%s "$TEMP_DIR/model_output.json" 2>/dev/null || echo "0")
echo ""
echo "  Model completed in ${DURATION}s ($(( DURATION / 60 ))m $(( DURATION % 60 ))s)"
echo "  Output size: ${OUTPUT_SIZE} bytes"

# Validate output
if [[ "$OUTPUT_SIZE" -lt 1000 ]]; then
    echo "  ERROR: Output too small (${OUTPUT_SIZE} bytes). Model likely failed."
    cat "$TEMP_DIR/model_output.json" >&2
    exit 1
fi

# Validate JSON
python3.11 -c "
import json
d = json.load(open('$TEMP_DIR/model_output.json'))
print(f'  Dashboard keys: {len(d.get(\"dashboard\",{}))}')
print(f'  Timeseries points: {len(d.get(\"timeseries\",[]))}')
print(f'  Backtest points: {len(d.get(\"backtest_ts\",{}).get(\"timeseries\",[]))}')
"

# Step 4: Upload to dashboard
echo ""
echo "[4/4] Uploading to Manus dashboard..."

if [[ -z "${MANUS_WEBHOOK_SECRET:-}" || -z "${MANUS_DASHBOARD_URL:-}" ]]; then
    echo "  WARNING: MANUS_WEBHOOK_SECRET or MANUS_DASHBOARD_URL not set."
    echo "  Saving output to: $TEMP_DIR/model_output.json"
    echo "  Upload manually with:"
    echo "    gzip -c $TEMP_DIR/model_output.json | curl -X POST \\"
    echo "      -H 'Authorization: Bearer \$MANUS_WEBHOOK_SECRET' \\"
    echo "      -H 'Content-Type: application/json' \\"
    echo "      -H 'Content-Encoding: gzip' \\"
    echo "      --data-binary @- \\"
    echo "      \$MANUS_DASHBOARD_URL/api/webhook/model-result"
    exit 0
fi

gzip -c "$TEMP_DIR/model_output.json" > "$TEMP_DIR/model_output.json.gz"

RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST "${MANUS_DASHBOARD_URL}/api/webhook/model-result" \
    -H "Authorization: Bearer ${MANUS_WEBHOOK_SECRET}" \
    -H "Content-Type: application/json" \
    -H "Content-Encoding: gzip" \
    --data-binary @"$TEMP_DIR/model_output.json.gz" \
    --max-time 120)

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [[ "$HTTP_CODE" -ge 200 && "$HTTP_CODE" -lt 300 ]]; then
    echo "  Successfully uploaded to Manus dashboard (HTTP ${HTTP_CODE})"
    echo "  Response: ${BODY}"
else
    echo "  WARNING: Upload failed (HTTP ${HTTP_CODE})"
    echo "  Response: ${BODY}"
    echo "  Output saved at: $TEMP_DIR/model_output.json"
    exit 1
fi

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Run complete — ${DURATION}s ($(( DURATION / 60 ))m $(( DURATION % 60 ))s)"
echo "════════════════════════════════════════════════════════════"
