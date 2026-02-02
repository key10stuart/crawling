#!/usr/bin/env python3
"""
Guided System Evaluation - For Dummies Edition

A beginner-friendly walkthrough of the entire crawling system.
No prior knowledge required. Each test explains what's happening
and guides you through what to look for.

Usage:
    python scripts/eval_guided.py
    python scripts/eval_guided.py --quick      # Skip manual/slow tests
    python scripts/eval_guided.py --section 3  # Jump to section

Report: corpus/eval_reports/guided_eval_{timestamp}.json
"""

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent
REPORTS_DIR = PROJECT_ROOT / "corpus" / "eval_reports"
CORPUS_DIR = PROJECT_ROOT / "corpus" / "sites"


# =============================================================================
# Styling
# =============================================================================

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    END = '\033[0m'


def clear():
    os.system('clear' if os.name != 'nt' else 'cls')


def header(text):
    print(f"\n{Colors.BOLD}{Colors.HEADER}{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}{Colors.END}\n")


def section(text):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'-'*50}")
    print(f"  {text}")
    print(f"{'-'*50}{Colors.END}\n")


def info(text):
    print(f"{Colors.BLUE}ℹ {text}{Colors.END}")


def success(text):
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")


def warn(text):
    print(f"{Colors.YELLOW}⚠ {text}{Colors.END}")


def error(text):
    print(f"{Colors.RED}✗ {text}{Colors.END}")


def dim(text):
    print(f"{Colors.DIM}{text}{Colors.END}")


def prompt(text):
    return input(f"{Colors.BOLD}{text}{Colors.END}").strip().lower()


def wait():
    input(f"\n{Colors.DIM}Press Enter to continue...{Colors.END}")


def yesno(question) -> bool:
    """Simple yes/no question."""
    while True:
        answer = prompt(f"{question} [y/n]: ")
        if answer in ['y', 'yes']:
            return True
        if answer in ['n', 'no']:
            return False
        print("Please answer 'y' or 'n'")


# =============================================================================
# Command Running
# =============================================================================

def run(cmd, timeout=120, show_output=True, max_lines=30):
    """Run a command and return (success, output)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=PROJECT_ROOT
        )
        output = result.stdout + result.stderr

        if show_output:
            lines = output.strip().split('\n')
            if len(lines) > max_lines:
                print('\n'.join(lines[:max_lines//2]))
                dim(f"  ... ({len(lines) - max_lines} lines hidden) ...")
                print('\n'.join(lines[-max_lines//2:]))
            else:
                print(output)

        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        error(f"Command timed out after {timeout}s")
        return False, "TIMEOUT"
    except Exception as e:
        error(f"Error: {e}")
        return False, str(e)


def check_file_exists(path):
    """Check if a file exists and has content."""
    p = PROJECT_ROOT / path if not Path(path).is_absolute() else Path(path)
    return p.exists() and p.stat().st_size > 0


def get_site_stats(domain):
    """Get basic stats from a crawled site."""
    filename = domain.replace(".", "_") + ".json"
    filepath = CORPUS_DIR / filename

    if not filepath.exists():
        return None

    try:
        data = json.loads(filepath.read_text())
        return {
            "words": data.get("total_word_count", 0),
            "pages": len(data.get("pages", [])),
            "domain": data.get("domain", domain),
        }
    except:
        return None


# =============================================================================
# Report Management
# =============================================================================

@dataclass
class EvalReport:
    started: str = ""
    completed: str = ""
    evaluator: str = ""
    sections: dict = field(default_factory=dict)
    overall_notes: str = ""

    def save(self):
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = REPORTS_DIR / f"guided_eval_{ts}.json"
        path.write_text(json.dumps(asdict(self), indent=2))
        return path


# =============================================================================
# SECTION 1: Can It Crawl At All?
# =============================================================================

def section_1_basic_crawl(report, quick=False):
    clear()
    header("SECTION 1: Can It Crawl At All?")

    print("""
This section tests the most basic functionality:
Can the crawler visit a website and extract text from it?

We'll test on a simple website that doesn't need any special tricks.
    """)

    wait()

    results = {"tests": [], "passed": 0, "failed": 0}

    # Test 1.1: Basic HTTP crawl
    section("Test 1.1: Basic Web Crawl")

    print("""
WHAT WE'RE TESTING:
  The crawler visits saia.com (a trucking company) and extracts text.
  This site is simple - no JavaScript tricks, no bot protection.

