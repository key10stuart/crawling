#!/usr/bin/env python3
"""T3: Test capture mode with requests fetch method."""
import subprocess
import sys
import json
from pathlib import Path

CORPUS_DIR = Path(__file__).parent.parent / "corpus"

def main():
    result = subprocess.run(
        [
            sys.executable, "scripts/crawl.py",
            "--tier", "1",
            "--limit", "1",
            "--depth", "1",
            "--fetch-method", "requests",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    if result.returncode != 0:
        print("FAIL: capture mode crawl returned non-zero")
        print(result.stderr[-500:] if result.stderr else "no stderr")
        return 1

    # Find most recent site file
    sites = list((CORPUS_DIR / "sites").glob("*.json"))
    if not sites:
        print("FAIL: no site JSON files created")
        return 1

    latest = max(sites, key=lambda p: p.stat().st_mtime)
    data = json.loads(latest.read_text())

    checks = []

    # Check capture mode indicators
    checks.append((data.get("capture_mode") == True, "capture_mode: true"))
    checks.append((len(data.get("pages", [])) > 0, "has pages array"))
    checks.append((len(data.get("captures", [])) > 0, "has captures array"))
    checks.append(("stats" in data, "has stats object"))

    # Check page structure
    if data.get("pages"):
        p = data["pages"][0]
        checks.append(("tagged_blocks" in p, "page has tagged_blocks"))
        checks.append(("assets" in p, "page has assets"))
        checks.append(("links" in p, "page has links"))
        checks.append(("main_content" in p, "page has main_content"))

    # Check raw archive
    raw_dir = CORPUS_DIR / "raw" / data.get("domain", "unknown")
    checks.append((raw_dir.exists(), f"raw dir exists: {raw_dir.name}"))
    manifest = raw_dir / "manifest.json"
    checks.append((manifest.exists(), "manifest.json exists"))

    passed = 0
    for ok, desc in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {desc}")
        if ok:
            passed += 1

    print(f"\nT3: {passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1

if __name__ == "__main__":
    sys.exit(main())
