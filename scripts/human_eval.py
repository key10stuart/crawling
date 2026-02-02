#!/usr/bin/env python3
"""
Human Evaluation Harness for Comp Packages Extraction.

Implements the evaluation rubric from docs/div3.txt:
- Sampling: random (10), targeted (5), edge cases (5)
- Scoring: Coverage (0-3), Precision (0-3), Recency (0-2) = /8 per site
- Pass/Fail: average >= 6/8, no site < 4

Usage:
    # Generate a sample set for evaluation
    python scripts/human_eval.py --sample --out eval/sample_2026-01-26.json

    # Generate worksheet (Markdown) for manual scoring
    python scripts/human_eval.py --worksheet eval/sample_2026-01-26.json --out eval/worksheet_2026-01-26.md

    # Score a completed worksheet
    python scripts/human_eval.py --score eval/worksheet_2026-01-26_scored.json

    # Full report with pass/fail
    python scripts/human_eval.py --report eval/scores.json
"""

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

SITES_DIR = Path(__file__).parent.parent / "corpus" / "sites"
SEEDS_FILE = Path(__file__).parent.parent / "seeds" / "trucking_carriers.json"

# Evaluation criteria from div3.txt
CRITERIA = {
    'coverage': {
        'max': 3,
        'levels': {
            0: 'None - No comp items captured',
            1: 'Partial - Some items captured, major gaps',
            2: 'Good - Most items captured, minor gaps',
            3: 'Complete - All visible comp items captured',
        },
    },
    'precision': {
        'max': 3,
        'levels': {
            0: 'Many false positives - >50% incorrect',
            1: 'Some false positives - 25-50% incorrect',
            2: 'Few false positives - <25% incorrect',
            3: 'Clean - No false positives',
        },
    },
    'recency': {
        'max': 2,
        'levels': {
            0: 'Missed recent changes',
            1: 'Partial recent capture',
            2: 'Captured new items',
        },
    },
}

MAX_SCORE = sum(c['max'] for c in CRITERIA.values())  # 8
PASS_THRESHOLD_AVG = 6
PASS_THRESHOLD_MIN = 4


def load_seeds() -> list[dict]:
    """Load carrier seeds with tier info."""
    if not SEEDS_FILE.exists():
        return []
    with open(SEEDS_FILE) as f:
        data = json.load(f)
    # Handle nested structure with "carriers" key
    if isinstance(data, dict) and "carriers" in data:
        return data["carriers"]
    return data


def load_site(domain: str) -> dict | None:
    """Load site JSON if exists."""
    filename = domain.replace('.', '_') + '.json'
    path = SITES_DIR / filename
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def generate_sample(
    n_random: int = 10,
    n_targeted: int = 5,
    n_edge: int = 5,
) -> dict:
    """
    Generate a stratified sample for human evaluation.

    Returns:
        Dict with sample metadata and site list
    """
    seeds = load_seeds()
    available_sites = []

    for seed in seeds:
        domain = seed.get('domain', '')
        site_data = load_site(domain)
        if site_data and site_data.get('pages'):
            # Handle both 'category' and 'categories' field names
            categories = seed.get('categories') or seed.get('category', [])
            if isinstance(categories, str):
                categories = [categories]
            available_sites.append({
                'domain': domain,
                'tier': seed.get('tier', 3),
                'categories': categories,
                'page_count': len(site_data.get('pages', [])),
                'has_structured': bool(site_data.get('structured_data')),
            })

    if not available_sites:
        return {'error': 'No crawled sites found', 'sites': []}

    # Stratify by tier
    tier1 = [s for s in available_sites if s['tier'] == 1]
    tier2 = [s for s in available_sites if s['tier'] == 2]
    tier3 = [s for s in available_sites if s['tier'] == 3]

    sample = []

    # Random sample across tiers
    all_for_random = tier1 + tier2 + tier3
    random.shuffle(all_for_random)
    random_sample = all_for_random[:n_random]
    for s in random_sample:
        s['sample_type'] = 'random'
    sample.extend(random_sample)

    # Targeted: sites likely to have rich recruiting content
    recruiting_keywords = ['ltl', 'truckload', 'regional', 'otr']
    targeted_candidates = [
        s for s in available_sites
        if s not in sample and any(k in ' '.join(s['categories']).lower() for k in recruiting_keywords)
    ]
    random.shuffle(targeted_candidates)
    targeted_sample = targeted_candidates[:n_targeted]
    for s in targeted_sample:
        s['sample_type'] = 'targeted'
    sample.extend(targeted_sample)

    # Edge cases: JS-heavy sites (tier 1 typically)
    edge_candidates = [
        s for s in tier1
        if s not in sample
    ]
    random.shuffle(edge_candidates)
    edge_sample = edge_candidates[:n_edge]
    for s in edge_sample:
        s['sample_type'] = 'edge_case'
    sample.extend(edge_sample)

    return {
        'generated_at': datetime.now().isoformat(),
        'counts': {
            'total': len(sample),
            'random': len([s for s in sample if s['sample_type'] == 'random']),
            'targeted': len([s for s in sample if s['sample_type'] == 'targeted']),
            'edge_case': len([s for s in sample if s['sample_type'] == 'edge_case']),
        },
        'sites': sample,
    }


