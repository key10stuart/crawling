#!/bin/bash
# Kill all crawl-xvfb containers
#
# Usage: ./scripts/docker_cleanup.sh

CONTAINERS=$(docker ps -q --filter ancestor=crawl-xvfb)

if [ -z "$CONTAINERS" ]; then
    echo "No crawl containers running."
else
    COUNT=$(echo "$CONTAINERS" | wc -l | tr -d ' ')
    echo "Killing $COUNT crawl container(s)..."
    docker kill $CONTAINERS
    docker rm $CONTAINERS 2>/dev/null
    echo "Done."
fi
