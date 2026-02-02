#!/usr/bin/env python3
"""
Extraction Quality Evaluation

Side-by-side comparison of original HTML vs extracted content.
Grade extraction quality on completeness, precision, and structure.

Usage:
    python scripts/eval_extraction.py                    # Interactive mode
    python scripts/eval_extraction.py --domain saia.com  # Specific domain
    python scripts/eval_extraction.py --crawl            # Fresh crawl first
    python scripts/eval_extraction.py --sample 5         # Evaluate 5 pages
    python scripts/eval_extraction.py --report           # View last report

    # Auto mode - run at scale without prompts
    python scripts/eval_extraction.py --auto                      # All available crawls
    python scripts/eval_extraction.py --auto --tier 1             # Tier-1 carriers only
    python scripts/eval_extraction.py --auto --tier 1 --sample 10 # 10 pages per site
    python scripts/eval_extraction.py --auto --jobs 4             # Parallel processing
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import webbrowser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fetch.extractor import extract_content, STRIP_TAGS, STRIP_CLASSES
from fetch.config import FetchConfig

CORPUS_DIR = Path(__file__).parent.parent / "corpus"
SEEDS_FILE = Path(__file__).parent.parent / "seeds" / "trucking_carriers.json"
REPORTS_DIR = CORPUS_DIR / "eval_reports"

# Boilerplate markers that indicate junk content
BOILERPLATE_MARKERS = [
    r'\bcookie\b', r'\bprivacy policy\b', r'\bterms of (use|service)\b',
    r'\bsubscribe\b', r'\bnewsletter\b', r'\bfollow us\b', r'\bsocial media\b',
    r'\ball rights reserved\b', r'\bcopyright\b', r'\bcontact us\b',
    r'\bsite map\b', r'\bsitemap\b', r'\baccessibility\b',
]
BOILERPLATE_RE = re.compile('|'.join(BOILERPLATE_MARKERS), re.IGNORECASE)


# =============================================================================
# AUTO-SCORING HEURISTICS
# =============================================================================

def auto_score_completeness(html: str, extracted: str, word_count: int) -> tuple[float, list[str]]:
    """
    Estimate completeness score (1-5) based on heuristics.

    Returns (score, reasons).
    """
    reasons = []
    score = 3.0  # Start neutral

    html_len = len(html)
    extracted_len = len(extracted)

    # Word count thresholds
    if word_count >= 500:
        score += 1.0
        reasons.append(f"good word count ({word_count})")
    elif word_count >= 200:
        score += 0.5
        reasons.append(f"decent word count ({word_count})")
    elif word_count < 50:
        score -= 1.5
        reasons.append(f"very low word count ({word_count})")
    elif word_count < 100:
        score -= 0.5
        reasons.append(f"low word count ({word_count})")

    # Extraction ratio (extracted chars / html chars)
    if html_len > 0:
        ratio = extracted_len / html_len
        if 0.05 <= ratio <= 0.4:
            score += 0.5
            reasons.append(f"healthy extraction ratio ({ratio:.1%})")
        elif ratio < 0.01:
            score -= 1.0
            reasons.append(f"very low extraction ratio ({ratio:.1%})")
        elif ratio > 0.5:
            score -= 0.5
            reasons.append(f"suspiciously high ratio ({ratio:.1%})")

    # Check for headings in extracted text
    if re.search(r'\n[A-Z][^.!?]*\n', extracted):
        score += 0.25
        reasons.append("has heading-like text")

    return max(1.0, min(5.0, score)), reasons


def auto_score_precision(extracted: str, link_density: float, word_count: int) -> tuple[float, list[str]]:
    """
    Estimate precision score (1-5) based on heuristics.

    Returns (score, reasons).
    """
    reasons = []
    score = 3.5  # Start slightly positive

    # Link density penalty
    if link_density > 0.5:
        score -= 1.5
        reasons.append(f"very high link density ({link_density:.2f})")
    elif link_density > 0.3:
        score -= 0.75
        reasons.append(f"high link density ({link_density:.2f})")
    elif link_density < 0.1:
        score += 0.5
        reasons.append(f"low link density ({link_density:.2f})")

    # Boilerplate marker count
    boilerplate_matches = BOILERPLATE_RE.findall(extracted.lower())
    bp_count = len(boilerplate_matches)
    if bp_count == 0:
        score += 0.5
        reasons.append("no boilerplate markers")
    elif bp_count <= 2:
        pass  # neutral
    elif bp_count <= 5:
        score -= 0.5
        reasons.append(f"some boilerplate ({bp_count} markers)")
    else:
        score -= 1.0
        reasons.append(f"lots of boilerplate ({bp_count} markers)")

    # Check for repeated phrases (sign of nav/footer duplication)
    words = extracted.lower().split()
    if len(words) > 20:
        # Look for repeated 3-grams
        trigrams = [' '.join(words[i:i+3]) for i in range(len(words)-2)]
        trigram_counts = Counter(trigrams)
        repeated = sum(1 for t, c in trigram_counts.items() if c > 2)
        if repeated > 5:
            score -= 0.5
            reasons.append(f"repeated phrases ({repeated})")

    return max(1.0, min(5.0, score)), reasons


def auto_score_structure(extracted: str, word_count: int) -> tuple[float, list[str]]:
    """
    Estimate structure score (1-5) based on heuristics.

    Returns (score, reasons).
    """
    reasons = []
    score = 3.0  # Start neutral

    if word_count < 20:
        return 2.0, ["too little text to assess structure"]

    # Paragraph analysis
    paragraphs = [p.strip() for p in extracted.split('\n\n') if p.strip()]
    if len(paragraphs) >= 3:
        score += 0.5
        reasons.append(f"has {len(paragraphs)} paragraphs")
    elif len(paragraphs) == 1:
        score -= 0.5
        reasons.append("single block of text")

    # Sentence analysis
    sentences = re.split(r'[.!?]+', extracted)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

    if sentences:
        avg_sentence_len = sum(len(s.split()) for s in sentences) / len(sentences)
        if 10 <= avg_sentence_len <= 25:
            score += 0.5
            reasons.append(f"good sentence length (avg {avg_sentence_len:.0f} words)")
        elif avg_sentence_len < 5:
            score -= 0.75
            reasons.append(f"very short sentences (avg {avg_sentence_len:.0f} words)")
        elif avg_sentence_len > 40:
            score -= 0.5
            reasons.append(f"very long sentences (avg {avg_sentence_len:.0f} words)")

    # Check for garbled text (lots of special chars, no spaces)
    special_ratio = len(re.findall(r'[^\w\s]', extracted)) / max(len(extracted), 1)
    if special_ratio > 0.15:
        score -= 0.5
        reasons.append(f"high special char ratio ({special_ratio:.1%})")

    # Check for coherence (sentences start with capital, end with punctuation)
    well_formed = sum(1 for s in sentences if s and s[0].isupper())
    if sentences and well_formed / len(sentences) > 0.7:
        score += 0.25
        reasons.append("well-formed sentences")

    return max(1.0, min(5.0, score)), reasons


def auto_grade_extraction(html: str, extraction_result) -> dict:
    """
    Automatically grade an extraction using heuristics.

    Returns dict with scores and reasoning.
    """
    text = extraction_result.text or ""
    word_count = len(text.split()) if text else 0
    link_density = extraction_result.link_density

    comp_score, comp_reasons = auto_score_completeness(html, text, word_count)
    prec_score, prec_reasons = auto_score_precision(text, link_density, word_count)
    struct_score, struct_reasons = auto_score_structure(text, word_count)

    avg_score = (comp_score + prec_score + struct_score) / 3

    return {
        "completeness": round(comp_score, 2),
        "precision": round(prec_score, 2),
        "structure": round(struct_score, 2),
        "average": round(avg_score, 2),
        "reasons": {
            "completeness": comp_reasons,
            "precision": prec_reasons,
            "structure": struct_reasons,
        },
        "stats": {
            "html_chars": len(html),
            "extracted_chars": len(text),
            "word_count": word_count,
            "link_density": round(link_density, 3),
            "method": extraction_result.method,
        }
    }


def load_seeds() -> list[dict]:
    """Load carrier seeds."""
    if not SEEDS_FILE.exists():
        return []
    with open(SEEDS_FILE) as f:
        data = json.load(f)
    return data.get("carriers", [])


def get_available_crawls() -> list[str]:
    """Get domains with existing crawl data."""
    sites_dir = CORPUS_DIR / "sites"
    if not sites_dir.exists():
        return []
    domains = []
    for f in sites_dir.glob("*.json"):
        if not f.name.endswith("_summary.json"):
            domain = f.stem.replace("_", ".")
            domains.append(domain)
    return sorted(domains)


def get_raw_html_files(domain: str) -> list[Path]:
    """Get raw HTML files for a domain."""
    raw_dir = CORPUS_DIR / "raw" / domain
    if not raw_dir.exists():
        return []
    return sorted(raw_dir.glob("*.html"))


def load_site_data(domain: str) -> dict | None:
    """Load site crawl data."""
    domain_slug = domain.replace(".", "_").replace("-", "_")
    site_file = CORPUS_DIR / "sites" / f"{domain_slug}.json"
    if not site_file.exists():
        # Try with dashes
        domain_slug = domain.replace(".", "_")
        site_file = CORPUS_DIR / "sites" / f"{domain_slug}.json"
    if not site_file.exists():
        return None
    with open(site_file) as f:
        return json.load(f)


def run_crawl(domain: str, depth: int = 0) -> bool:
    """Run a crawl for the domain."""
    print(f"\nCrawling {domain} (depth={depth})...")
    try:
        result = subprocess.run(
            ["python", "scripts/crawl.py", "--domain", domain, "--depth", str(depth)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            print("Crawl complete.")
            return True
        else:
            print(f"Crawl failed: {result.stderr[:500]}")
            return False
    except subprocess.TimeoutExpired:
        print("Crawl timed out.")
        return False
    except Exception as e:
        print(f"Crawl error: {e}")
        return False


def open_in_browser(html_content: str, title: str = "Original HTML"):
    """Open HTML content in browser for visual comparison."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write(html_content)
        temp_path = f.name
    webbrowser.open(f"file://{temp_path}")
    print(f"  Opened in browser: {title}")


