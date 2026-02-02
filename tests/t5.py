#!/usr/bin/env python3
"""T5: Docker crawl test (requires Docker access)."""
import subprocess
import sys
from pathlib import Path

def main():
    print("T5: Docker crawl test")
    print("  NOTE: This test requires Docker socket access\n")

    script = Path(__file__).parent.parent / "scripts" / "docker_crawl.sh"
    if not script.exists():
        print(f"FAIL: {script} not found")
        return 1

    # Check Docker availability
    docker_check = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
    )
    if docker_check.returncode != 0:
        print("SKIP: Docker not available")
        print("  Run this test from a user with Docker socket access")
        return 0  # Skip, not fail

    result = subprocess.run(
        [str(script), "--tier", "1", "--limit", "1"],
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        print("FAIL: Docker crawl returned non-zero")
        print(result.stderr[-500:] if result.stderr else "no stderr")
        return 1

    print("T5: PASS (Docker crawl completed)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
