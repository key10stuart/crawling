#!/usr/bin/env python3
"""
Interactive Evaluation CLI for Comp Packages Extraction.

Opens browser tabs (extracted HTML report + live site) and collects scores via CLI.
Shows homepage first, then any comp/recruiting pages found.

Usage:
    # Run interactive evaluation with auto-generated sample
    python scripts/eval_interactive.py

    # Run with existing sample
    python scripts/eval_interactive.py --sample eval/sample_2026-01-26.json

    # Limit to N sites
    python scripts/eval_interactive.py --limit 5

    # Resume from a specific site index
    python scripts/eval_interactive.py --start 3

    # Only show pages with classified page_type (reduces noise)
    python scripts/eval_interactive.py --page-type-only

    # Limit comp pages per site (e.g., max 3)
    python scripts/eval_interactive.py --max-comp-pages 3
"""

import argparse
import json
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.human_eval import (
    generate_sample,
    load_site,
    CRITERIA,
    MAX_SCORE,
    PASS_THRESHOLD_AVG,
    PASS_THRESHOLD_MIN,
)
from scripts.render_extraction import _render_html

SITES_DIR = Path(__file__).parent.parent / "corpus" / "sites"
REPORTS_DIR = Path(__file__).parent.parent / "corpus" / "reports"
EVAL_DIR = Path(__file__).parent.parent / "eval"

# Patterns that indicate comp/recruiting pages (strong signals)
COMP_URL_PATTERNS_STRONG = [
    r'/careers?(?:/|$)',
    r'/jobs?(?:/|$)',
    r'/owner-?operators?',
    r'/recruiting',
    r'/employment',
    r'/apply(?:/|$)',
    r'/benefits(?:/|$)',
    r'/pay(?:/|$)',
    r'/compensation',
    r'/join(?:-us|-our-team)?(?:/|$)',
    r'/work-?(with|for|at)-us',
    r'/driver-?(?:jobs|careers|pay|benefits|application)',
]

# Weaker patterns - only match if NOT in /blog/ path
COMP_URL_PATTERNS_WEAK = [
    r'/drivers?(?:/|$)',
    r'/driving(?:/|$)',
]

# Patterns to exclude (blog posts about driving that aren't comp-related)
COMP_URL_EXCLUDE = [
    r'/blog/',
    r'/news/',
    r'/press/',
    r'/article/',
    r'/driving-change',  # Werner's safety blog series
    r'/driving-towards',  # sustainability content
]

COMP_PATTERN_STRONG_RE = re.compile('|'.join(COMP_URL_PATTERNS_STRONG), re.IGNORECASE)
COMP_PATTERN_WEAK_RE = re.compile('|'.join(COMP_URL_PATTERNS_WEAK), re.IGNORECASE)
COMP_EXCLUDE_RE = re.compile('|'.join(COMP_URL_EXCLUDE), re.IGNORECASE)


def find_comp_pages(site: dict) -> list[dict]:
    """Find pages that look like comp/recruiting content."""
    pages = site.get("pages", [])
    comp_pages = []

    for page in pages:
        url = page.get("url", "")
        page_type = page.get("page_type", "")

        # Check exclusions first (blog posts, news, etc.)
        if COMP_EXCLUDE_RE.search(url):
            # Skip unless it's a strong match (e.g., /blog/careers/ somehow)
            if not COMP_PATTERN_STRONG_RE.search(url):
                continue

        # Match by strong URL pattern (always include)
        if COMP_PATTERN_STRONG_RE.search(url):
            comp_pages.append(page)
            continue

        # Match by weak URL pattern (only if not excluded)
        if COMP_PATTERN_WEAK_RE.search(url) and not COMP_EXCLUDE_RE.search(url):
            comp_pages.append(page)
            continue

        # Match by page type if classified
        if page_type in ("careers", "recruiting", "drivers", "benefits"):
            comp_pages.append(page)

    return comp_pages


def find_homepage(site: dict) -> dict | None:
    """Find the homepage (usually first page or root URL)."""
    pages = site.get("pages", [])
    if not pages:
        return None

    # Look for root URL first
    domain = site.get("domain", "")
    for page in pages:
        url = page.get("url", "")
        # Root paths: /, /en, /en-us, /home
        if re.match(rf'^https?://[^/]*{re.escape(domain)}/?(?:en(?:-us)?/?|home/?)?$', url, re.IGNORECASE):
            return page

    # Fall back to first page
    return pages[0]


