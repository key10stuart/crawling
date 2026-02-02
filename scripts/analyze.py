#!/usr/bin/env python3
"""
Analysis tools for trucking web corpus.

Generates:
- Term frequency analysis (ngrams, tracked terms)
- Cross-site comparisons
- The "mean website" - aggregate/typical site structure and content
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SITES_DIR = PROJECT_ROOT / "corpus" / "sites"
ANALYSIS_DIR = PROJECT_ROOT / "analysis"


def load_all_sites() -> list[dict]:
    """Load all site JSON files."""
    sites = []
    for f in SITES_DIR.glob("*.json"):
        with open(f) as fp:
            sites.append(json.load(fp))
    return sites


def term_frequency_report(sites: list[dict]) -> dict:
    """
    Analyze term frequencies across corpus.
    Returns dict with global counts, per-site counts, per-page-type counts.
    """
    global_counts = Counter()
    per_site = {}
    per_page_type = defaultdict(Counter)
    per_category = defaultdict(Counter)

    for site in sites:
        site_terms = Counter(site.get('term_counts', {}))
        global_counts.update(site_terms)
        per_site[site['domain']] = dict(site_terms)

        for cat in site.get('category', []):
            per_category[cat].update(site_terms)

        for page in site.get('pages', []):
            page_type = page.get('page_type', 'other')
            per_page_type[page_type].update(page.get('term_counts', {}))

    return {
        'global': dict(global_counts.most_common()),
        'per_site': per_site,
        'per_page_type': {k: dict(v.most_common()) for k, v in per_page_type.items()},
        'per_category': {k: dict(v.most_common()) for k, v in per_category.items()},
    }


def compute_ngrams(text: str, n: int = 2) -> Counter:
    """Compute n-grams from text."""
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    ngrams = zip(*[words[i:] for i in range(n)])
    return Counter(' '.join(ng) for ng in ngrams)


def corpus_ngrams(sites: list[dict], n: int = 2, top_k: int = 100) -> dict:
    """Compute n-grams across entire corpus."""
    all_ngrams = Counter()

    for site in sites:
        for page in site.get('pages', []):
            text = page.get('full_text', '')
            all_ngrams.update(compute_ngrams(text, n))

    return {
        'n': n,
        'top': dict(all_ngrams.most_common(top_k)),
    }


def mean_website(sites: list[dict]) -> dict:
    """
    Compute the "mean website" - aggregate characteristics.

    Returns:
    - Most common page types and their frequency
    - Average pages per site
    - Most common H1s
    - Most common section headings
    - Average word count by page type
    - Typical site structure
    """
    if not sites:
        return {}

    # Page type distribution
    page_type_counts = Counter()
    page_type_word_counts = defaultdict(list)

    # H1s and headings
    all_h1s = Counter()
    all_headings = Counter()

    # Structure
    total_pages = []
    pages_by_type = defaultdict(list)

    for site in sites:
        pages = site.get('pages', [])
        total_pages.append(len(pages))

        for page in pages:
            pt = page.get('page_type', 'other')
            page_type_counts[pt] += 1
            page_type_word_counts[pt].append(page.get('word_count', 0))

            if page.get('h1'):
                # Normalize H1 for comparison (lowercase, strip)
                h1_normalized = page['h1'].lower().strip()
                all_h1s[h1_normalized] += 1

            for section in page.get('sections', []):
                if section.get('heading'):
                    heading_normalized = section['heading'].lower().strip()
                    all_headings[heading_normalized] += 1

    # Compute averages
    avg_pages = sum(total_pages) / len(total_pages) if total_pages else 0

    avg_word_count_by_type = {}
    for pt, counts in page_type_word_counts.items():
        avg_word_count_by_type[pt] = sum(counts) / len(counts) if counts else 0

    # Page types that appear in >50% of sites
    sites_with_page_type = defaultdict(set)
    for site in sites:
        for page in site.get('pages', []):
            sites_with_page_type[page.get('page_type')].add(site['domain'])

    common_page_types = {
        pt: len(domains) / len(sites)
        for pt, domains in sites_with_page_type.items()
    }

    return {
        'sample_size': len(sites),
        'avg_pages_per_site': round(avg_pages, 1),
        'page_type_distribution': dict(page_type_counts.most_common()),
        'page_type_prevalence': {k: round(v, 2) for k, v in sorted(common_page_types.items(), key=lambda x: -x[1])},
        'avg_word_count_by_page_type': {k: round(v, 0) for k, v in avg_word_count_by_type.items()},
        'top_h1s': dict(all_h1s.most_common(30)),
        'top_section_headings': dict(all_headings.most_common(50)),
    }


def site_comparison_matrix(sites: list[dict], terms: list[str] = None) -> dict:
    """
    Create comparison matrix of sites vs terms.
    Useful for heatmap visualization.
    """
    if terms is None:
        # Get top terms from corpus
        all_terms = Counter()
        for site in sites:
            all_terms.update(site.get('term_counts', {}))
        terms = [t for t, _ in all_terms.most_common(20)]

    matrix = {}
    for site in sites:
        site_counts = site.get('term_counts', {})
        matrix[site['domain']] = {t: site_counts.get(t, 0) for t in terms}

    return {
        'terms': terms,
        'sites': [s['domain'] for s in sites],
        'matrix': matrix,
    }


def h1_analysis(sites: list[dict]) -> dict:
    """Analyze homepage H1s specifically."""
    homepage_h1s = []

    for site in sites:
        for page in site.get('pages', []):
            if page.get('page_type') == 'home' and page.get('h1'):
                homepage_h1s.append({
                    'domain': site['domain'],
                    'company': site['company_name'],
                    'h1': page['h1'],
                    'category': site.get('category', []),
                })
                break  # Only first homepage

    return {
        'count': len(homepage_h1s),
        'h1s': homepage_h1s,
    }


def generate_report(sites: list[dict]) -> dict:
    """Generate full analysis report."""
    return {
        'summary': {
            'total_sites': len(sites),
            'total_pages': sum(s['structure']['total_pages'] for s in sites),
            'total_words': sum(s['total_word_count'] for s in sites),
            'by_tier': Counter(s['tier'] for s in sites),
            'by_category': Counter(cat for s in sites for cat in s.get('category', [])),
        },
        'term_frequency': term_frequency_report(sites),
        'bigrams': corpus_ngrams(sites, n=2, top_k=50),
        'trigrams': corpus_ngrams(sites, n=3, top_k=50),
        'mean_website': mean_website(sites),
        'comparison_matrix': site_comparison_matrix(sites),
        'homepage_h1s': h1_analysis(sites),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Analyze trucking web corpus')
    parser.add_argument('--output', '-o', default='report.json', help='Output file')
    parser.add_argument('--term', '-t', help='Show sites mentioning specific term')
    parser.add_argument('--compare', nargs=2, help='Compare two domains')
    args = parser.parse_args()

    sites = load_all_sites()

    if not sites:
        print("No sites found in corpus. Run crawl.py first.")
        return

    print(f"Loaded {len(sites)} sites")

    if args.term:
        # Quick term lookup
        term = args.term.lower()
        print(f"\nSites mentioning '{term}':")
        for site in sorted(sites, key=lambda s: s.get('term_counts', {}).get(term, 0), reverse=True):
            count = site.get('term_counts', {}).get(term, 0)
            if count > 0:
                print(f"  {site['domain']}: {count}")
        return

    if args.compare:
        # Compare two sites
        d1, d2 = args.compare
        s1 = next((s for s in sites if d1 in s['domain']), None)
        s2 = next((s for s in sites if d2 in s['domain']), None)

        if not s1 or not s2:
            print("Could not find both domains")
            return

        print(f"\nComparing {s1['domain']} vs {s2['domain']}:")
        print(f"  Pages: {s1['structure']['total_pages']} vs {s2['structure']['total_pages']}")
        print(f"  Words: {s1['total_word_count']:,} vs {s2['total_word_count']:,}")

        all_terms = set(s1.get('term_counts', {}).keys()) | set(s2.get('term_counts', {}).keys())
        print(f"\n  Term comparison:")
        for term in sorted(all_terms):
            c1 = s1.get('term_counts', {}).get(term, 0)
            c2 = s2.get('term_counts', {}).get(term, 0)
            if c1 > 0 or c2 > 0:
                print(f"    {term}: {c1} vs {c2}")
        return

    # Full report
    print("Generating full report...")
    report = generate_report(sites)

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = ANALYSIS_DIR / args.output

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Report saved to {output_path}")

    # Print summary
    print(f"\n{'='*60}")
    print("CORPUS SUMMARY")
    print(f"{'='*60}")
    print(f"Sites: {report['summary']['total_sites']}")
    print(f"Pages: {report['summary']['total_pages']}")
    print(f"Words: {report['summary']['total_words']:,}")

    print(f"\nTop terms:")
    for term, count in list(report['term_frequency']['global'].items())[:15]:
        print(f"  {term}: {count}")

    print(f"\nMean website:")
    mw = report['mean_website']
    print(f"  Avg pages: {mw['avg_pages_per_site']}")
    print(f"  Common page types: {list(mw['page_type_prevalence'].keys())[:8]}")


if __name__ == '__main__':
    main()
