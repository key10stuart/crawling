#!/usr/bin/env python3
"""
Human Emulation Test Harness

Tests for validating that human emulation utilities produce
realistic distributions for timing, mouse movement, and scrolling.

Run with:
    python eval/fixtures/human_emulation/test_human.py
    python eval/fixtures/human_emulation/test_human.py --visual  # show plots
"""

import argparse
import math
import statistics
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from fetch.human import (
    human_delay,
    typing_delay,
    reading_time,
    generate_mouse_path,
    HumanSession,
    COMMON_VIEWPORTS,
)


def test_human_delay_distribution(n_samples: int = 1000) -> dict:
    """
    Test that human_delay produces realistic distribution.

    Expected characteristics:
    - Mean around base value
    - Some variance (not all identical)
    - Occasional longer delays (distraction)
    - No negative values
    """
    base = 1.0
    samples = [human_delay(base) for _ in range(n_samples)]

    results = {
        'test': 'human_delay_distribution',
        'n_samples': n_samples,
        'base': base,
        'min': min(samples),
        'max': max(samples),
        'mean': statistics.mean(samples),
        'stdev': statistics.stdev(samples),
        'median': statistics.median(samples),
    }

    # Check characteristics
    results['passed'] = True
    results['failures'] = []

    # No negative values
    if results['min'] < 0:
        results['passed'] = False
        results['failures'].append(f'Negative delay: {results["min"]}')

    # Mean should be close to base (within 50%)
    if not (0.5 * base <= results['mean'] <= 2.0 * base):
        results['passed'] = False
        results['failures'].append(f'Mean {results["mean"]:.3f} not close to base {base}')

    # Should have some variance (stdev > 0.1)
    if results['stdev'] < 0.1:
        results['passed'] = False
        results['failures'].append(f'Too little variance: stdev={results["stdev"]:.3f}')

    # Should have some "distraction" delays (max > 2x base)
    if results['max'] < 2.0 * base:
        results['passed'] = False
        results['failures'].append(f'No distraction delays detected')

    return results