def render_page_report(site: dict, page: dict, suffix: str = "") -> Path:
    """Render HTML report for a specific page."""
    domain = site.get("domain", "site").replace(".", "_")
    html = _render_html(site, page, show_open_original=True)

    # Sanitize suffix: only alphanumeric and underscores, truncate to 50 chars
    safe_suffix = re.sub(r'[^a-z0-9]+', '_', suffix.lower()).strip('_')[:50]

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{domain}_{safe_suffix}.html"
    report_path.write_text(html, encoding="utf-8")

    # Verify file exists before returning (defensive)
    if not report_path.exists():
        raise RuntimeError(f"Failed to write report: {report_path}")

    return report_path


def prompt_score(criterion: str, max_val: int, levels: dict) -> int | None:
    """Prompt user for a score with rubric displayed. Returns None for N/A."""
    print(f"\n  {criterion.upper()} (0-{max_val}, or 'na'):")
    for score, desc in levels.items():
        print(f"    {score}: {desc}")

    while True:
        try:
            val = input(f"  Enter {criterion} score [0-{max_val}/na]: ").strip().lower()
            if val == "":
                return -1  # skip entirely
            if val == "na" or val == "n/a":
                return None  # not applicable
            score = int(val)
            if 0 <= score <= max_val:
                return score
            print(f"    Invalid. Enter 0-{max_val} or 'na'.")
        except ValueError:
            print("    Invalid. Enter a number or 'na'.")
        except (KeyboardInterrupt, EOFError):
            return -1


def eval_page(site: dict, page: dict, page_label: str) -> dict | None:
    """
    Evaluate a single page. Returns scores dict or None if skipped.
    """
    url = page.get("url", "")
    title = page.get("title", "Untitled")
    word_count = page.get("word_count", 0)

    print(f"\n  {'─' * 50}")
    print(f"  PAGE: {page_label}")
    print(f"  URL: {url}")
    print(f"  Title: {title}")
    print(f"  Words: {word_count}")
    print(f"  {'─' * 50}")

    # Render and open
    suffix = page_label.lower().replace(" ", "_").replace("/", "_")
    report_path = render_page_report(site, page, suffix)

    print(f"  Opening tabs...")
    webbrowser.open(f"file://{report_path.absolute()}")
    webbrowser.open(url)

    print(f"\n  Compare extraction against live page.")
    print(f"  Press Enter when ready to score, 's' to skip page...")

    try:
        ready = input("  > ").strip().lower()
        if ready == "s":
            print("  Skipped page.")
            return None
    except (KeyboardInterrupt, EOFError):
        return None

    # Collect scores
    page_scores = {
        "url": url,
        "page_label": page_label,
    }

    for criterion, info in CRITERIA.items():
        score = prompt_score(criterion, info["max"], info["levels"])
        if score == -1:  # hard skip
            return None
        page_scores[criterion] = score  # None means N/A

    # Notes
    print("\n  Notes (optional, press Enter to skip):")
    try:
        notes = input("  > ").strip()
        if notes:
            page_scores["notes"] = notes
    except (KeyboardInterrupt, EOFError):
        pass

    # Calculate total (excluding N/A)
    applicable_scores = [
        page_scores.get(c) for c in CRITERIA.keys()
        if page_scores.get(c) is not None
    ]
    if applicable_scores:
        page_scores["total"] = sum(applicable_scores)
        page_scores["max_possible"] = sum(
            CRITERIA[c]["max"] for c in CRITERIA.keys()
            if page_scores.get(c) is not None
        )
    else:
        page_scores["total"] = None
        page_scores["max_possible"] = None

    return page_scores


