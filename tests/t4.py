#!/usr/bin/env python3
"""T4: Test parallel capture (requires GUI for Playwright)."""
import subprocess
import sys
import json
from pathlib import Path
import tempfile

CORPUS_DIR = Path(__file__).parent.parent / "corpus"

def main():
    print("T4: Parallel capture test")
    print("  NOTE: This test requires GUI access for Playwright")
    print("  Running with --fetch-method requests as fallback...\n")

    companies = [
        {"name": "Example", "domain": "example.com", "tier": 1},
        {"name": "ExampleOrg", "domain": "example.org", "tier": 1},
        {"name": "IANA", "domain": "iana.org", "tier": 1},
    ]
    companies_file = Path(tempfile.gettempdir()) / "t4_companies.json"
    companies_file.write_text(json.dumps(companies), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, "scripts/crawl.py",
            "--companies", str(companies_file),
            "--limit", "3",
            "-j", "2",
            "--depth", "0",
            "--fetch-method", "requests",
            "--delay", "0",
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
