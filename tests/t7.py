#!/usr/bin/env python3
"""T7: Test eval_extraction.py runs successfully."""
import subprocess
import sys
from pathlib import Path

CORPUS_DIR = Path(__file__).parent.parent / "corpus"

def main():
    # Check if there are any site files to evaluate
    sites = list((CORPUS_DIR / "sites").glob("*.json"))
    if not sites:
        print("SKIP: No site JSON files to evaluate")
        return 0

    result = subprocess.run(
        [
            sys.executable, "scripts/eval_extraction.py",
            "--auto",
            "--limit", "1",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        print("FAIL: eval_extraction.py returned non-zero")
        print(result.stderr[-500:] if result.stderr else "no stderr")
        return 1

    output = result.stdout

    # Check for expected output
    checks = [
        ("Evaluating" in output or "evaluated" in output.lower(), "ran evaluation"),
        ("score" in output.lower() or "rating" in output.lower(), "produced scores"),
    ]

    passed = 0
    for ok, desc in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {desc}")
        if ok:
            passed += 1

    print(f"\nT7: {passed}/{len(checks)} checks passed")
    return 0 if passed >= 1 else 1

if __name__ == "__main__":
    sys.exit(main())
