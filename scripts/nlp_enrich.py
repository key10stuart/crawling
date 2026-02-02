#!/usr/bin/env python3
"""
Enrich crawl data with NLP analysis.

Runs lightweight extractors (regex, keywords) by default. Add --llm for LLM analysis.

Usage:
    # Single site (lightweight only, no API calls)
    python scripts/nlp_enrich.py --site corpus/sites/jbhunt_com.json

    # All sites
    python scripts/nlp_enrich.py --all

    # With LLM analysis (requires ANTHROPIC_API_KEY)
    python scripts/nlp_enrich.py --site corpus/sites/jbhunt_com.json --llm

    # Ask a question across corpus (always uses LLM)
    python scripts/nlp_enrich.py --question "Which carriers offer sign-on bonuses over $5000?"

    # Competitive summary for a domain (always uses LLM)
    python scripts/nlp_enrich.py --summary jbhunt.com

Requires ANTHROPIC_API_KEY env var for --llm, --question, --summary.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fetch.nlp import (
    enrich_site,
    enrich_page,
    extract_all_lightweight,
    llm_answer_question,
    llm_competitive_summary,
)


SITES_DIR = Path(__file__).parent.parent / "corpus" / "sites"


def load_site(path: Path) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_site(site: dict, path: Path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(site, f, indent=2, ensure_ascii=False)


def print_extraction_summary(site: dict):
    """Print summary of NLP extractions."""
    domain = site.get('domain', 'unknown')
    pages = site.get('pages', [])

    total_money = 0
    total_locations = set()
    comp_categories = {}
    urgent_pages = 0

    for page in pages:
        nlp = page.get('nlp', {})
        total_money += len(nlp.get('money', []))
        total_locations.update(nlp.get('locations', []))

        for cat in nlp.get('comp_keywords', {}).keys():
            comp_categories[cat] = comp_categories.get(cat, 0) + 1

        if nlp.get('urgency', {}).get('is_urgent'):
            urgent_pages += 1

    print(f"\n{domain}")
    print(f"  Pages analyzed: {len(pages)}")
    print(f"  Money mentions: {total_money}")
    print(f"  Locations: {len(total_locations)}")
    print(f"  Urgent pages: {urgent_pages}")
    print(f"  Comp categories: {comp_categories}")


def aggregate_corpus_text(sites: list[dict], max_chars_per_site: int = 5000) -> str:
    """Aggregate text from multiple sites for corpus-wide questions."""
    parts = []
    for site in sites:
        domain = site.get('domain', 'unknown')
        pages = site.get('pages', [])
        site_text = ""
        for page in pages:
            text = page.get('full_text', '')[:1000]
            if text:
                site_text += f"\n[{page.get('path', '/')}]\n{text}\n"
            if len(site_text) > max_chars_per_site:
                break
        if site_text:
            parts.append(f"\n=== {domain} ===\n{site_text}")
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description='Enrich crawl data with NLP analysis')
    parser.add_argument('--site', type=Path, help='Path to site JSON')
    parser.add_argument('--all', action='store_true', help='Process all sites in corpus/sites/')
    parser.add_argument('--llm', action='store_true', help='Enable LLM analysis (requires ANTHROPIC_API_KEY)')
    parser.add_argument('--model', default='claude-haiku-4-20250514', help='LLM model to use')
    parser.add_argument('--question', help='Ask a question across the corpus')
    parser.add_argument('--summary', help='Generate competitive summary for domain')
    parser.add_argument('--dry-run', action='store_true', help='Print results without saving')
    args = parser.parse_args()

    # Question answering mode
    if args.question:
        print(f"Loading corpus...")
        sites = []
        for f in SITES_DIR.glob('*.json'):
            if 'summary' not in f.name:
                sites.append(load_site(f))
        print(f"Loaded {len(sites)} sites")

        corpus_text = aggregate_corpus_text(sites)
        print(f"Corpus text: {len(corpus_text):,} chars")
        print(f"\nQuestion: {args.question}\n")

        answer = llm_answer_question(corpus_text, args.question, args.model)
        print(f"Answer:\n{answer}")
        return

    # Competitive summary mode
    if args.summary:
        site_file = SITES_DIR / f"{args.summary.replace('.', '_')}.json"
        if not site_file.exists():
            print(f"Site not found: {site_file}")
            return
        site = load_site(site_file)
        text = ""
        for page in site.get('pages', [])[:5]:
            text += page.get('full_text', '')[:2000] + "\n"

        summary = llm_competitive_summary(text, site.get('company_name', args.summary), args.model)
        print(f"\nCompetitive Summary: {args.summary}\n")
        print(summary)
        return

    # Enrichment mode
    if args.site:
        sites = [args.site]
    elif args.all:
        sites = list(SITES_DIR.glob('*.json'))
        sites = [s for s in sites if 'summary' not in s.name]
    else:
        parser.print_help()
        return

    for site_path in sites:
        print(f"Processing {site_path.name}...")
        site = load_site(site_path)
        site = enrich_site(site, use_llm=args.llm, llm_model=args.model)

        print_extraction_summary(site)

        if not args.dry_run:
            save_site(site, site_path)
            print(f"  Saved: {site_path}")


if __name__ == '__main__':
    main()