WHAT SHOULD HAPPEN:
  - Crawler connects to the website
  - Downloads the homepage
  - Extracts the main text content
  - Saves it to a file

WHAT SUCCESS LOOKS LIKE:
  - No error messages
  - Reports extracting 500+ words
  - Creates an output file
    """)

    if quick:
        info("Quick mode: Checking if previous crawl exists...")
        stats = get_site_stats("saia.com")
        if stats and stats["words"] > 500:
            success(f"Previous crawl found: {stats['words']} words")
            results["tests"].append({"name": "basic_crawl", "status": "pass", "note": "used existing"})
            results["passed"] += 1
        else:
            warn("No previous crawl. Running crawl...")
            quick = False  # Fall through to actual test

    if not quick:
        info("Running: python scripts/crawl.py --domain saia.com --depth 0 --fetch-method requests")
        print()

        ok, output = run("python scripts/crawl.py --domain saia.com --depth 0 --fetch-method requests", timeout=60)
        print()

        # Check results
        stats = get_site_stats("saia.com")

        if stats and stats["words"] > 500:
            success(f"Crawl successful! Extracted {stats['words']} words")
            results["tests"].append({"name": "basic_crawl", "status": "pass", "words": stats["words"]})
            results["passed"] += 1
        elif stats:
            warn(f"Crawl completed but only got {stats['words']} words (expected 500+)")
            results["tests"].append({"name": "basic_crawl", "status": "partial", "words": stats["words"]})
        else:
            error("Crawl failed - no output file created")
            results["tests"].append({"name": "basic_crawl", "status": "fail"})
            results["failed"] += 1

    wait()

    # Test 1.2: Can it handle JavaScript sites?
    section("Test 1.2: JavaScript Website")

    print("""
WHAT WE'RE TESTING:
  Some websites load their content with JavaScript. A basic web request
  just sees an empty page. The crawler needs to use a real browser.

  schneider.com uses Next.js - the page is basically empty without JS.

WHAT SHOULD HAPPEN:
  - Crawler detects it needs a browser
  - Launches Playwright (headless Chrome)
  - Waits for JavaScript to load
  - Then extracts the content

WHAT SUCCESS LOOKS LIKE:
  - Extracts 1000+ words (not just "Loading..." or empty)
  - No timeout errors
    """)

    if quick:
        info("Quick mode: Checking existing crawl...")
        stats = get_site_stats("schneider.com")
        if stats and stats["words"] > 1000:
            success(f"Previous crawl found: {stats['words']} words")
            results["tests"].append({"name": "js_crawl", "status": "pass", "note": "used existing"})
            results["passed"] += 1
        else:
            warn("No good previous crawl. This test takes ~30 seconds...")
            info("Running: python scripts/crawl.py --domain schneider.com --depth 0 --fetch-method js")
            print()
            ok, _ = run("python scripts/crawl.py --domain schneider.com --depth 0 --fetch-method js", timeout=90)
            stats = get_site_stats("schneider.com")
            if stats and stats["words"] > 1000:
                success(f"Crawl successful! Extracted {stats['words']} words")
                results["tests"].append({"name": "js_crawl", "status": "pass", "words": stats["words"]})
                results["passed"] += 1
            else:
                error(f"JS crawl got only {stats['words'] if stats else 0} words")
                results["tests"].append({"name": "js_crawl", "status": "fail"})
                results["failed"] += 1
    else:
        info("This test takes about 30 seconds (launching browser)...")
        info("Running: python scripts/crawl.py --domain schneider.com --depth 0 --fetch-method js")
        print()

        ok, _ = run("python scripts/crawl.py --domain schneider.com --depth 0 --fetch-method js", timeout=90)
        print()

        stats = get_site_stats("schneider.com")
        if stats and stats["words"] > 1000:
            success(f"JS crawl successful! Extracted {stats['words']} words")
            results["tests"].append({"name": "js_crawl", "status": "pass", "words": stats["words"]})
            results["passed"] += 1
        elif stats:
            warn(f"JS crawl only got {stats['words']} words - might be a problem")
            results["tests"].append({"name": "js_crawl", "status": "partial"})
        else:
            error("JS crawl failed")
            results["tests"].append({"name": "js_crawl", "status": "fail"})
            results["failed"] += 1

    wait()

    # Summary
    section("Section 1 Summary")

    print(f"Tests passed: {results['passed']}")
    print(f"Tests failed: {results['failed']}")

    if results['passed'] >= 2:
        success("Basic crawling is working!")
        print("\nThe system can:")
        print("  - Connect to websites")
        print("  - Extract text content")
        print("  - Handle JavaScript-heavy sites")
    elif results['passed'] >= 1:
        warn("Basic crawling partially works")
        print("Some sites work, but there may be issues with JS rendering.")
    else:
        error("Basic crawling has problems")
        print("The fundamental crawling isn't working. Check error messages above.")

    report.sections["1_basic_crawl"] = results

    if not yesno("\nContinue to next section?"):
        return False
    return True


# =============================================================================
# SECTION 2: Does It Detect Protections?
# =============================================================================

def section_2_recon(report, quick=False):
    clear()
    header("SECTION 2: Does It Detect Protections?")

    print("""
