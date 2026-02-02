#!/usr/bin/env python3
"""T9: Full tier-1 Docker crawl (requires Docker + GUI user)."""
import subprocess
import sys
import json
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
CORPUS_DIR = PROJECT_DIR / "corpus"

def main():
    print("T9: Full tier-1 Docker crawl")
    print("  NOTE: Requires Docker daemon + GUI user\n")

    # Check Docker availability
    docker_check = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
    )
    if docker_check.returncode != 0:
        print("SKIP: Docker not available")
        print("  Run from a user with Docker socket access")
        return 0  # Skip, not fail

    script = PROJECT_DIR / "scripts" / "docker_crawl.sh"
    if not script.exists():
        print(f"FAIL: {script} not found")
        return 1

    print("Starting full tier-1 crawl (this may take a while)...")
    start_time = time.time()

    result = subprocess.run(
        [str(script), "--tier", "1"],
        capture_output=False,  # Stream output live
        text=True,
        timeout=3600,  # 1 hour max
        cwd=str(PROJECT_DIR),
    )

    elapsed = time.time() - start_time
    print(f"\nCompleted in {elapsed/60:.1f} minutes")

    if result.returncode != 0:
        print(f"FAIL: Docker crawl returned {result.returncode}")
        return 1

    # Count results
    sites = list((CORPUS_DIR / "sites").glob("*.json"))
    tier1_sites = []
    for p in sites:
        try:
            data = json.loads(p.read_text())
            if data.get("tier") == 1:
                tier1_sites.append(data)
        except:
            pass

    print(f"\nResults:")
    print(f"  Tier-1 sites crawled: {len(tier1_sites)}")

    total_pages = sum(len(s.get("pages", [])) for s in tier1_sites)
    print(f"  Total pages: {total_pages}")

    # Check success rate
    success = sum(1 for s in tier1_sites if len(s.get("pages", [])) > 0)
    rate = (success / len(tier1_sites) * 100) if tier1_sites else 0
    print(f"  Success rate: {rate:.1f}%")

    if rate >= 50:
        print(f"\nT9: PASS ({success}/{len(tier1_sites)} tier-1 sites)")
        return 0
    else:
        print(f"\nT9: PARTIAL (only {rate:.1f}% success)")
        return 1

if __name__ == "__main__":
    sys.exit(main())
