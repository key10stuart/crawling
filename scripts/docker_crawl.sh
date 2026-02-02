#!/bin/bash
# Professional-grade crawl runner using Docker with Xvfb
#
# Usage:
#   ./scripts/docker_crawl.sh --tier 1              # Uses defaults from configs/defaults.yaml
#   ./scripts/docker_crawl.sh --domain schneider.com
#   ./scripts/docker_crawl.sh --tier 1 --freshen 1d # Override default freshen
#
# Defaults (from configs/defaults.yaml):
#   depth: 2, freshen: 7d, jobs: 4, js_auto: true, progress: true
#
# All browser windows render to virtual display - nothing visible.
# Full escalation ladder available (including visible mode).
#
# Docker flags (must come BEFORE crawl args):
#   --rebuild    Force rebuild the Docker image (use after code or dep changes)
#
# Code is baked into image. Rebuild after changing code or requirements.txt.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
IMAGE_NAME="crawl-xvfb"

cd "$PROJECT_DIR"

# Check for --rebuild flag
FORCE_REBUILD=false
CRAWL_ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--rebuild" ]; then
        FORCE_REBUILD=true
    else
        CRAWL_ARGS+=("$arg")
    fi
done

# Check Docker daemon
if ! docker info &>/dev/null; then
    echo "Docker daemon not running. Start Docker Desktop first:"
    echo "  dockerstart"
    exit 1
fi

# Build image if needed (using tar to avoid permission issues)
if $FORCE_REBUILD || ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    if $FORCE_REBUILD; then
        echo "Rebuilding Docker image (--rebuild flag)..."
    else
        echo "Building Docker image (first time only)..."
    fi

    # Create a clean build context via tar, excluding problematic dirs
    tar --no-xattrs \
        --exclude='.claude' \
        --exclude='.git' \
        --exclude='corpus' \
        --exclude='__pycache__' \
        --exclude='.pytest_cache' \
        --exclude='node_modules' \
        --exclude='.DS_Store' \
        -cf - . 2>/dev/null | docker build -t "$IMAGE_NAME" -f Dockerfile.xvfb -

    echo "Build complete."
    echo ""
fi

# Run crawl with source code mounted as volumes
# This means code changes don't require rebuild - only dep changes do
echo "Starting crawl in Docker container..."
echo ""

# Only mount corpus for output - everything else baked in
# Entrypoint already runs "python scripts/crawl.py", just pass args
# --init: proper signal handling for graceful shutdown
# trap: cleanup container on script exit
CONTAINER_ID=""
cleanup() {
    if [ -n "$CONTAINER_ID" ]; then
        echo ""
        echo "Cleaning up container..."
        docker kill "$CONTAINER_ID" 2>/dev/null
        docker rm "$CONTAINER_ID" 2>/dev/null
    fi
}
trap cleanup EXIT INT TERM

CONTAINER_ID=$(docker run -d --init \
    -e CRAWL_IN_DOCKER=1 \
    -v "$PROJECT_DIR/corpus:/app/corpus:delegated" \
    "$IMAGE_NAME" \
    "${CRAWL_ARGS[@]}")

# Follow logs until container exits
docker logs -f "$CONTAINER_ID"

# Wait for container to finish and get exit code
EXIT_CODE=$(docker wait "$CONTAINER_ID")
docker rm "$CONTAINER_ID" 2>/dev/null
exit $EXIT_CODE