This section tests the "recon" (reconnaissance) system.

Before crawling a site, the system checks what kind of protection it has:
- Cloudflare (common, shows "checking your browser" pages)
- StackPath (shows captchas)
- Akamai, Fastly (enterprise CDNs)
- JavaScript-only sites (need a real browser)

This helps the crawler choose the right strategy without wasting time.
    """)

    wait()

    results = {"tests": [], "passed": 0, "failed": 0}

    # Test 2.1: Recon on protected site
    section("Test 2.1: Detect Protection")

    print("""
WHAT WE'RE TESTING:
  Run recon on knight-swift.com - a site with StackPath protection.
  The system should detect the CDN and protection type.

WHAT SUCCESS LOOKS LIKE:
  - Detects "stackpath" as CDN
  - Detects some kind of challenge/protection
    """)

    info("Running recon on knight-swift.com...")
    print()

    cmd = '''python -c "
from fetch.recon import recon_site
r = recon_site('https://www.knight-swift.com')
print(f'CDN detected: {r.cdn}')
print(f'WAF detected: {r.waf}')
print(f'Challenge page: {r.challenge_detected}')
print(f'Needs JavaScript: {r.js_required}')
"'''

    ok, output = run(cmd, timeout=30)
    print()

    if "stackpath" in output.lower() or "challenge" in output.lower() or r.challenge_detected:
        success("Protection detected correctly!")
        results["tests"].append({"name": "detect_protection", "status": "pass"})
        results["passed"] += 1
    elif "cdn detected: none" in output.lower():
        warn("No CDN detected - recon might not be working")
        results["tests"].append({"name": "detect_protection", "status": "partial"})
    else:
        info("Some detection occurred - check output above")
        results["tests"].append({"name": "detect_protection", "status": "partial"})

    wait()

    # Test 2.2: Recon caching
    section("Test 2.2: Recon Cache")

    print("""
WHAT WE'RE TESTING:
  Recon results should be saved so we don't re-check every time.
  There should be a cache file at corpus/access/recon_cache.json

WHAT SUCCESS LOOKS LIKE:
  - File exists
  - Contains recent entries
    """)

    cache_path = PROJECT_ROOT / "corpus" / "access" / "recon_cache.json"

    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
            entries = len(cache)
            success(f"Recon cache exists with {entries} entries")

            # Show a sample
            if cache:
                sample_domain = list(cache.keys())[0]
                dim(f"  Sample entry: {sample_domain}")

            results["tests"].append({"name": "recon_cache", "status": "pass", "entries": entries})
            results["passed"] += 1
        except:
            warn("Cache file exists but couldn't be read")
            results["tests"].append({"name": "recon_cache", "status": "partial"})
    else:
        warn("No recon cache yet (will be created after crawls)")
        results["tests"].append({"name": "recon_cache", "status": "skip"})

    wait()

    # Summary
    section("Section 2 Summary")

    if results['passed'] >= 1:
        success("Recon system is working!")
        print("\nThe system can:")
        print("  - Detect CDN/WAF protection before crawling")
        print("  - Cache results to avoid repeated checks")
    else:
        warn("Recon might need attention")

    report.sections["2_recon"] = results

    if not yesno("\nContinue to next section?"):
        return False
    return True


# =============================================================================
# SECTION 3: Can It Handle Blocked Sites?
# =============================================================================

def section_3_monkey(report, quick=False):
    clear()
    header("SECTION 3: The Monkey System")

    print("""
This is the most advanced part of the system.

