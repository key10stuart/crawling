#!/usr/bin/env python3
"""T4: Test parallel capture (requires GUI for Playwright)."""
import subprocess
import sys
import json
from pathlib import Path

CORPUS_DIR = Path(__file__).parent.parent / "corpus"

def main():
    print("T4: Parallel capture test")
    print("  NOTE: This test requires GUI access for Playwright")
    print("  Running with --fetch-method requests as fallback...\n")

    result = subprocess.run(
        [
            sys.executable, "scripts/crawl.py",
            "--tier", "1",
            "--limit", "3",
            "-j", "2",
            "--depth", "0",
            "--fetch-method", "requests",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        print("FAIL: parallel crawl returned non-zero")
        print(result.stderr[-500:] if result.stderr else "no stderr")
        return 1

    # Count recent site files (modified in last 5 min)
    import time
    cutoff = time.time() - 300
    recent = [
        p for p in (CORPUS_DIR / "sites").glob("*.json")
        if p.stat().st_mtime > cutoff
    ]

    print(f"  Sites crawled: {len(recent)}")
    for p in recent:
        data = json.loads(p.read_text())
        pages = len(data.get("pages", []))
        print(f"    {data.get('domain')}: {pages} pages")

    if len(recent) >= 2:
        print(f"\nT4: PASS (parallel execution worked)")
        return 0
    else:
        print(f"\nT4: PARTIAL (only {len(recent)} sites crawled)")
        return 1

if __name__ == "__main__":
    sys.exit(main())
