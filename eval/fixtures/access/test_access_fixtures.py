#!/usr/bin/env python3
"""
Offline test harness for access layer fixtures.

Validates access fixture data against expected outcomes without making live requests.
Uses manifest.json to define test cases and expected results.

Usage:
    python eval/fixtures/access/test_access_fixtures.py
    python eval/fixtures/access/test_access_fixtures.py --verbose
    python eval/fixtures/access/test_access_fixtures.py --fixture successful_http_crawl
"""

import argparse
import json
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def load_manifest() -> dict:
    """Load the fixtures manifest."""
    manifest_path = FIXTURES_DIR / "manifest.json"
    return json.loads(manifest_path.read_text())


def load_fixture(fixture_id: str) -> tuple[dict, dict]:
    """Load fixture data and expected results. Returns (crawl_data, expected)."""
    manifest = load_manifest()

    fixture_meta = None
    for f in manifest["fixtures"]:
        if f["id"] == fixture_id:
            fixture_meta = f
            break

    if not fixture_meta:
        raise ValueError(f"Fixture not found: {fixture_id}")

    crawl_path = FIXTURES_DIR / fixture_meta["crawl_file"]
    crawl_data = json.loads(crawl_path.read_text())

    return crawl_data, fixture_meta["expected"]


def validate_fixture(crawl_data: dict, expected: dict) -> list[str]:
    """Validate crawl data against expected results. Returns list of failures."""
    failures = []
    access = crawl_data.get("access", {})

    # Check success (based on word count and page count)
    pages = crawl_data.get("pages", [])
    total_words = crawl_data.get("total_word_count", 0)
    actual_success = len(pages) > 0 and total_words >= 100

    if "success" in expected:
        if actual_success != expected["success"]:
            failures.append(f"success: expected {expected['success']}, got {actual_success}")

    # Check blocked status
    if "blocked" in expected:
        actual_blocked = access.get("blocked", False)
        if actual_blocked != expected["blocked"]:
            failures.append(f"blocked: expected {expected['blocked']}, got {actual_blocked}")

    # Check strategy
    if "strategy" in expected:
        actual_strategy = access.get("strategy", "unknown")
        if actual_strategy != expected["strategy"]:
            failures.append(f"strategy: expected {expected['strategy']}, got {actual_strategy}")

    # Check page count thresholds
    if "pages_gt" in expected:
        if len(pages) <= expected["pages_gt"]:
            failures.append(f"pages_gt: expected >{expected['pages_gt']}, got {len(pages)}")

    # Check word count thresholds
    if "words_gt" in expected:
        if total_words <= expected["words_gt"]:
            failures.append(f"words_gt: expected >{expected['words_gt']}, got {total_words}")

    if "words_lt" in expected:
        if total_words >= expected["words_lt"]:
            failures.append(f"words_lt: expected <{expected['words_lt']}, got {total_words}")

    # Check escalations
    if "escalations" in expected:
        actual_escalations = access.get("escalations", [])
        for esc in expected["escalations"]:
            if esc not in actual_escalations:
                failures.append(f"escalations: missing {esc}")

    # Check block reason
    if "block_reason" in expected:
        block_signals = access.get("block_signals", [])
        if expected["block_reason"] not in str(block_signals):
            failures.append(f"block_reason: expected {expected['block_reason']} in signals")

    return failures


def run_all_tests(verbose: bool = False) -> tuple[int, int]:
    """Run all fixture tests. Returns (passed, failed)."""
    manifest = load_manifest()

    passed = 0
    failed = 0

    for fixture_meta in manifest["fixtures"]:
        fixture_id = fixture_meta["id"]

        try:
            crawl_data, expected = load_fixture(fixture_id)
            failures = validate_fixture(crawl_data, expected)

            if failures:
                print(f"FAIL: {fixture_id} ({fixture_meta['name']})")
                for f in failures:
                    print(f"      {f}")
                failed += 1
            else:
                print(f"PASS: {fixture_id}")
                if verbose:
                    access = crawl_data.get("access", {})
                    print(f"      strategy={access.get('strategy')}, "
                          f"blocked={access.get('blocked')}, "
                          f"words={crawl_data.get('total_word_count')}, "
                          f"pages={len(crawl_data.get('pages', []))}")
                passed += 1

        except Exception as e:
            print(f"ERROR: {fixture_id} - {e}")
            failed += 1

    return passed, failed


def run_single_test(fixture_id: str, verbose: bool = False):
    """Run a single fixture test with detailed output."""
    crawl_data, expected = load_fixture(fixture_id)
    failures = validate_fixture(crawl_data, expected)

    print(f"Fixture: {fixture_id}")
    print(f"  Domain: {crawl_data.get('domain')}")
    print(f"  Crawl Date: {crawl_data.get('snapshot_date')}")
    print()

    access = crawl_data.get("access", {})
    print("  Access Info:")
    print(f"    Strategy: {access.get('strategy')}")
    print(f"    Blocked: {access.get('blocked')}")
    print(f"    Escalations: {access.get('escalations', [])}")

    recon = access.get("recon", {})
    if recon:
        print(f"    CDN: {recon.get('cdn')}")
        print(f"    WAF: {recon.get('waf')}")
        print(f"    Challenge: {recon.get('challenge_detected')}")
        print(f"    JS Required: {recon.get('js_required')}")
    print()

    print("  Content:")
    print(f"    Total Words: {crawl_data.get('total_word_count')}")
    print(f"    Pages: {len(crawl_data.get('pages', []))}")
    print()

    print("  Expected:")
    for k, v in expected.items():
        print(f"    {k}: {v}")
    print()

    if failures:
        print("FAIL - Validation Errors:")
        for f in failures:
            print(f"  {f}")
    else:
        print("PASS - All validations passed")


def main():
    parser = argparse.ArgumentParser(description="Test access layer fixtures")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--fixture", "-f", help="Run single fixture by ID")
    args = parser.parse_args()

    if args.fixture:
        run_single_test(args.fixture, args.verbose)
    else:
        passed, failed = run_all_tests(args.verbose)
        print()
        print(f"Results: {passed} passed, {failed} failed")
        sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