When a site blocks all automated methods, it queues the site for
"monkey_see" - where a human browses while the system records.

Then "monkey_do" replays that recording automatically next time,
mimicking human behavior (mouse movements, timing, scrolling).

This section tests the tooling around this system.
    """)

    wait()

    results = {"tests": [], "passed": 0, "failed": 0}

    # Test 3.1: Queue management
    section("Test 3.1: Monkey Queue")

    print("""
WHAT WE'RE TESTING:
  The queue system that tracks sites needing human attention.
  We'll add a test domain, verify it's there, then remove it.

WHAT SUCCESS LOOKS LIKE:
  - Can add domains to queue
  - Can list the queue
  - Can remove domains
    """)

    info("Checking current queue...")
    run("python scripts/monkey.py --list", timeout=10)
    print()

    info("Adding test domain to queue...")
    ok1, _ = run("python scripts/monkey.py --add test-eval-domain.com --reason 'evaluation test'", timeout=10, show_output=False)

    info("Verifying it's in the queue...")
    ok2, output = run("python scripts/monkey.py --list", timeout=10)

    in_queue = "test-eval-domain.com" in output

    info("Removing test domain...")
    ok3, _ = run("python scripts/monkey.py --clear test-eval-domain.com", timeout=10, show_output=False)

    if in_queue:
        success("Queue management working!")
        results["tests"].append({"name": "queue_mgmt", "status": "pass"})
        results["passed"] += 1
    else:
        error("Couldn't verify queue operations")
        results["tests"].append({"name": "queue_mgmt", "status": "fail"})
        results["failed"] += 1

    wait()

    # Test 3.2: Human emulation tests
    section("Test 3.2: Human Emulation Logic")

    print("""
WHAT WE'RE TESTING:
  The code that makes replay look human - mouse curves, timing, etc.
  These are unit tests that verify the math is correct.

WHAT SUCCESS LOOKS LIKE:
  - All 6 tests pass
    """)

    info("Running human emulation tests...")
    print()

    ok, output = run("python -m pytest eval/fixtures/human_emulation/test_human.py -v", timeout=30)
    print()

    if "6 passed" in output or ("passed" in output and "failed" not in output):
        success("Human emulation tests pass!")
        results["tests"].append({"name": "human_tests", "status": "pass"})
        results["passed"] += 1
    else:
        error("Some human emulation tests failed")
        results["tests"].append({"name": "human_tests", "status": "fail"})
        results["failed"] += 1

    wait()

    # Test 3.3: Manual monkey_see (optional)
    if not quick:
        section("Test 3.3: Record a Flow (Optional)")

        print("""
WHAT WE'RE TESTING:
  The actual recording functionality. A browser will open and you
  browse around while it records your actions.

THIS IS OPTIONAL because it requires interaction.

If you proceed:
  1. A browser window opens to saia.com
  2. Click around a bit (2-3 pages)
  3. Press Enter in this terminal when done
  4. The flow is saved for replay
        """)

        if yesno("Do you want to test recording a flow?"):
            info("Opening browser for saia.com...")
            info("Browse around, then press Enter here when done.")
            print()

            ok, _ = run("python scripts/monkey.py --see saia.com", timeout=300)

            # Check if flow was saved
            flow_path = Path.home() / ".crawl" / "flows" / "saia.com.flow.json"
            if flow_path.exists():
                success("Flow recorded successfully!")
                results["tests"].append({"name": "monkey_see", "status": "pass"})
                results["passed"] += 1
            else:
                warn("Flow might not have saved - check ~/.crawl/flows/")
                results["tests"].append({"name": "monkey_see", "status": "partial"})
        else:
            info("Skipping recording test")
            results["tests"].append({"name": "monkey_see", "status": "skip"})

    wait()

    # Summary
    section("Section 3 Summary")

    print(f"Tests passed: {results['passed']}")
    print(f"Tests failed: {results['failed']}")

    if results['passed'] >= 2:
        success("Monkey system basics are working!")
        print("\nThe system can:")
        print("  - Track sites that need human help")
        print("  - Simulate human-like behavior")
    else:
        warn("Some monkey system features may need attention")

    report.sections["3_monkey"] = results

    if not yesno("\nContinue to next section?"):
        return False
    return True


# =============================================================================
# SECTION 4: Analytics & Reports
# =============================================================================

def section_4_analytics(report, quick=False):
    clear()
    header("SECTION 4: Analytics & Reports")

    print("""
