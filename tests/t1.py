#!/usr/bin/env python3
"""T1: Test --help output is clean."""
import subprocess
import sys

def main():
    result = subprocess.run(
        [sys.executable, "scripts/crawl.py", "--help"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print("FAIL: --help returned non-zero")
        print(result.stderr)
        return 1

    # Check for expected sections
    output = result.stdout
    checks = [
        ("usage:" in output.lower(), "has usage line"),
        ("--domain" in output, "has --domain flag"),
        ("--tier" in output, "has --tier flag"),
        ("--depth" in output, "has --depth flag"),
        ("--fetch-method" in output, "has --fetch-method flag"),
    ]

    passed = 0
    for ok, desc in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {desc}")
        if ok:
            passed += 1

    print(f"\nT1: {passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1

if __name__ == "__main__":
    sys.exit(main())
