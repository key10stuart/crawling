#!/usr/bin/env python3
"""
Export crawl data to various formats.

Supports:
- JSONL: One JSON object per line (streaming-friendly)
- CSV: Flat table of pages
- Summary: Condensed site overview

Usage:
    python scripts/export.py --site corpus/sites/schneider_com.json --format jsonl
    python scripts/export.py --site corpus/sites/schneider_com.json --format csv
    python scripts/export.py --site corpus/sites/schneider_com.json --format summary
"""

import argparse
import csv
import json
import sys
from pathlib import Path


def load_site(path: Path) -> dict:
    """Load site JSON."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def export_jsonl(site: dict, output: Path):
    """
    Export to JSONL format (one JSON object per line).

    Each line is a page with site context added.
    """
    domain = site.get('domain', '')
    company = site.get('company_name', '')
    snapshot_date = site.get('snapshot_date', '')

    with open(output, 'w', encoding='utf-8') as f:
        for page in site.get('pages', []):
            record = {
                'domain': domain,
                'company': company,
                'snapshot_date': snapshot_date,
                'url': page.get('url'),
                'path': page.get('path'),
                'title': page.get('title'),
                'page_type': page.get('page_type'),
                'product': page.get('product'),
                'word_count': page.get('word_count'),
                'full_text': page.get('full_text'),
                'main_content': page.get('main_content'),
                'hero_text': page.get('hero_text'),
                'nav_section': page.get('nav_section'),
                'is_duplicate': page.get('is_duplicate', False),
                'content_hash': page.get('content_hash'),
                'image_count': len(page.get('images', [])),
                'code_block_count': len(page.get('code_blocks', [])),
                'detected_features': page.get('detected_features'),
                'term_counts': page.get('term_counts'),
            }
            f.write(json.dumps(record, ensure_ascii=False) + '\n')

    print(f"Exported {len(site.get('pages', []))} pages to {output}")


def export_csv(site: dict, output: Path):
    """
    Export to CSV format (flat table).

    One row per page with key fields.
    """
    pages = site.get('pages', [])
    if not pages:
        print("No pages to export")
        return

    domain = site.get('domain', '')
    company = site.get('company_name', '')

    fieldnames = [
        'domain', 'company', 'url', 'path', 'title', 'page_type', 'product',
        'word_count', 'main_content_words', 'image_count', 'code_count',
        'nav_section', 'is_duplicate', 'has_portal', 'has_api',
    ]

    with open(output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for page in pages:
            features = page.get('detected_features', {})
            portals = features.get('portals', [])
            api_hints = features.get('api_hints', [])

            main_content = page.get('main_content', '')
            main_words = len(main_content.split()) if main_content else 0

            writer.writerow({
                'domain': domain,
                'company': company,
                'url': page.get('url', ''),
                'path': page.get('path', ''),
                'title': (page.get('title') or '')[:100],  # Truncate for CSV
                'page_type': page.get('page_type', ''),
                'product': page.get('product', ''),
                'word_count': page.get('word_count', 0),
                'main_content_words': main_words,
                'image_count': len(page.get('images', [])),
                'code_count': len(page.get('code_blocks', [])),
                'nav_section': page.get('nav_section', ''),
                'is_duplicate': page.get('is_duplicate', False),
                'has_portal': bool(portals),
                'has_api': bool(api_hints),
            })

    print(f"Exported {len(pages)} pages to {output}")


def export_summary(site: dict, output: Path):
    """
    Export condensed site summary.

    Single JSON with key metrics and aggregated data.
    """
    pages = site.get('pages', [])

    # Page type counts
    page_types = {}
    for p in pages:
        pt = p.get('page_type', 'other')
        page_types[pt] = page_types.get(pt, 0) + 1

    # Product distribution
    products = {}
    for p in pages:
        prod = p.get('product')
        if prod:
            products[prod] = products.get(prod, 0) + 1

    # Aggregate features
    all_portals = set()
    all_integrations = set()
    all_api_hints = set()
    for p in pages:
        features = p.get('detected_features', {})
        for portal in features.get('portals', []):
            if isinstance(portal, dict):
                all_portals.add(portal.get('type', 'unknown'))
            else:
                all_portals.add(str(portal))
        for integ in features.get('integrations', []):
            all_integrations.add(integ)
        for api in features.get('api_hints', []):
            all_api_hints.add(api)

    # Top terms
    term_totals = {}
    for p in pages:
        for term, count in p.get('term_counts', {}).items():
            term_totals[term] = term_totals.get(term, 0) + count
    top_terms = sorted(term_totals.items(), key=lambda x: -x[1])[:20]

    summary = {
        'domain': site.get('domain'),
        'company_name': site.get('company_name'),
        'snapshot_date': site.get('snapshot_date'),
        'crawl_duration_sec': site.get('crawl_duration_sec'),
        'profile': site.get('profile'),

        'metrics': {
            'total_pages': len(pages),
            'total_words': site.get('total_word_count', 0),
            'total_images': site.get('image_count', 0),
            'total_code_blocks': site.get('code_block_count', 0),
            'duplicate_pages': site.get('duplicate_pages', 0),
            'avg_words_per_page': round(site.get('total_word_count', 0) / len(pages)) if pages else 0,
        },

        'coverage': {
            'nav_coverage': site.get('nav_coverage'),
            'product_coverage': site.get('product_coverage'),
        },

        'page_types': page_types,
        'products': products,

        'features': {
            'portals': list(all_portals),
            'integrations': list(all_integrations),
            'api_hints': list(all_api_hints)[:10],  # Limit
        },

        'top_terms': dict(top_terms),

        'pages_sample': [
            {
                'path': p.get('path'),
                'title': p.get('title'),
                'page_type': p.get('page_type'),
                'word_count': p.get('word_count'),
            }
            for p in pages[:10]
        ],
    }

    with open(output, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"Exported summary to {output}")
    print(f"  Pages: {len(pages)}")
    print(f"  Words: {site.get('total_word_count', 0):,}")
    print(f"  Features: {len(all_portals)} portals, {len(all_integrations)} integrations")


def main():
    parser = argparse.ArgumentParser(description='Export crawl data to various formats')
    parser.add_argument('--site', required=True, help='Path to site JSON')
    parser.add_argument('--format', choices=['jsonl', 'csv', 'summary'], default='jsonl',
                        help='Output format')
    parser.add_argument('--out', help='Output path (default: auto-generated)')
    args = parser.parse_args()

    site_path = Path(args.site)
    if not site_path.exists():
        print(f"Error: Site file not found: {site_path}")
        sys.exit(1)

    site = load_site(site_path)
    domain_slug = site.get('domain', 'site').replace('.', '_')

    # Determine output path
    if args.out:
        output = Path(args.out)
    else:
        ext = {'jsonl': '.jsonl', 'csv': '.csv', 'summary': '_summary.json'}[args.format]
        output = site_path.parent / f"{domain_slug}{ext}"

    output.parent.mkdir(parents=True, exist_ok=True)

    # Export
    if args.format == 'jsonl':
        export_jsonl(site, output)
    elif args.format == 'csv':
        export_csv(site, output)
    elif args.format == 'summary':
        export_summary(site, output)


if __name__ == '__main__':
    main()