def show_extraction_comparison(html: str, page_url: str) -> dict:
    """Show original vs extracted and collect grades."""

    print("\n" + "=" * 70)
    print(f"  PAGE: {page_url}")
    print("=" * 70)

    # Extract content
    config = FetchConfig()
    result = extract_content(html, config)

    # Stats
    original_len = len(html)
    extracted_len = len(result.text) if result.text else 0
    extracted_words = len(result.text.split()) if result.text else 0

    print(f"\n  Original HTML: {original_len:,} chars")
    print(f"  Extracted text: {extracted_len:,} chars, {extracted_words:,} words")
    print(f"  Extraction method: {result.method}")
    print(f"  Link density: {result.link_density:.2f}")
    if result.title:
        print(f"  Title: {result.title[:80]}...")

    # Show extracted preview
    print("\n  --- EXTRACTED CONTENT (first 1000 chars) ---")
    preview = result.text[:1000] if result.text else "(empty)"
    # Clean up for display
    preview = ' '.join(preview.split())
    print(f"  {preview}...")

    # Options
    print("\n  Options:")
    print("    [b] Open original in browser")
    print("    [e] Show more extracted text")
    print("    [g] Grade this extraction")
    print("    [s] Skip this page")
    print("    [q] Quit evaluation")

    while True:
        choice = input("\n  Choice: ").strip().lower()

        if choice == 'b':
            open_in_browser(html, f"Original: {page_url}")

        elif choice == 'e':
            print("\n  --- FULL EXTRACTED TEXT ---")
            print(result.text if result.text else "(empty)")
            print("  --- END ---")

        elif choice == 'g':
            return collect_grades(page_url, result, html)

        elif choice == 's':
            return {"status": "skip", "url": page_url}

        elif choice == 'q':
            return {"status": "quit"}

        else:
            print("  Invalid choice. Try again.")


