#!/usr/bin/env python3
"""T2: Test basic HTTP fetch with requests method."""
import subprocess
import sys
import json
from pathlib import Path
import tempfile

CORPUS_DIR = Path(__file__).parent.parent / "corpus"

def main():
    # Use quick, low-risk domains to keep test runtime bounded.
    companies = [
        {"name": "Example", "domain": "example.com", "tier": 1},
        {"name": "ExampleOrg", "domain": "example.org", "tier": 1},
    ]
    companies_file = Path(tempfile.gettempdir()) / "t2_companies.json"
    companies_file.write_text(json.dumps(companies), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, "scripts/crawl.py",
            "--companies", str(companies_file),
            "--limit", "1",
            "--depth", "0",
            "--fetch-method", "requests",
            "--delay", "0",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        print("FAIL: crawl returned non-zero")
        print(result.stderr[-500:] if result.stderr else "no stderr")
        return 1

    # Check that some site was crawled
    sites = list((CORPUS_DIR / "sites").glob("*.json"))
    if not sites:
        print("FAIL: no site JSON files created")
        return 1

    # Check most recent site file
    latest = max(sites, key=lambda p: p.stat().st_mtime)
    try:
        data = json.loads(latest.read_text())
        word_count = data.get("total_word_count", 0)
        if data.get("pages"):
            word_count = sum(
                p.get("main_content", {}).get("word_count", 0)
                for p in data["pages"]
            )
        print(f"  Site: {data.get('domain')}")
        print(f"  Words: {word_count}")
        print(f"\nT2: PASS (HTTP fetch works)")
        return 0
    except Exception as e:
        print(f"FAIL: could not parse site JSON: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
