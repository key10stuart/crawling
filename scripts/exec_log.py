#!/usr/bin/env python3
"""
View and query execution logs.

Usage:
    python scripts/exec_log.py                  # Show last 5 runs
    python scripts/exec_log.py --last 10        # Show last 10 runs
    python scripts/exec_log.py --today          # Today's runs only
    python scripts/exec_log.py --failures       # Show only failed runs
    python scripts/exec_log.py --full           # Full JSON output
    python scripts/exec_log.py --stats          # Aggregate statistics
"""

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
LOG_FILE = PROJECT_ROOT / "corpus" / "logs" / "executions.jsonl"


def load_logs():
    """Load all execution logs."""
    if not LOG_FILE.exists():
        return []
    logs = []
    for line in LOG_FILE.read_text().strip().split('\n'):
        if line:
            try:
                logs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return logs


def format_duration(sec):
    """Format seconds as human-readable duration."""
    if sec < 60:
        return f"{sec:.0f}s"
    elif sec < 3600:
        return f"{sec/60:.1f}m"
    else:
        return f"{sec/3600:.1f}h"


def format_entry(entry, full=False):
    """Format a single log entry for display."""
    if full:
        return json.dumps(entry, indent=2)

    ts = entry.get('timestamp', '')[:19].replace('T', ' ')
    dur = format_duration(entry.get('duration_sec', 0))
    cfg = entry.get('config', {})
    res = entry.get('results', {})

    tier = cfg.get('tier') or '-'
    domain = cfg.get('domain') or '-'
    docker = 'docker' if cfg.get('docker') else 'native'

    completed = res.get('sites_completed', 0)
    attempted = res.get('sites_attempted', 0)
    pages = res.get('total_pages', 0)
    words = res.get('total_words', 0)
    methods = res.get('methods_used', {})

    target = f"tier {tier}" if tier != '-' else domain

    method_str = ', '.join(f"{k}:{v}" for k, v in methods.items()) if methods else '-'

    lines = [
        f"[{ts}] {target} ({docker})",
        f"  {completed}/{attempted} sites, {pages} pages, {words:,} words in {dur}",
        f"  methods: {method_str}",
    ]

    if res.get('sites_failed', 0) > 0:
        lines.append(f"  FAILED: {res['sites_failed']} sites")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='View execution logs')
    parser.add_argument('--last', type=int, default=5, help='Show last N runs')
    parser.add_argument('--today', action='store_true', help='Today only')
    parser.add_argument('--failures', action='store_true', help='Failed runs only')
    parser.add_argument('--full', action='store_true', help='Full JSON output')
    parser.add_argument('--stats', action='store_true', help='Aggregate statistics')
    args = parser.parse_args()

    logs = load_logs()

    if not logs:
        print("No execution logs found.")
        print(f"Run a crawl first: ./scripts/docker_crawl.sh --tier 1")
        return

    # Filter
    if args.today:
        today = datetime.now(timezone.utc).date().isoformat()
        logs = [l for l in logs if l.get('timestamp', '').startswith(today)]

    if args.failures:
        logs = [l for l in logs if l.get('results', {}).get('sites_failed', 0) > 0]

    if args.stats:
        # Aggregate statistics
        total_runs = len(logs)
        total_sites = sum(l.get('results', {}).get('sites_completed', 0) for l in logs)
        total_pages = sum(l.get('results', {}).get('total_pages', 0) for l in logs)
        total_words = sum(l.get('results', {}).get('total_words', 0) for l in logs)
        total_time = sum(l.get('duration_sec', 0) for l in logs)
        total_failed = sum(l.get('results', {}).get('sites_failed', 0) for l in logs)

        all_methods = {}
        for l in logs:
            for method, count in l.get('results', {}).get('methods_used', {}).items():
                all_methods[method] = all_methods.get(method, 0) + count

        print("=== Execution Log Statistics ===")
        print(f"Total runs:    {total_runs}")
        print(f"Total sites:   {total_sites} ({total_failed} failed)")
        print(f"Total pages:   {total_pages}")
        print(f"Total words:   {total_words:,}")
        print(f"Total time:    {format_duration(total_time)}")
        print(f"Methods used:  {all_methods}")

        if logs:
            first = logs[0].get('timestamp', '')[:10]
            last = logs[-1].get('timestamp', '')[:10]
            print(f"Date range:    {first} to {last}")
        return

    # Show last N
    logs = logs[-args.last:]

    if not logs:
        print("No matching logs found.")
        return

    print(f"=== Last {len(logs)} Execution(s) ===\n")
    for entry in logs:
        print(format_entry(entry, full=args.full))
        print()


if __name__ == '__main__':
    main()
