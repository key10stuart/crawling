#!/bin/bash
# Run eval_access.py in Docker with invisible browser
#
# Usage:
#   ./scripts/run_eval_docker.sh              # Build and run with defaults
#   ./scripts/run_eval_docker.sh -j 4 -n 10   # Custom args
#   ./scripts/run_eval_docker.sh --build      # Force rebuild image
#
# Benefits:
#   - No browser windows pop up (runs in virtual display)
#   - Isolated environment
#   - Reproducible results
#
# Note: First run will be slow (downloads Playwright browsers ~400MB)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="crawl-eval"

cd "$PROJECT_DIR"

# Check for --build flag
BUILD=false
ARGS=()
for arg in "$@"; do
    if [ "$arg" == "--build" ]; then
        BUILD=true
    else
        ARGS+=("$arg")
    fi
done

# Build image if it doesn't exist or --build flag
if [ "$BUILD" == "true" ] || ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    echo "Building Docker image..."
    docker build -f Dockerfile.eval -t "$IMAGE_NAME" .
    echo ""
fi

# Run with volume mount for corpus
echo "Running eval in Docker..."
echo ""

docker run --rm \
    -v "$PROJECT_DIR/corpus:/app/corpus" \
    -v "$PROJECT_DIR/seeds:/app/seeds:ro" \
    -v "$PROJECT_DIR/profiles:/app/profiles:ro" \
    "$IMAGE_NAME" \
    "${ARGS[@]:-"-j" "4"}"
