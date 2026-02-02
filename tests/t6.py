#!/usr/bin/env python3
"""T6: Test access_report.py generates report."""
import subprocess
import sys

def main():
    result = subprocess.run(
        [sys.executable, "scripts/access_report.py"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        print("FAIL: access_report.py returned non-zero")
        print(result.stderr[-500:] if result.stderr else "no stderr")
        return 1

    output = result.stdout

    checks = [
        ("ACCESS LAYER REPORT" in output, "has report header"),
        ("SUMMARY" in output, "has summary section"),
        ("BY TIER" in output, "has tier breakdown"),
        ("success rate" in output.lower(), "shows success rate"),
    ]

    passed = 0
    for ok, desc in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {desc}")
        if ok:
            passed += 1

    # Extract success rate
    import re
    match = re.search(r"Overall success rate: ([\d.]+)%", output)
    if match:
        print(f"  Success rate: {match.group(1)}%")

    print(f"\nT6: {passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1

if __name__ == "__main__":
    sys.exit(main())