def collect_grades(url: str, extraction_result, html: str) -> dict:
    """Collect grades for an extraction."""

    print("\n  --- GRADING ---")
    print("  Rate each dimension 1-5:")
    print("    1 = Poor (missed most content / full of junk)")
    print("    2 = Below average")
    print("    3 = Acceptable")
    print("    4 = Good")
    print("    5 = Excellent (captured everything important, no junk)")

    grades = {}

    # Completeness
    print("\n  COMPLETENESS: Did it capture the important content?")
    print("    - Main text/articles")
    print("    - Key information (contact, services, etc.)")
    print("    - Important details")
    while True:
        try:
            score = int(input("  Completeness (1-5): "))
            if 1 <= score <= 5:
                grades["completeness"] = score
                break
        except ValueError:
            pass
        print("  Enter a number 1-5")

    # Precision
    print("\n  PRECISION: Did it avoid junk content?")
    print("    - No navigation menus")
    print("    - No cookie banners / popups")
    print("    - No boilerplate footer text")
    while True:
        try:
            score = int(input("  Precision (1-5): "))
            if 1 <= score <= 5:
                grades["precision"] = score
                break
        except ValueError:
            pass
        print("  Enter a number 1-5")

    # Structure
    print("\n  STRUCTURE: Is the text coherent and readable?")
    print("    - Logical flow")
    print("    - Reasonable paragraph breaks")
    print("    - Not jumbled/garbled")
    while True:
        try:
            score = int(input("  Structure (1-5): "))
            if 1 <= score <= 5:
                grades["structure"] = score
                break
        except ValueError:
            pass
        print("  Enter a number 1-5")

    # Notes
    notes = input("\n  Notes (optional, press Enter to skip): ").strip()

    # Calculate average
    avg = sum(grades.values()) / len(grades)

    return {
        "status": "graded",
        "url": url,
        "grades": grades,
        "average": round(avg, 2),
        "notes": notes if notes else None,
        "stats": {
            "html_chars": len(html),
            "extracted_chars": len(extraction_result.text) if extraction_result.text else 0,
            "extracted_words": len(extraction_result.text.split()) if extraction_result.text else 0,
            "method": extraction_result.method,
            "link_density": round(extraction_result.link_density, 3),
        }
    }