def test_typing_delay_distribution(n_samples: int = 1000) -> dict:
    """
    Test that typing_delay produces realistic distribution.

    Expected characteristics:
    - Average around 100-200ms
    - Variation between characters
    - Longer delays after punctuation
    """
    # Test with variety of characters
    test_chars = 'The quick brown fox jumps! Over the lazy dog.'
    samples = [typing_delay(c) for c in test_chars * (n_samples // len(test_chars))]

    # Separate by character type
    letter_delays = [typing_delay(c) for c in 'abcdefghijklmnop' * 50]
    punct_delays = [typing_delay(c) for c in '.,;:!? ' * 50]

    results = {
        'test': 'typing_delay_distribution',
        'n_samples': len(samples),
        'mean_all': statistics.mean(samples),
        'stdev_all': statistics.stdev(samples),
        'mean_letters': statistics.mean(letter_delays),
        'mean_punctuation': statistics.mean(punct_delays),
    }

    results['passed'] = True
    results['failures'] = []

    # Average should be around 80-200ms
    if not (0.05 <= results['mean_all'] <= 0.3):
        results['passed'] = False
        results['failures'].append(f'Mean delay {results["mean_all"]:.3f}s outside expected range')

    # Punctuation should be slower than letters
    if results['mean_punctuation'] <= results['mean_letters']:
        results['passed'] = False
        results['failures'].append('Punctuation not slower than letters')

    return results


def test_mouse_path_characteristics(n_paths: int = 100) -> dict:
    """
    Test that mouse paths are curved and realistic.

    Expected characteristics:
    - Paths are curved (not straight lines)
    - Path length > straight-line distance
    - Points have micro-jitter
    - Speed varies along path (faster middle, slower ends)
    """
    results = {
        'test': 'mouse_path_characteristics',
        'n_paths': n_paths,
        'path_lengths': [],
        'straight_distances': [],
        'curvature_ratios': [],
    }

    for _ in range(n_paths):
        # Random start and end
        import random
        start = (random.randint(0, 1000), random.randint(0, 800))
        end = (random.randint(0, 1000), random.randint(0, 800))

        path = generate_mouse_path(start, end)

        # Calculate path length
        path_length = 0
        for i in range(1, len(path)):
            dx = path[i][0] - path[i-1][0]
            dy = path[i][1] - path[i-1][1]
            path_length += math.sqrt(dx*dx + dy*dy)

        # Calculate straight-line distance
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        straight = math.sqrt(dx*dx + dy*dy)

        if straight > 10:  # Skip very short paths
            results['path_lengths'].append(path_length)
            results['straight_distances'].append(straight)
            results['curvature_ratios'].append(path_length / straight)

    if not results['curvature_ratios']:
        results['passed'] = False
        results['failures'] = ['No valid paths generated']
        return results

    results['mean_curvature_ratio'] = statistics.mean(results['curvature_ratios'])
    results['min_curvature_ratio'] = min(results['curvature_ratios'])
    results['max_curvature_ratio'] = max(results['curvature_ratios'])

    results['passed'] = True
    results['failures'] = []

    # Paths should be curved (length > straight distance)
    if results['mean_curvature_ratio'] < 1.01:
        results['passed'] = False
        results['failures'].append('Paths too straight (not curved enough)')

    # But not too curved (< 2x straight distance on average)
    if results['mean_curvature_ratio'] > 2.0:
        results['passed'] = False
        results['failures'].append('Paths too curved (unrealistic)')

    return results


def test_mouse_path_jitter(n_paths: int = 50) -> dict:
    """
    Test that mouse paths have micro-jitter.
    """
    results = {
        'test': 'mouse_path_jitter',
        'n_paths': n_paths,
    }

    import random

    # Generate paths with same start/end to check for variation
    start = (100, 100)
    end = (500, 400)

    paths = [generate_mouse_path(start, end) for _ in range(n_paths)]

    # Check that midpoints vary
    midpoint_xs = [p[len(p)//2][0] for p in paths]
    midpoint_ys = [p[len(p)//2][1] for p in paths]

    results['midpoint_x_stdev'] = statistics.stdev(midpoint_xs)
    results['midpoint_y_stdev'] = statistics.stdev(midpoint_ys)

    results['passed'] = True
    results['failures'] = []

    # Should have some variation at midpoint
    if results['midpoint_x_stdev'] < 5 or results['midpoint_y_stdev'] < 5:
        results['passed'] = False
        results['failures'].append('Paths too deterministic (not enough variation)')

    return results


def test_human_session_variety(n_sessions: int = 100) -> dict:
    """
    Test that HumanSession produces variety.
    """
    sessions = [HumanSession() for _ in range(n_sessions)]

    viewports = [s.viewport for s in sessions]
    timezones = [s.timezone for s in sessions]
    locales = [s.locale for s in sessions]

    results = {
        'test': 'human_session_variety',
        'n_sessions': n_sessions,
        'unique_viewports': len(set(viewports)),
        'unique_timezones': len(set(timezones)),
        'unique_locales': len(set(locales)),
        'total_viewport_options': len(COMMON_VIEWPORTS),
    }

    results['passed'] = True
    results['failures'] = []

    # Should use variety of viewports
    if results['unique_viewports'] < 3:
        results['passed'] = False
        results['failures'].append('Not enough viewport variety')

    # Should use variety of timezones
    if results['unique_timezones'] < 2:
        results['passed'] = False
        results['failures'].append('Not enough timezone variety')

    return results


def test_reading_time() -> dict:
    """Test reading time estimates."""
    results = {
        'test': 'reading_time',
    }

    # Short text
    short = reading_time(50)  # 50 words
    medium = reading_time(200)  # 200 words
    long = reading_time(1000)  # 1000 words

    results['short_50_words'] = short
    results['medium_200_words'] = medium
    results['long_1000_words'] = long

    results['passed'] = True
    results['failures'] = []

    # Short should be < medium < long
    if not (short < medium < long):
        results['passed'] = False
        results['failures'].append('Reading time not proportional to length')

    # 200 words should take roughly 30-90 seconds
    if not (20 <= medium <= 120):
        results['passed'] = False
        results['failures'].append(f'Medium reading time {medium}s outside expected range')

    return results


def run_all_tests(verbose: bool = False) -> bool:
    """Run all tests and report results."""
    tests = [
        test_human_delay_distribution,
        test_typing_delay_distribution,
        test_mouse_path_characteristics,
        test_mouse_path_jitter,
        test_human_session_variety,
        test_reading_time,
    ]

    all_passed = True
    print('Human Emulation Test Suite')
    print('=' * 60)
    print()

    for test_fn in tests:
        result = test_fn()

        status = 'PASS' if result['passed'] else 'FAIL'
        print(f'{result["test"]}: {status}')

        if verbose or not result['passed']:
            for key, value in result.items():
                if key not in ('test', 'passed', 'failures', 'path_lengths', 'straight_distances', 'curvature_ratios'):
                    if isinstance(value, float):
                        print(f'  {key}: {value:.4f}')
                    else:
                        print(f'  {key}: {value}')

            if result.get('failures'):
                for failure in result['failures']:
                    print(f'  FAILURE: {failure}')

        if not result['passed']:
            all_passed = False

        print()

    print('=' * 60)
    print(f'Overall: {"PASS" if all_passed else "FAIL"}')

    return all_passed


def visualize_distributions():
    """Create visual plots of distributions (requires matplotlib)."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print('matplotlib not installed - skipping visualizations')
        return

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))

    # 1. Human delay distribution
    delays = [human_delay(1.0) for _ in range(1000)]
    axes[0, 0].hist(delays, bins=50, edgecolor='black')
    axes[0, 0].set_title('Human Delay Distribution (base=1.0s)')
    axes[0, 0].set_xlabel('Delay (seconds)')
    axes[0, 0].set_ylabel('Frequency')
    axes[0, 0].axvline(x=1.0, color='r', linestyle='--', label='Base')
    axes[0, 0].legend()

    # 2. Typing delay distribution
    text = 'The quick brown fox jumps over the lazy dog. ' * 20
    typing = [typing_delay(c) for c in text]
    axes[0, 1].hist(typing, bins=50, edgecolor='black')
    axes[0, 1].set_title('Typing Delay Distribution')
    axes[0, 1].set_xlabel('Delay (seconds)')
    axes[0, 1].set_ylabel('Frequency')

    # 3. Sample mouse paths
    import random
    for _ in range(5):
        start = (random.randint(0, 100), random.randint(0, 100))
        end = (random.randint(400, 500), random.randint(300, 400))
        path = generate_mouse_path(start, end)
        xs = [p[0] for p in path]
        ys = [p[1] for p in path]
        axes[1, 0].plot(xs, ys, alpha=0.7)
    axes[1, 0].set_title('Sample Mouse Paths')
    axes[1, 0].set_xlabel('X')
    axes[1, 0].set_ylabel('Y')
    axes[1, 0].invert_yaxis()  # Y increases downward in screen coords

    # 4. Path curvature ratio distribution
    curvatures = []
    for _ in range(200):
        start = (random.randint(0, 1000), random.randint(0, 800))
        end = (random.randint(0, 1000), random.randint(0, 800))
        path = generate_mouse_path(start, end)

        path_len = sum(
            math.sqrt((path[i][0]-path[i-1][0])**2 + (path[i][1]-path[i-1][1])**2)
            for i in range(1, len(path))
        )
        straight = math.sqrt((end[0]-start[0])**2 + (end[1]-start[1])**2)
        if straight > 10:
            curvatures.append(path_len / straight)

    axes[1, 1].hist(curvatures, bins=30, edgecolor='black')
    axes[1, 1].set_title('Path Curvature Ratio (path_length / straight_distance)')
    axes[1, 1].set_xlabel('Ratio')
    axes[1, 1].set_ylabel('Frequency')
    axes[1, 1].axvline(x=1.0, color='r', linestyle='--', label='Straight line')
    axes[1, 1].legend()

    plt.tight_layout()
    plt.savefig('human_emulation_analysis.png', dpi=150)
    print('Saved visualization to human_emulation_analysis.png')
    plt.show()


def main():
    parser = argparse.ArgumentParser(description='Human Emulation Test Harness')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--visual', action='store_true', help='Show visualizations')

    args = parser.parse_args()

    passed = run_all_tests(verbose=args.verbose)

    if args.visual:
        visualize_distributions()

    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
