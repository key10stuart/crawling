#!/usr/bin/env python3
"""
Offline test harness for recon module.

Runs recon detection logic against HTML fixtures without making live requests.
Uses manifest.json to validate expected signals.

Usage:
    python eval/fixtures/recon/test_recon_fixtures.py
    python eval/fixtures/recon/test_recon_fixtures.py --verbose
    python eval/fixtures/recon/test_recon_fixtures.py --fixture cloudflare_challenge
"""

import argparse
import json
import re
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

FIXTURES_DIR = Path(__file__).parent


@dataclass
class ReconResult:
    """Result of recon analysis."""
    cdn: Optional[str] = None
    challenge_type: Optional[str] = None
    js_required: bool = False
    recommended_method: str = "http"
    signals: list = None

    def __post_init__(self):
        if self.signals is None:
            self.signals = []


def detect_cdn_from_headers(headers: dict) -> Optional[str]:
    """Detect CDN/WAF from response headers."""
    headers_lower = {k.lower(): v.lower() for k, v in headers.items()}

    # Cloudflare
    if 'cf-ray' in headers_lower or 'cf-cache-status' in headers_lower:
        return 'cloudflare'

    # StackPath
    if 'sg-captcha' in headers_lower or headers_lower.get('x-cdn') == 'stackpath':
        return 'stackpath'

    # Akamai
    if 'x-akamai-transformed' in headers_lower or 'akamaighost' in headers_lower.get('server', ''):
        return 'akamai'

    # Fastly
    if 'x-fastly-request-id' in headers_lower or 'x-served-by' in headers_lower:
        if 'cache-' in headers_lower.get('x-served-by', ''):
            return 'fastly'

    # Vercel
    if 'x-vercel-id' in headers_lower or headers_lower.get('server') == 'vercel':
        return 'vercel'

    return None


def detect_challenge_from_headers(headers: dict, status_code: int) -> Optional[str]:
    """Detect challenge type from headers and status."""
    headers_lower = {k.lower(): v.lower() for k, v in headers.items()}

    # StackPath sgcaptcha
    if headers_lower.get('sg-captcha') == 'challenge':
        return 'sgcaptcha'

    # Generic bot challenge on 202
    if status_code == 202:
        return 'bot-challenge'

    # Akamai bot manager on 403
    if status_code == 403 and detect_cdn_from_headers(headers) == 'akamai':
        return 'bot-manager'

    return None


def detect_challenge_from_html(html: str) -> Optional[str]:
    """Detect challenge type from HTML content."""
    html_lower = html.lower()

    # Cloudflare challenge indicators
    cf_indicators = [
        'checking your browser',
        'just a moment',
        'cf-browser-verification',
        'ddos protection by cloudflare',
    ]
    if any(ind in html_lower for ind in cf_indicators):
        return 'cf-challenge'

    # StackPath/generic captcha
    if 'sg-captcha' in html_lower or '_captcha/challenge' in html_lower:
        return 'sgcaptcha'

    return None


def detect_js_required(html: str) -> tuple[bool, list[str]]:
    """Detect if JavaScript is required to render content."""
    signals = []

    # Empty SPA root divs
    if re.search(r'<div\s+id=["\'](?:root|app|__next)["\']\s*>\s*</div>', html, re.IGNORECASE):
        signals.append('empty_spa_root')

    # Noscript warnings
    noscript_match = re.search(r'<noscript[^>]*>(.*?)</noscript>', html, re.IGNORECASE | re.DOTALL)
    if noscript_match:
        noscript_content = noscript_match.group(1).lower()
        if any(w in noscript_content for w in ['enable javascript', 'javascript required', 'need javascript', 'requires javascript']):
            signals.append('noscript_warning')

    # Next.js markers
    if '__NEXT_DATA__' in html or '/_next/static' in html:
        signals.append('nextjs')

    # React markers
    if 'data-reactroot' in html or re.search(r'/static/js/.*\.chunk\..*\.js', html):
        signals.append('react')

    # Vue markers
    if re.search(r'data-v-[a-f0-9]+', html) or 'v-cloak' in html:
        signals.append('vue')

    # Angular markers
    if 'ng-version' in html or '<app-root' in html:
        signals.append('angular')

    # AEM markers
    if '/etc.clientlibs/' in html or '/content/dam/' in html or '/_jcr_content/' in html:
        signals.append('aem')

    # Webpack/bundler patterns
    if re.search(r'\.chunk\.[a-f0-9]+\.js', html) or 'webpack' in html.lower():
        signals.append('bundled_js')

    # Strong signals that alone indicate JS requirement
    strong_signals = {'noscript_warning', 'angular', 'aem', 'empty_spa_root'}

    js_required = bool(signals) and (
        len(signals) >= 2 or
        bool(set(signals) & strong_signals)
    )

    return js_required, signals


