#!/usr/bin/env python3
"""Batch test interactive fetch on carrier sites."""

import sys
import time
sys.path.insert(0, '.')

from fetch.interactive import interactive_fetch
from fetch.config import FetchConfig
from fetch import fetch_source

CARRIERS = [
    ('J.B. Hunt', 'https://www.jbhunt.com'),
    ('Schneider', 'https://www.schneider.com'),
    ('XPO', 'https://www.xpo.com'),
    ('Old Dominion', 'https://www.odfl.com'),
    ('Saia', 'https://www.saia.com'),
    ('Werner', 'https://www.werner.com'),
    ('Landstar', 'https://www.landstar.com'),
    ('Knight-Swift', 'https://www.knight-swift.com'),
]

def test_carrier(name, url):
    """Test baseline vs interactive fetch."""
    config = FetchConfig()

    # Baseline
    start = time.time()
    baseline = fetch_source(url, config)
    baseline_time = time.time() - start
    baseline_words = baseline.word_count if baseline else 0

    # Interactive (forced)
    config_forced = FetchConfig(min_words=9999)
    start = time.time()
    interactive = interactive_fetch(url, config_forced)
    interactive_time = time.time() - start
    interactive_words = interactive.word_count
    interactions = len(interactive.interaction_log)

    return {
        'name': name,
        'url': url,
        'baseline_words': baseline_words,
        'interactive_words': interactive_words,
        'delta': interactive_words - baseline_words,
        'delta_pct': round((interactive_words - baseline_words) / max(baseline_words, 1) * 100),
        'interactions': interactions,
        'baseline_time': round(baseline_time, 1),
        'interactive_time': round(interactive_time, 1),
    }

def main():
    print(f"Testing {len(CARRIERS)} carriers...\n")
    print(f"{'Carrier':<15} {'Baseline':>8} {'Interactive':>11} {'Delta':>8} {'Actions':>7} {'Time':>6}")
    print("-" * 60)

    results = []
    for name, url in CARRIERS:
        try:
            r = test_carrier(name, url)
            results.append(r)
            print(f"{r['name']:<15} {r['baseline_words']:>8} {r['interactive_words']:>11} {r['delta']:>+8} {r['interactions']:>7} {r['interactive_time']:>5}s")
        except Exception as e:
            print(f"{name:<15} ERROR: {e}")

    # Summary
    print("-" * 60)
    total_baseline = sum(r['baseline_words'] for r in results)
    total_interactive = sum(r['interactive_words'] for r in results)
    total_delta = total_interactive - total_baseline
    avg_time = sum(r['interactive_time'] for r in results) / len(results) if results else 0

    print(f"{'TOTAL':<15} {total_baseline:>8} {total_interactive:>11} {total_delta:>+8}")
    print(f"\nAvg interactive time: {avg_time:.1f}s")
    print(f"Overall improvement: {total_delta:+} words ({round(total_delta/max(total_baseline,1)*100)}%)")

if __name__ == '__main__':
    main()
