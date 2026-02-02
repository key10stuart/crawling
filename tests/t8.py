#!/usr/bin/env python3
"""T8: Run pytest on capture and extraction tests."""
import subprocess
import sys

def main():
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/test_capture.py",
            "tests/test_extraction.py",
            "-v",
            "--tb=short",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    output = result.stdout + result.stderr

    # Parse results
    import re
    match = re.search(r"(\d+) passed", output)
    passed = int(match.group(1)) if match else 0

    match = re.search(r"(\d+) failed", output)
    failed = int(match.group(1)) if match else 0

    match = re.search(r"(\d+) skipped", output)
    skipped = int(match.group(1)) if match else 0

    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"  Skipped: {skipped}")

    if failed > 0:
        print(f"\nT8: FAIL ({failed} tests failed)")
        # Show failure details
        print("\nFailure details:")
        print(output[-2000:])
        return 1

    print(f"\nT8: PASS ({passed} tests passed)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