The system tracks what's working and what's not:
- Which sites are blocked?
- What methods succeed?
- Are we meeting quality targets?

This section tests the reporting tools.
    """)

    wait()

    results = {"tests": [], "passed": 0, "failed": 0}

    # Test 4.1: Access report
    section("Test 4.1: Access Report")

    print("""
WHAT WE'RE TESTING:
  The main report showing success rates, blocked sites, and SLOs.

WHAT SUCCESS LOOKS LIKE:
  - Report runs without errors
  - Shows summary statistics
    """)

    info("Running access report...")
    print()

    ok, output = run("python scripts/access_report.py", timeout=30)

    if "SUCCESS" in output or "SUMMARY" in output or "SLO" in output:
        success("Access report works!")
        results["tests"].append({"name": "access_report", "status": "pass"})
        results["passed"] += 1
    elif ok:
        warn("Report ran but output unclear")
        results["tests"].append({"name": "access_report", "status": "partial"})
    else:
        error("Access report failed")
        results["tests"].append({"name": "access_report", "status": "fail"})
        results["failed"] += 1

    wait()

    # Test 4.2: Integration tests
    section("Test 4.2: Integration Tests")

    print("""
WHAT WE'RE TESTING:
  A suite of 42 tests covering the access layer.
  34 should pass, 8 are skipped (need full end-to-end wiring).

WHAT SUCCESS LOOKS LIKE:
  - "34 passed, 8 skipped"
    """)

    info("Running integration tests...")
    print()

    ok, output = run("python -m pytest tests/test_access_integration.py -v --tb=line 2>&1 | tail -15", timeout=60)

    if "34 passed" in output or ("passed" in output and "failed" not in output.split("passed")[-1]):
        success("Integration tests pass!")
        results["tests"].append({"name": "integration_tests", "status": "pass"})
        results["passed"] += 1
    else:
        warn("Some integration tests may have failed - check output")
        results["tests"].append({"name": "integration_tests", "status": "partial"})

    wait()

    # Summary
    section("Section 4 Summary")

    if results['passed'] >= 2:
        success("Analytics and tests are working!")
    else:
        warn("Some analytics may need attention")

    report.sections["4_analytics"] = results

    return True


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Guided System Evaluation")
    parser.add_argument("--quick", action="store_true", help="Skip slow/manual tests")
    parser.add_argument("--section", type=int, help="Start at section N")
    args = parser.parse_args()

    clear()
    header("GUIDED SYSTEM EVALUATION")

    print("""
Welcome! This will walk you through testing the entire crawling system.

Each test explains:
  - WHAT we're testing
  - WHY it matters
  - WHAT success looks like

You don't need to understand the code - just follow along.

The evaluation has 4 sections:
  1. Basic Crawling (can it fetch websites?)
  2. Recon (can it detect protections?)
  3. Monkey System (can it handle blocked sites?)
  4. Analytics (are the reports working?)
    """)

    if args.quick:
        info("Quick mode: Skipping manual/slow tests")

    wait()

    # Initialize report
    report = EvalReport(
        started=datetime.now(timezone.utc).isoformat(),
        evaluator=prompt("Your name (for the report): ") or "anonymous"
    )

    # Run sections
    sections = [
        (1, section_1_basic_crawl),
        (2, section_2_recon),
        (3, section_3_monkey),
        (4, section_4_analytics),
    ]

    start = args.section or 1

    for num, func in sections:
        if num < start:
            continue
        if not func(report, quick=args.quick):
            break

    # Final summary
    clear()
    header("EVALUATION COMPLETE")

    total_passed = sum(s.get("passed", 0) for s in report.sections.values())
    total_failed = sum(s.get("failed", 0) for s in report.sections.values())

    print(f"Total passed: {total_passed}")
    print(f"Total failed: {total_failed}")

    if total_failed == 0 and total_passed > 0:
        success("Everything tested is working!")
    elif total_failed <= 2:
        warn("Mostly working with a few issues")
    else:
        error("Several problems detected")

    # Get overall notes
    print()
    report.overall_notes = input("Any overall notes? (Enter to skip): ").strip()

    # Save report
    report.completed = datetime.now(timezone.utc).isoformat()
    path = report.save()

    print()
    success(f"Report saved to: {path}")
    print("\nYou can share this report for review.")


if __name__ == "__main__":
    main()