def select_domain(crawls: list[str], seeds: list[dict]) -> str | None:
    """Interactive domain selection."""

    print("\n" + "=" * 60)
    print("  SELECT DOMAIN FOR EXTRACTION EVALUATION")
    print("=" * 60)

    if crawls:
        print("\n  Existing crawls:")
        for i, domain in enumerate(crawls[:10], 1):
            # Find tier info
            tier = "?"
            for s in seeds:
                if s.get("domain") == domain:
                    tier = s.get("tier", "?")
                    break
            print(f"    {i}. {domain} (tier {tier})")
        if len(crawls) > 10:
            print(f"    ... and {len(crawls) - 10} more")

    print("\n  Options:")
    print("    [number] Select from list above")
    print("    [domain] Enter domain manually (e.g., saia.com)")
    print("    [q] Quit")

    while True:
        choice = input("\n  Domain: ").strip().lower()

        if choice == 'q':
            return None

        # Check if it's a number
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(crawls):
                return crawls[idx]
        except ValueError:
            pass

        # Check if it looks like a domain
        if '.' in choice:
            return choice

        print("  Invalid choice. Enter a number or domain name.")


def run_evaluation(domain: str, sample_size: int = 5, do_crawl: bool = False) -> dict:
    """Run extraction evaluation for a domain."""

    report = {
        "domain": domain,
        "started": datetime.now(timezone.utc).isoformat(),
        "evaluator": "user",
        "pages": [],
        "summary": {},
    }

    # Check for existing data or crawl
    site_data = load_site_data(domain)
    raw_files = get_raw_html_files(domain)

    if not site_data and not raw_files:
        if do_crawl:
            if not run_crawl(domain, depth=1):
                print("Could not crawl domain.")
                return report
            raw_files = get_raw_html_files(domain)
        else:
            print(f"\n  No existing crawl data for {domain}")
            print("  Run with --crawl to fetch first, or choose different domain.")
            return report

    if not raw_files:
        print(f"\n  No raw HTML files found for {domain}")
        print("  (Site was crawled but HTML wasn't preserved)")
        return report

    print(f"\n  Found {len(raw_files)} raw HTML files for {domain}")

    # Sample pages
    if len(raw_files) > sample_size:
        # Take first, last, and random middle ones
        import random
        middle = random.sample(raw_files[1:-1], min(sample_size - 2, len(raw_files) - 2))
        selected = [raw_files[0]] + middle + [raw_files[-1]]
    else:
        selected = raw_files

    print(f"  Evaluating {len(selected)} pages\n")

    # Evaluate each page
    for i, html_file in enumerate(selected, 1):
        print(f"\n  [{i}/{len(selected)}] ", end="")

        # Read HTML
        try:
            html = html_file.read_text(errors='replace')
        except Exception as e:
            print(f"Error reading {html_file}: {e}")
            continue

        # Reconstruct URL from filename
        page_path = html_file.stem.replace("_", "/")
        if page_path == "index":
            page_url = f"https://{domain}/"
        else:
            page_url = f"https://{domain}/{page_path}"

        # Show comparison and collect grades
        result = show_extraction_comparison(html, page_url)

        if result.get("status") == "quit":
            print("\n  Evaluation stopped early.")
            break

        report["pages"].append(result)

    # Calculate summary
    graded = [p for p in report["pages"] if p.get("status") == "graded"]
    if graded:
        avg_completeness = sum(p["grades"]["completeness"] for p in graded) / len(graded)
        avg_precision = sum(p["grades"]["precision"] for p in graded) / len(graded)
        avg_structure = sum(p["grades"]["structure"] for p in graded) / len(graded)
        avg_overall = sum(p["average"] for p in graded) / len(graded)

        report["summary"] = {
            "pages_evaluated": len(report["pages"]),
            "pages_graded": len(graded),
            "pages_skipped": len([p for p in report["pages"] if p.get("status") == "skip"]),
            "avg_completeness": round(avg_completeness, 2),
            "avg_precision": round(avg_precision, 2),
            "avg_structure": round(avg_structure, 2),
            "avg_overall": round(avg_overall, 2),
        }

    report["completed"] = datetime.now(timezone.utc).isoformat()

    return report


