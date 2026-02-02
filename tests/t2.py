#!/usr/bin/env python3
"""T2: Test basic HTTP fetch with requests method."""
import subprocess
import sys
import json
from pathlib import Path

CORPUS_DIR = Path(__file__).parent.parent / "corpus"

def main():
    # Use a tier-1 carrier that works with requests
    result = subprocess.run(
        [
            sys.executable, "scripts/crawl.py",
            "--tier", "1",
            "--limit", "1",
            "--depth", "0",
            "--fetch-method", "requests",
            "--quiet",
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
