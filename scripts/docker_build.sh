#!/bin/bash
# Build the Docker image for crawling with Xvfb
#
# Usage:
#   ./scripts/docker_build.sh

set -e

cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "Building crawl-xvfb image..."

tar --no-xattrs \
    --exclude='.claude' \
    --exclude='.git' \
    --exclude='corpus' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='node_modules' \
    --exclude='.DS_Store' \
    -cf - . 2>/dev/null | docker build -t crawl-xvfb -f Dockerfile.xvfb -

echo ""
echo "Done. Run crawls with:"
echo "  ./scripts/docker_crawl.sh --tier 1 --depth 2 --js-auto"
