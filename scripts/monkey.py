#!/usr/bin/env python3
"""
Monkey CLI - Human-assisted crawling interface.

Commands:
    --list          Show queue of sites awaiting human attention
    --next          Process next site in queue (monkey_see)
    --see DOMAIN    Record flow for specific domain
    --do DOMAIN     Replay saved flow for domain
    --schedule      Run all due scheduled replays
    --clear         Clear the queue
    --info DOMAIN   Show flow info for domain

Usage:
    python scripts/monkey.py --list
    python scripts/monkey.py --next
    python scripts/monkey.py --see knight-swift.com
    python scripts/monkey.py --do knight-swift.com
    python scripts/monkey.py --schedule
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fetch.monkey import (
    MonkeyQueue,
    Flow,
    FLOWS_DIR,
    list_queue,
    get_next_queued,
    clear_queue,
    monkey_see,
    monkey_do,
    run_scheduled_replays,
    get_flow_age_days,
    check_perpetual_manual,
    add_to_monkey_queue,
    load_replay_schedule,
)


def format_age(iso_timestamp: str) -> str:
    """Format ISO timestamp as human-readable age."""
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
        delta = datetime.now(timezone.utc) - dt
        seconds = delta.total_seconds()

        if seconds < 60:
            return f'{int(seconds)}s ago'
        elif seconds < 3600:
            return f'{int(seconds / 60)}m ago'
        elif seconds < 86400:
            return f'{int(seconds / 3600)}h ago'
        else:
            return f'{int(seconds / 86400)}d ago'
    except Exception:
        return 'unknown'


def cmd_list():
    """List queue of sites awaiting human attention."""
    queue_entries = list_queue()

    if not queue_entries:
        print('Monkey Queue: empty')
        print('\nNo sites need attention.')
        return

    print(f'Monkey Queue ({len(queue_entries)} sites):')
    print()

    # Sort by priority and age
    priority_order = {'high': 0, 'normal': 1, 'low': 2}
    sorted_entries = sorted(
        queue_entries,
        key=lambda e: (priority_order.get(e.priority, 1), e.added)
    )

    for i, entry in enumerate(sorted_entries, 1):
        priority_label = f'[{entry.priority.upper()}]' if entry.priority != 'normal' else ''
        age = format_age(entry.added)

        # Check if perpetual manual
        perpetual = check_perpetual_manual(entry.domain)
        perpetual_label = ' [PERPETUAL]' if perpetual else ''

        print(f'  {i}. {entry.domain} {priority_label}{perpetual_label}')
        print(f'     Reason: {entry.reason}')
        print(f'     Queued: {age}')

        if entry.attempts_auto:
            print(f'     Auto attempts: {", ".join(entry.attempts_auto)}')
        if entry.attempts_monkey_do > 0:
            print(f'     Replay attempts: {entry.attempts_monkey_do}')
        if entry.last_flow_date:
            flow_age = format_age(entry.last_flow_date)
            print(f'     Last flow: {flow_age}')

        print()


def cmd_next():
    """Process next site in queue."""
    entry = get_next_queued()

    if not entry:
        print('Queue is empty. Nothing to process.')
        return

    print(f'Processing: {entry.domain}')
    print(f'Reason: {entry.reason}')
    print()

    # Run monkey_see
    result = asyncio.run(monkey_see(entry.domain))

    if result.error:
        print(f'\nError: {result.error}')
        sys.exit(1)


def cmd_see(domain: str):
    """Record flow for specific domain."""
    print(f'Starting monkey_see for {domain}')
    print()

    result = asyncio.run(monkey_see(domain))

    if result.error:
        print(f'\nError: {result.error}')
        sys.exit(1)


def cmd_do(domain: str, headless: bool = True):
    """Replay saved flow for domain."""
    flow_path = FLOWS_DIR / f'{domain}.flow.json'

    if not flow_path.exists():
        print(f'No flow found for {domain}')
        print(f'Run: python scripts/monkey.py --see {domain}')
        sys.exit(1)

    flow_age = get_flow_age_days(domain)
    if flow_age:
        print(f'Flow age: {flow_age:.1f} days')

    print(f'Replaying flow for {domain}...')
    print()

    result = asyncio.run(monkey_do(domain, headless=headless))

    if result.success:
        print(f'\nSuccess: {result.pages} pages, {result.words} words')
    else:
        print(f'\nFailed: {result.error}')
        if result.failed_at is not None:
            print(f'Failed at action {result.failed_at}')
        if result.pages > 0:
            print(f'Partial capture: {result.pages} pages, {result.words} words')
        sys.exit(1)


def cmd_schedule():
    """Run all due scheduled replays."""
    print('Checking replay schedule...')

    results = asyncio.run(run_scheduled_replays())

    if not results:
        print('No replays due.')
        return

    print(f'\nProcessed {len(results)} scheduled replays:')
    for domain, result in results:
        status = 'OK' if result.success else 'FAILED'
        print(f'  {domain}: {status} ({result.pages} pages, {result.words} words)')


def cmd_clear():
    """Clear the queue."""
    count = clear_queue()
    print(f'Cleared {count} entries from queue.')


def cmd_info(domain: str):
    """Show flow info for domain."""
    flow_path = FLOWS_DIR / f'{domain}.flow.json'

    if not flow_path.exists():
        print(f'No flow found for {domain}')
        return

    try:
        flow = Flow.load(flow_path)
    except Exception as e:
        print(f'Error loading flow: {e}')
        return

    print(f'Flow: {domain}')
    print(f'  Recorded: {flow.recorded}')
    print(f'  Duration: {flow.total_duration_sec:.1f}s')
    print(f'  Viewport: {flow.viewport}')
    print(f'  Actions: {len(flow.actions)}')
    print()

    # Show action summary
    action_counts = {}
    for action in flow.actions:
        action_counts[action.action] = action_counts.get(action.action, 0) + 1

    print('  Action breakdown:')
    for action_type, count in sorted(action_counts.items()):
        print(f'    {action_type}: {count}')

    # Show navigations
    navigations = [a for a in flow.actions if a.action == 'navigate']
    if navigations:
        print()
        print('  Pages visited:')
        for nav in navigations:
            print(f'    {nav.url}')

    # Check age
    flow_age = get_flow_age_days(domain)
    if flow_age:
        print()
        if flow_age > 30:
            print(f'  WARNING: Flow is {flow_age:.0f} days old - may be stale')
        else:
            print(f'  Age: {flow_age:.1f} days')


def cmd_queue_add(domain: str, reason: str = 'manual add', tier: int | None = None):
    """Add domain to queue manually."""
    add_to_monkey_queue(domain, reason=reason, tier=tier)
    print(f'Added {domain} to queue')


def cmd_schedules():
    """List replay schedules."""
    schedules = load_replay_schedule()

    if not schedules:
        print('No scheduled replays.')
        return

    print(f'Replay Schedules ({len(schedules)} domains):')
    print()

    for entry in schedules:
        last = format_age(entry.last_success) if entry.last_success else 'never'
        failures = f' ({entry.consecutive_failures} failures)' if entry.consecutive_failures > 0 else ''

        print(f'  {entry.domain}')
        print(f'    Cadence: {entry.cadence}')
        print(f'    Last success: {last}{failures}')
        print()


def main():
    parser = argparse.ArgumentParser(
        description='Monkey CLI - Human-assisted crawling interface',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--list', action='store_true', help='Show queue')
    group.add_argument('--next', action='store_true', help='Process next in queue')
    group.add_argument('--see', metavar='DOMAIN', help='Record flow for domain')
    group.add_argument('--do', metavar='DOMAIN', help='Replay flow for domain')
    group.add_argument('--schedule', action='store_true', help='Run due scheduled replays')
    group.add_argument('--schedules', action='store_true', help='List all schedules')
    group.add_argument('--clear', action='store_true', help='Clear queue')
    group.add_argument('--info', metavar='DOMAIN', help='Show flow info')
    group.add_argument('--add', metavar='DOMAIN', help='Add domain to queue')

    parser.add_argument('--reason', default='manual add', help='Reason for --add')
    parser.add_argument('--tier', type=int, help='Tier for --add (1=high priority)')
    parser.add_argument('--visible', action='store_true', help='Run --do with visible browser')

    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.next:
        cmd_next()
    elif args.see:
        cmd_see(args.see)
    elif args.do:
        cmd_do(args.do, headless=not args.visible)
    elif args.schedule:
        cmd_schedule()
    elif args.schedules:
        cmd_schedules()
    elif args.clear:
        cmd_clear()
    elif args.info:
        cmd_info(args.info)
    elif args.add:
        cmd_queue_add(args.add, reason=args.reason, tier=args.tier)


if __name__ == '__main__':
    main()