def determine_recommended_method(cdn: Optional[str], challenge: Optional[str], js_required: bool) -> str:
    """Determine recommended fetch method based on recon."""
    # Challenge-based recommendations
    if challenge == 'sgcaptcha':
        return 'stealth+cookies'
    if challenge in ('cf-challenge', 'bot-manager'):
        return 'stealth'
    if challenge == 'bot-challenge':
        return 'stealth'

    # CDN-based recommendations (no challenge)
    if cdn == 'cloudflare':
        return 'js'  # Cloudflare without challenge still benefits from JS
    if cdn == 'akamai':
        return 'js'

    # JS requirement
    if js_required:
        return 'js'

    # Default to simple HTTP
    return 'http'


def run_recon(headers: dict, html: str, status_code: int) -> ReconResult:
    """Run full recon analysis."""
    result = ReconResult()

    # Detect CDN
    result.cdn = detect_cdn_from_headers(headers)

    # Detect challenge (headers first, then HTML)
    result.challenge_type = detect_challenge_from_headers(headers, status_code)
    if not result.challenge_type:
        result.challenge_type = detect_challenge_from_html(html)

    # Detect JS requirement
    result.js_required, result.signals = detect_js_required(html)

    # If there's a challenge, JS is definitely required
    if result.challenge_type:
        result.js_required = True

    # Determine recommended method
    result.recommended_method = determine_recommended_method(
        result.cdn, result.challenge_type, result.js_required
    )

    return result


def load_fixture(fixture_id: str) -> tuple[dict, str, int, dict]:
    """Load fixture data. Returns (headers, html, status_code, expected)."""
    manifest_path = FIXTURES_DIR / "manifest.json"
    with open(manifest_path) as f:
        manifest = json.load(f)

    fixture = None
    for f in manifest["fixtures"]:
        if f["id"] == fixture_id:
            fixture = f
            break

    if not fixture:
        raise ValueError(f"Fixture not found: {fixture_id}")

    html_path = FIXTURES_DIR / fixture["html_file"]
    with open(html_path) as f:
        html = f.read()

    return (
        fixture["headers"],
        html,
        fixture["status_code"],
        fixture["expected"]
    )


def compare_results(actual: ReconResult, expected: dict) -> list[str]:
    """Compare actual results to expected. Returns list of mismatches."""
    mismatches = []

    if actual.cdn != expected.get("cdn"):
        mismatches.append(f"cdn: expected {expected.get('cdn')}, got {actual.cdn}")

    if actual.challenge_type != expected.get("challenge_type"):
        mismatches.append(f"challenge_type: expected {expected.get('challenge_type')}, got {actual.challenge_type}")

    if actual.js_required != expected.get("js_required"):
        mismatches.append(f"js_required: expected {expected.get('js_required')}, got {actual.js_required}")

    if actual.recommended_method != expected.get("recommended_method"):
        mismatches.append(f"recommended_method: expected {expected.get('recommended_method')}, got {actual.recommended_method}")

    return mismatches


def run_all_tests(verbose: bool = False) -> tuple[int, int]:
    """Run all fixture tests. Returns (passed, failed)."""
    manifest_path = FIXTURES_DIR / "manifest.json"
    with open(manifest_path) as f:
        manifest = json.load(f)

    passed = 0
    failed = 0

    for fixture in manifest["fixtures"]:
        fixture_id = fixture["id"]

        try:
            headers, html, status_code, expected = load_fixture(fixture_id)
            result = run_recon(headers, html, status_code)
            mismatches = compare_results(result, expected)

            if mismatches:
                print(f"FAIL: {fixture_id} ({fixture['name']})")
                for m in mismatches:
                    print(f"      {m}")
                if verbose:
                    print(f"      signals: {result.signals}")
                failed += 1
            else:
                print(f"PASS: {fixture_id}")
                if verbose:
                    print(f"      cdn={result.cdn}, challenge={result.challenge_type}, "
                          f"js={result.js_required}, method={result.recommended_method}")
                    print(f"      signals: {result.signals}")
                passed += 1

        except Exception as e:
            print(f"ERROR: {fixture_id} - {e}")
            failed += 1

    return passed, failed


def run_single_test(fixture_id: str, verbose: bool = False):
    """Run a single fixture test."""
    headers, html, status_code, expected = load_fixture(fixture_id)
    result = run_recon(headers, html, status_code)
    mismatches = compare_results(result, expected)

    print(f"Fixture: {fixture_id}")
    print(f"  Status: {status_code}")
    print(f"  Headers: {headers}")
    print(f"  Results:")
    print(f"    cdn: {result.cdn}")
    print(f"    challenge_type: {result.challenge_type}")
    print(f"    js_required: {result.js_required}")
    print(f"    recommended_method: {result.recommended_method}")
    print(f"    signals: {result.signals}")
    print()

    if mismatches:
        print("FAIL - Mismatches:")
        for m in mismatches:
            print(f"  {m}")
    else:
        print("PASS")


def main():
    parser = argparse.ArgumentParser(description="Test recon logic against fixtures")
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