def run_interactive_eval(
    sample: dict,
    start_index: int = 0,
    limit: int | None = None,
    page_type_only: bool = False,
    max_comp_pages: int | None = None,
) -> list[dict]:
    """
    Run interactive evaluation session.

    For each site: shows homepage first, then any comp pages found.

    Args:
        page_type_only: If True, only show pages with classified page_type
        max_comp_pages: Limit comp pages per site (None = unlimited)
    """
    sites = sample.get("sites", [])
    if limit:
        sites = sites[:limit]

    all_scores = []
    total = len(sites)

    print("\n" + "=" * 60)
    print("INTERACTIVE EVALUATION SESSION")
    print("=" * 60)
    print(f"\nSites to evaluate: {total}")
    print("For each site:")
    print("  1. Homepage is shown first")
    print("  2. Then any comp/recruiting pages found")
    print("  3. Score each page (or 'na' if criterion doesn't apply)")
    print("\nPress Enter to start, Ctrl+C to quit...")

    try:
        input()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        return all_scores

    for i, site_info in enumerate(sites[start_index:], start=start_index + 1):
        domain = site_info["domain"]
        print(f"\n{'═' * 60}")
        print(f"SITE {i}/{total}: {domain}")
        print(f"Type: {site_info.get('sample_type', 'unknown')} | Tier: {site_info.get('tier', '?')}")
        print("═" * 60)

        # Load site data
        site = load_site(domain)
        if not site or not site.get("pages"):
            print(f"  ⚠ No crawl data found for {domain}, skipping.")
            continue

        # Find pages to evaluate
        homepage = find_homepage(site)
        comp_pages = find_comp_pages(site)

        # Remove homepage from comp_pages if it's there
        if homepage:
            comp_pages = [p for p in comp_pages if p.get("url") != homepage.get("url")]

        # Apply page_type filter if requested
        if page_type_only:
            comp_pages = [p for p in comp_pages
                          if p.get("page_type") in ("careers", "recruiting", "drivers", "benefits")]

        # Apply max_comp_pages limit if set
        if max_comp_pages is not None and len(comp_pages) > max_comp_pages:
            comp_pages = comp_pages[:max_comp_pages]

        print(f"\n  Found: 1 homepage + {len(comp_pages)} comp page(s)")

        site_scores = {
            "domain": domain,
            "tier": site_info.get("tier"),
            "sample_type": site_info.get("sample_type"),
            "pages": [],
        }

        # Evaluate homepage
        if homepage:
            print(f"\n  [1/{1 + len(comp_pages)}] HOMEPAGE")
            page_result = eval_page(site, homepage, "Homepage")
            if page_result:
                site_scores["pages"].append(page_result)

        # Evaluate comp pages
        for j, comp_page in enumerate(comp_pages, start=1):
            url = comp_page.get("url", "")
            # Extract path for label
            path = url.split(domain)[-1] if domain in url else url
            label = f"Comp {j}: {path[:40]}"

            print(f"\n  [{1 + j}/{1 + len(comp_pages)}] {label}")
            page_result = eval_page(site, comp_page, label)
            if page_result:
                site_scores["pages"].append(page_result)

            # Option to skip remaining comp pages
            if j < len(comp_pages):
                print(f"\n  {len(comp_pages) - j} more comp page(s). Continue? [Enter=yes, 'n'=skip to next site]")
                try:
                    cont = input("  > ").strip().lower()
                    if cont == "n":
                        break
                except (KeyboardInterrupt, EOFError):
                    break

        # Site summary
        if site_scores["pages"]:
            all_scores.append(site_scores)
            page_count = len(site_scores["pages"])
            print(f"\n  ✓ Recorded {page_count} page(s) for {domain}")
        else:
            print(f"\n  No pages scored for {domain}")

        print(f"\n  Continue to next site? [Enter=yes, 'q'=quit and save]")
        try:
            cont = input("  > ").strip().lower()
            if cont == "q":
                break
        except (KeyboardInterrupt, EOFError):
            break

    return all_scores


def compute_site_summary(site_scores: dict) -> dict:
    """Compute aggregate scores for a site."""
    pages = site_scores.get("pages", [])
    if not pages:
        return {"error": "no pages"}

    # Aggregate by criterion
    criterion_totals = {c: [] for c in CRITERIA.keys()}

    for page in pages:
        for criterion in CRITERIA.keys():
            val = page.get(criterion)
            if val is not None:  # exclude N/A
                criterion_totals[criterion].append(val)

    summary = {}
    for criterion, values in criterion_totals.items():
        if values:
            summary[f"{criterion}_avg"] = round(sum(values) / len(values), 2)
            summary[f"{criterion}_count"] = len(values)
        else:
            summary[f"{criterion}_avg"] = None

    # Overall
    all_totals = [p["total"] for p in pages if p.get("total") is not None]
    all_max = [p["max_possible"] for p in pages if p.get("max_possible") is not None]

    if all_totals and all_max:
        summary["total_points"] = sum(all_totals)
        summary["max_points"] = sum(all_max)
        summary["pct"] = round(100 * sum(all_totals) / sum(all_max), 1)

    return summary