def generate_worksheet(sample: dict) -> str:
    """Generate Markdown worksheet for manual scoring."""
    lines = [
        "# Human Evaluation Worksheet",
        f"Generated: {sample.get('generated_at', 'unknown')}",
        "",
        "## Instructions",
        "1. For each site, visit the live website and compare against our extraction.",
        "2. Score each criterion (see rubric below).",
        "3. Add notes for any issues found.",
        "",
        "## Scoring Rubric",
        "",
    ]

    for criterion, info in CRITERIA.items():
        lines.append(f"### {criterion.title()} (0-{info['max']})")
        for score, desc in info['levels'].items():
            lines.append(f"- **{score}**: {desc}")
        lines.append("")

    lines.extend([
        f"## Pass/Fail Threshold",
        f"- Average score >= {PASS_THRESHOLD_AVG}/{MAX_SCORE}",
        f"- No site scores < {PASS_THRESHOLD_MIN}/{MAX_SCORE}",
        "",
        "---",
        "",
        "## Sites to Evaluate",
        "",
    ])

    for i, site in enumerate(sample.get('sites', []), 1):
        domain = site['domain']
        lines.extend([
            f"### {i}. {domain}",
            f"- **Type**: {site['sample_type']}",
            f"- **Tier**: {site['tier']}",
            f"- **Pages crawled**: {site['page_count']}",
            "",
            "#### Checklist",
            "- [ ] Drivers: Pay/bonus/benefits captured?",
            "- [ ] Owner-operators: Lease/settlement/fuel captured?",
            "- [ ] Carriers: Inducements (quick pay, load board) captured?",
            "- [ ] Misses: Any obvious items not captured?",
            "- [ ] False positives: Non-comp content tagged as comp?",
            "",
            "#### Scores",
            "- Coverage: ___/3",
            "- Precision: ___/3",
            "- Recency: ___/2",
            f"- **Total: ___/{MAX_SCORE}**",
            "",
            "#### Notes",
            "```",
            "(Add observations here)",
            "```",
            "",
            "---",
            "",
        ])

    return '\n'.join(lines)