def save_report(report: dict) -> Path:
    """Save evaluation report."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    domain_slug = report["domain"].replace(".", "_")
    filename = f"extraction_eval_{domain_slug}_{timestamp}.json"
    filepath = REPORTS_DIR / filename

    with open(filepath, 'w') as f:
        json.dump(report, f, indent=2)

    return filepath


def show_report(report: dict):
    """Display report summary."""

    print("\n" + "=" * 60)
    print("  EXTRACTION EVALUATION REPORT")
    print("=" * 60)
    print(f"\n  Domain: {report['domain']}")
    print(f"  Started: {report['started']}")
    print(f"  Completed: {report.get('completed', 'N/A')}")

    summary = report.get("summary", {})
    if summary:
        print(f"\n  Pages evaluated: {summary.get('pages_evaluated', 0)}")
        print(f"  Pages graded: {summary.get('pages_graded', 0)}")
        print(f"  Pages skipped: {summary.get('pages_skipped', 0)}")

        print(f"\n  Average scores:")
        print(f"    Completeness: {summary.get('avg_completeness', 'N/A')}/5")
        print(f"    Precision:    {summary.get('avg_precision', 'N/A')}/5")
        print(f"    Structure:    {summary.get('avg_structure', 'N/A')}/5")
        print(f"    Overall:      {summary.get('avg_overall', 'N/A')}/5")

        # Interpret
        overall = summary.get('avg_overall', 0)
        if overall >= 4:
            print("\n  Verdict: GOOD - Extraction quality is solid")
        elif overall >= 3:
            print("\n  Verdict: ACCEPTABLE - Some room for improvement")
        elif overall >= 2:
            print("\n  Verdict: POOR - Significant extraction issues")
        else:
            print("\n  Verdict: FAILING - Extraction needs major work")

    # Show individual page results
    print("\n  Page Results:")
    for page in report.get("pages", []):
        status = page.get("status", "unknown")
        url = page.get("url", "?")
        # Truncate URL for display
        url_display = url[:50] + "..." if len(url) > 50 else url

        if status == "graded":
            avg = page.get("average", 0)
            print(f"    {avg:.1f}/5 - {url_display}")
            if page.get("notes"):
                print(f"          Note: {page['notes']}")
        elif status == "skip":
            print(f"    [SKIP] - {url_display}")


def view_last_report():
    """View the most recent extraction evaluation report."""
    if not REPORTS_DIR.exists():
        print("No reports found.")
        return

    reports = sorted(REPORTS_DIR.glob("extraction_eval_*.json"), reverse=True)
    if not reports:
        print("No extraction evaluation reports found.")
        return

    with open(reports[0]) as f:
        report = json.load(f)

    print(f"\n  Loading: {reports[0].name}")
    show_report(report)


# =============================================================================
# AUTO MODE - Large Scale Evaluation
# =============================================================================

def auto_eval_domain(domain: str, sample_size: int = 5) -> dict:
    """
    Automatically evaluate extraction quality for a domain.
    No prompts - uses heuristics for scoring.
    """
    from fetch.extractor import extract_content
    from fetch.config import FetchConfig

    result = {
        "domain": domain,
        "pages": [],
        "summary": {},
        "error": None,
    }

    raw_files = get_raw_html_files(domain)
    if not raw_files:
        result["error"] = "no_raw_files"
        return result

    # Sample pages
    import random
    if len(raw_files) > sample_size:
        selected = random.sample(raw_files, sample_size)
    else:
        selected = raw_files

    config = FetchConfig()

    for html_file in selected:
        try:
            html = html_file.read_text(errors='replace')
            extraction = extract_content(html, config)

            # Reconstruct URL
            page_path = html_file.stem.replace("_", "/")
            if page_path == "index":
                page_url = f"https://{domain}/"
            else:
                page_url = f"https://{domain}/{page_path}"

            # Auto-grade
            grades = auto_grade_extraction(html, extraction)
            grades["url"] = page_url

            result["pages"].append(grades)

        except Exception as e:
            result["pages"].append({
                "url": str(html_file),
                "error": str(e),
            })

    # Calculate summary
    graded = [p for p in result["pages"] if "average" in p]
    if graded:
        result["summary"] = {
            "pages_evaluated": len(result["pages"]),
            "pages_graded": len(graded),
            "avg_completeness": round(sum(p["completeness"] for p in graded) / len(graded), 2),
            "avg_precision": round(sum(p["precision"] for p in graded) / len(graded), 2),
            "avg_structure": round(sum(p["structure"] for p in graded) / len(graded), 2),
            "avg_overall": round(sum(p["average"] for p in graded) / len(graded), 2),
            "avg_word_count": round(sum(p["stats"]["word_count"] for p in graded) / len(graded), 0),
        }

    return result


def run_auto_evaluation(
    domains: list[str],
    sample_size: int = 5,
    jobs: int = 1,
    tier_filter: int | None = None,
) -> dict:
    """
    Run automated evaluation across multiple domains.
    """
    seeds = load_seeds()

    # Filter by tier if specified
    if tier_filter is not None:
        tier_domains = {s["domain"] for s in seeds if s.get("tier") == tier_filter}
        domains = [d for d in domains if d in tier_domains]

    print(f"\n{'='*70}")
    print(f"  AUTO EXTRACTION EVALUATION")
    print(f"{'='*70}")
    print(f"\n  Domains: {len(domains)}")
    print(f"  Sample size: {sample_size} pages per domain")
    print(f"  Parallel jobs: {jobs}")
    if tier_filter:
        print(f"  Tier filter: {tier_filter}")
    print()

    all_results = []
    completed = 0

    if jobs > 1:
        # Parallel execution
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            futures = {
                executor.submit(auto_eval_domain, domain, sample_size): domain
                for domain in domains
            }

            for future in as_completed(futures):
                domain = futures[future]
                completed += 1
                try:
                    result = future.result()
                    all_results.append(result)

                    # Progress
                    avg = result.get("summary", {}).get("avg_overall", 0)
                    pages = result.get("summary", {}).get("pages_graded", 0)
                    if avg:
                        print(f"  [{completed}/{len(domains)}] {domain}: {avg:.2f}/5 ({pages} pages)")
                    else:
                        print(f"  [{completed}/{len(domains)}] {domain}: {result.get('error', 'no data')}")

                except Exception as e:
                    print(f"  [{completed}/{len(domains)}] {domain}: ERROR - {e}")
                    all_results.append({"domain": domain, "error": str(e)})
    else:
        # Sequential execution
        for domain in domains:
            completed += 1
            result = auto_eval_domain(domain, sample_size)
            all_results.append(result)

            avg = result.get("summary", {}).get("avg_overall", 0)
            pages = result.get("summary", {}).get("pages_graded", 0)
            if avg:
                print(f"  [{completed}/{len(domains)}] {domain}: {avg:.2f}/5 ({pages} pages)")
            else:
                print(f"  [{completed}/{len(domains)}] {domain}: {result.get('error', 'no data')}")

    # Build aggregate report
    report = {
        "mode": "auto",
        "started": datetime.now(timezone.utc).isoformat(),
        "tier_filter": tier_filter,
        "sample_size": sample_size,
        "domains": all_results,
        "aggregate": {},
    }

    # Calculate aggregate stats
    valid = [r for r in all_results if r.get("summary", {}).get("avg_overall")]
    if valid:
        report["aggregate"] = {
            "domains_evaluated": len(all_results),
            "domains_with_data": len(valid),
            "total_pages": sum(r["summary"]["pages_graded"] for r in valid),
            "avg_completeness": round(sum(r["summary"]["avg_completeness"] for r in valid) / len(valid), 2),
            "avg_precision": round(sum(r["summary"]["avg_precision"] for r in valid) / len(valid), 2),
            "avg_structure": round(sum(r["summary"]["avg_structure"] for r in valid) / len(valid), 2),
            "avg_overall": round(sum(r["summary"]["avg_overall"] for r in valid) / len(valid), 2),
        }

        # Find best and worst
        sorted_by_score = sorted(valid, key=lambda x: x["summary"]["avg_overall"], reverse=True)
        report["aggregate"]["best_domains"] = [
            {"domain": r["domain"], "score": r["summary"]["avg_overall"]}
            for r in sorted_by_score[:3]
        ]
        report["aggregate"]["worst_domains"] = [
            {"domain": r["domain"], "score": r["summary"]["avg_overall"]}
            for r in sorted_by_score[-3:]
        ]

    report["completed"] = datetime.now(timezone.utc).isoformat()

    return report


def show_auto_report(report: dict):
    """Display auto evaluation report."""
    print(f"\n{'='*70}")
    print(f"  AUTO EXTRACTION EVALUATION RESULTS")
    print(f"{'='*70}")

    agg = report.get("aggregate", {})
    if not agg:
        print("\n  No valid results to aggregate.")
        return

    print(f"\n  Domains evaluated: {agg.get('domains_evaluated', 0)}")
    print(f"  Domains with data: {agg.get('domains_with_data', 0)}")
    print(f"  Total pages: {agg.get('total_pages', 0)}")

    print(f"\n  AGGREGATE SCORES:")
    print(f"    Completeness: {agg.get('avg_completeness', 'N/A')}/5")
    print(f"    Precision:    {agg.get('avg_precision', 'N/A')}/5")
    print(f"    Structure:    {agg.get('avg_structure', 'N/A')}/5")
    print(f"    ─────────────────────")
    print(f"    OVERALL:      {agg.get('avg_overall', 'N/A')}/5")

    # Interpret
    overall = agg.get('avg_overall', 0)
    if overall >= 4:
        verdict = "GOOD"
    elif overall >= 3:
        verdict = "ACCEPTABLE"
    elif overall >= 2:
        verdict = "NEEDS WORK"
    else:
        verdict = "POOR"
    print(f"\n  Verdict: {verdict}")

    # Best/worst
    if agg.get("best_domains"):
        print(f"\n  Top performers:")
        for d in agg["best_domains"]:
            print(f"    {d['score']:.2f}/5 - {d['domain']}")

    if agg.get("worst_domains"):
        print(f"\n  Needs attention:")
        for d in agg["worst_domains"]:
            print(f"    {d['score']:.2f}/5 - {d['domain']}")

    # Per-domain table
    print(f"\n  {'─'*70}")
    print(f"  {'Domain':<30} {'Comp':>6} {'Prec':>6} {'Struct':>6} {'Avg':>6} {'Pages':>6}")
    print(f"  {'─'*70}")

    for r in sorted(report.get("domains", []), key=lambda x: x.get("summary", {}).get("avg_overall", 0), reverse=True):
        domain = r.get("domain", "?")[:28]
        s = r.get("summary", {})
        if s.get("avg_overall"):
            print(f"  {domain:<30} {s['avg_completeness']:>6.2f} {s['avg_precision']:>6.2f} {s['avg_structure']:>6.2f} {s['avg_overall']:>6.2f} {s['pages_graded']:>6}")
        else:
            err = r.get("error", "no data")[:20]
            print(f"  {domain:<30} {'--':>6} {'--':>6} {'--':>6} {'--':>6} {err:>6}")

    print(f"  {'─'*70}")


def main():
    parser = argparse.ArgumentParser(
        description="Extraction quality evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/eval_extraction.py                      # Interactive mode
  python scripts/eval_extraction.py --domain saia.com    # Specific domain
  python scripts/eval_extraction.py --auto               # Auto-evaluate all crawls
  python scripts/eval_extraction.py --auto --tier 1      # Auto-evaluate tier-1 only
  python scripts/eval_extraction.py --auto -j 4 -n 10    # 4 parallel, 10 pages each
"""
    )
    parser.add_argument("--domain", "-d", help="Domain to evaluate")
    parser.add_argument("--crawl", "-c", action="store_true", help="Crawl first if needed")
    parser.add_argument("--sample", "-n", type=int, default=5, help="Number of pages to evaluate")
    parser.add_argument("--report", "-r", action="store_true", help="View last report")
    parser.add_argument("--auto", "-a", action="store_true", help="Auto mode - no prompts, uses heuristics")
    parser.add_argument("--tier", "-t", type=int, help="Filter to specific tier (with --auto)")
    parser.add_argument("--jobs", "-j", type=int, default=1, help="Parallel jobs (with --auto)")
    args = parser.parse_args()

    if args.report:
        view_last_report()
        return

    seeds = load_seeds()
    crawls = get_available_crawls()

    # Auto mode
    if args.auto:
        if not crawls:
            print("No crawl data available. Run some crawls first.")
            return

        report = run_auto_evaluation(
            domains=crawls,
            sample_size=args.sample,
            jobs=args.jobs,
            tier_filter=args.tier,
        )

        # Save report
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tier_suffix = f"_tier{args.tier}" if args.tier else ""
        filepath = REPORTS_DIR / f"auto_extraction_eval{tier_suffix}_{timestamp}.json"
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\n  Report saved to: {filepath}")
        show_auto_report(report)
        return

    # Interactive mode
    if args.domain:
        domain = args.domain
    else:
        domain = select_domain(crawls, seeds)
        if not domain:
            print("No domain selected. Exiting.")
            return

    print(f"\n  Starting extraction evaluation for: {domain}")

    # Run evaluation
    report = run_evaluation(domain, sample_size=args.sample, do_crawl=args.crawl)

    if report.get("pages"):
        # Save report
        filepath = save_report(report)
        print(f"\n  Report saved to: {filepath}")

        # Show summary
        show_report(report)
    else:
        print("\n  No pages evaluated.")


if __name__ == "__main__":
    main()