def save_results(all_scores: list[dict], out_path: Path) -> dict:
    """Save scores and generate report."""
    # Add summaries
    for site_scores in all_scores:
        site_scores["summary"] = compute_site_summary(site_scores)

    # Overall summary
    site_pcts = [s["summary"]["pct"] for s in all_scores if s.get("summary", {}).get("pct")]

    result = {
        "evaluated_at": datetime.now().isoformat(),
        "sites_evaluated": len(all_scores),
        "overall": {
            "avg_pct": round(sum(site_pcts) / len(site_pcts), 1) if site_pcts else None,
            "min_pct": min(site_pcts) if site_pcts else None,
            "max_pct": max(site_pcts) if site_pcts else None,
        },
        "sites": all_scores,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    return result


def print_report(result: dict):
    """Print formatted evaluation report."""
    print("\n" + "=" * 60)
    print("EVALUATION REPORT")
    print("=" * 60)

    overall = result.get("overall", {})
    print(f"\nSites evaluated: {result.get('sites_evaluated', 0)}")
    print(f"Average score:   {overall.get('avg_pct', 'N/A')}%")
    print(f"Min score:       {overall.get('min_pct', 'N/A')}%")
    print(f"Max score:       {overall.get('max_pct', 'N/A')}%")

    print(f"\n{'─' * 60}")
    print("Per-site breakdown:")
    print(f"{'─' * 60}")

    for site in result.get("sites", []):
        domain = site.get("domain", "?")
        summary = site.get("summary", {})
        pct = summary.get("pct", "N/A")
        pages = len(site.get("pages", []))
        print(f"  {domain}: {pct}% ({pages} pages)")

    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Interactive evaluation CLI")
    parser.add_argument("--sample", type=Path, help="Path to sample JSON (generates new if not provided)")
    parser.add_argument("--out", type=Path, help="Output path for scores (default: eval/interactive_<timestamp>.json)")
    parser.add_argument("--limit", type=int, help="Limit to first N sites")
    parser.add_argument("--start", type=int, default=0, help="Start from site index (0-based)")
    parser.add_argument("--n-random", type=int, default=10, help="Random samples if generating")
    parser.add_argument("--n-targeted", type=int, default=5, help="Targeted samples if generating")
    parser.add_argument("--n-edge", type=int, default=5, help="Edge case samples if generating")
    parser.add_argument("--page-type-only", action="store_true",
                        help="Only show pages with classified page_type (careers, recruiting, etc.)")
    parser.add_argument("--max-comp-pages", type=int, default=None,
                        help="Limit comp pages per site (default: unlimited)")
    args = parser.parse_args()

    # Load or generate sample
    if args.sample and args.sample.exists():
        with open(args.sample) as f:
            sample = json.load(f)
        print(f"Loaded sample from {args.sample}")
    else:
        print("Generating sample set...")
        sample = generate_sample(
            n_random=args.n_random,
            n_targeted=args.n_targeted,
            n_edge=args.n_edge,
        )
        if sample.get("error"):
            print(f"Error: {sample['error']}")
            sys.exit(1)
        print(f"Generated {sample['counts']['total']} sites for evaluation")

    # Run interactive session
    scores = run_interactive_eval(
        sample,
        start_index=args.start,
        limit=args.limit,
        page_type_only=args.page_type_only,
        max_comp_pages=args.max_comp_pages,
    )

    if not scores:
        print("\nNo scores collected.")
        sys.exit(0)

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.out or (EVAL_DIR / f"interactive_{timestamp}.json")
    result = save_results(scores, out_path)

    print(f"\nResults saved to {out_path}")
    print_report(result)


if __name__ == "__main__":
    main()