def score_results(scores: list[dict]) -> dict:
    """
    Analyze scores and determine pass/fail.

    Args:
        scores: List of {domain, coverage, precision, recency} dicts

    Returns:
        Summary with pass/fail determination
    """
    if not scores:
        return {'error': 'No scores provided', 'pass': False}

    totals = []
    for s in scores:
        total = s.get('coverage', 0) + s.get('precision', 0) + s.get('recency', 0)
        totals.append(total)
        s['total'] = total

    avg_score = sum(totals) / len(totals)
    min_score = min(totals)
    max_score = max(totals)

    passed = avg_score >= PASS_THRESHOLD_AVG and min_score >= PASS_THRESHOLD_MIN

    failing_sites = [s for s in scores if s['total'] < PASS_THRESHOLD_MIN]

    return {
        'summary': {
            'sites_evaluated': len(scores),
            'average_score': round(avg_score, 2),
            'min_score': min_score,
            'max_score': max_score,
            'pass_threshold_avg': PASS_THRESHOLD_AVG,
            'pass_threshold_min': PASS_THRESHOLD_MIN,
        },
        'result': 'PASS' if passed else 'FAIL',
        'failing_sites': [s['domain'] for s in failing_sites],
        'scores': scores,
    }


def print_report(result: dict):
    """Print formatted evaluation report."""
    summary = result.get('summary', {})
    print("\n" + "=" * 60)
    print("HUMAN EVALUATION REPORT")
    print("=" * 60)
    print(f"\nSites evaluated: {summary.get('sites_evaluated', 0)}")
    print(f"Average score:   {summary.get('average_score', 0)}/{MAX_SCORE}")
    print(f"Min score:       {summary.get('min_score', 0)}/{MAX_SCORE}")
    print(f"Max score:       {summary.get('max_score', 0)}/{MAX_SCORE}")
    print(f"\nThresholds:")
    print(f"  Average >= {PASS_THRESHOLD_AVG}: {'✓' if summary.get('average_score', 0) >= PASS_THRESHOLD_AVG else '✗'}")
    print(f"  Min >= {PASS_THRESHOLD_MIN}:     {'✓' if summary.get('min_score', 0) >= PASS_THRESHOLD_MIN else '✗'}")

    print(f"\n{'=' * 60}")
    result_str = result.get('result', 'UNKNOWN')
    if result_str == 'PASS':
        print(f"RESULT: ✓ {result_str}")
    else:
        print(f"RESULT: ✗ {result_str}")
        if result.get('failing_sites'):
            print(f"\nFailing sites:")
            for site in result['failing_sites']:
                print(f"  - {site}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description='Human evaluation harness for comp packages')
    parser.add_argument('--sample', action='store_true', help='Generate sample set')
    parser.add_argument('--worksheet', type=Path, help='Generate worksheet from sample JSON')
    parser.add_argument('--score', type=Path, help='Score a completed worksheet JSON')
    parser.add_argument('--report', type=Path, help='Print report from scores JSON')
    parser.add_argument('--out', type=Path, help='Output file path')
    parser.add_argument('--n-random', type=int, default=10, help='Number of random samples')
    parser.add_argument('--n-targeted', type=int, default=5, help='Number of targeted samples')
    parser.add_argument('--n-edge', type=int, default=5, help='Number of edge case samples')
    args = parser.parse_args()

    if args.sample:
        sample = generate_sample(
            n_random=args.n_random,
            n_targeted=args.n_targeted,
            n_edge=args.n_edge,
        )
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with open(args.out, 'w') as f:
                json.dump(sample, f, indent=2)
            print(f"Sample written to {args.out}")
            print(f"  Total sites: {sample['counts']['total']}")
            print(f"  Random: {sample['counts']['random']}")
            print(f"  Targeted: {sample['counts']['targeted']}")
            print(f"  Edge cases: {sample['counts']['edge_case']}")
        else:
            print(json.dumps(sample, indent=2))

    elif args.worksheet:
        with open(args.worksheet) as f:
            sample = json.load(f)
        worksheet = generate_worksheet(sample)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with open(args.out, 'w') as f:
                f.write(worksheet)
            print(f"Worksheet written to {args.out}")
        else:
            print(worksheet)

    elif args.score or args.report:
        input_file = args.score or args.report
        with open(input_file) as f:
            data = json.load(f)
        # If it's raw scores, process them; if already processed, just report
        if 'result' in data:
            result = data
        else:
            result = score_results(data.get('scores', data))
        print_report(result)
        if args.out:
            with open(args.out, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"Results written to {args.out}")

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
