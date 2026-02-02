#!/usr/bin/env python3
"""
Monkey Dashboard - Rich terminal UI for queue management.

Provides an interactive view of:
- Queue status with detailed info
- Flow inventory with age/status
- Cookie status with expiry warnings
- Replay schedule status

Usage:
    python scripts/monkey_dashboard.py
    python scripts/monkey_dashboard.py --watch    # Auto-refresh every 5s
    python scripts/monkey_dashboard.py --compact  # Minimal output
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fetch.monkey import (
    MonkeyQueue,
    Flow,
    FLOWS_DIR,
    COOKIES_DIR,
    list_queue,
    load_replay_schedule,
    get_flow_age_days,
    check_perpetual_manual,
)


# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'


def colored(text: str, color: str) -> str:
    """Apply ANSI color to text."""
    return f'{color}{text}{Colors.RESET}'


def format_age(iso_timestamp: str) -> str:
    """Format ISO timestamp as human-readable age."""
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
        delta = datetime.now(timezone.utc) - dt
        seconds = delta.total_seconds()

        if seconds < 60:
            return f'{int(seconds)}s'
        elif seconds < 3600:
            return f'{int(seconds / 60)}m'
        elif seconds < 86400:
            return f'{int(seconds / 3600)}h'
        else:
            return f'{int(seconds / 86400)}d'
    except Exception:
        return '?'


def get_cookie_status(domain: str) -> tuple[int, str, str]:
    """Get cookie count, expiry status, and color."""
    import json

    cookie_file = COOKIES_DIR / f'{domain}.json'
    if not cookie_file.exists():
        return 0, 'none', Colors.DIM

    try:
        cookies = json.loads(cookie_file.read_text())
        count = len(cookies)

        # Check expiry
        now = datetime.now(timezone.utc).timestamp()
        expires_list = [c.get('expires', -1) for c in cookies if c.get('expires', -1) > 0]

        if not expires_list:
            return count, 'session', Colors.CYAN

        soonest = min(expires_list)
        if soonest < now:
            return count, 'EXPIRED', Colors.RED
        elif soonest < now + 7 * 86400:
            days = (soonest - now) / 86400
            return count, f'{days:.0f}d left', Colors.YELLOW
        else:
            return count, 'ok', Colors.GREEN

    except Exception:
        return 0, 'error', Colors.RED


def render_queue_section() -> list[str]:
    """Render queue status section."""
    lines = []
    lines.append(colored('QUEUE', Colors.BOLD + Colors.HEADER))
    lines.append(colored('─' * 70, Colors.DIM))

    queue_entries = list_queue()

    if not queue_entries:
        lines.append(colored('  (empty)', Colors.DIM))
        lines.append('')
        return lines

    # Sort by priority
    priority_order = {'high': 0, 'normal': 1, 'low': 2}
    sorted_entries = sorted(
        queue_entries,
        key=lambda e: (priority_order.get(e.priority, 1), e.added)
    )

    for i, entry in enumerate(sorted_entries, 1):
        # Priority indicator
        if entry.priority == 'high':
            priority = colored('[HIGH]', Colors.RED + Colors.BOLD)
        elif entry.priority == 'low':
            priority = colored('[LOW]', Colors.DIM)
        else:
            priority = ''

        # Perpetual manual indicator
        perpetual = colored(' [PERPETUAL]', Colors.YELLOW) if check_perpetual_manual(entry.domain) else ''

        # Age
        age = format_age(entry.added)

        # Flow status
        flow_age = get_flow_age_days(entry.domain)
        if flow_age is None:
            flow_status = colored('no flow', Colors.DIM)
        elif flow_age > 30:
            flow_status = colored(f'flow: {flow_age:.0f}d old', Colors.YELLOW)
        else:
            flow_status = colored(f'flow: {flow_age:.0f}d old', Colors.GREEN)

        # Cookie status
        cookie_count, cookie_status, cookie_color = get_cookie_status(entry.domain)
        cookie_str = colored(f'{cookie_count} cookies ({cookie_status})', cookie_color)

        lines.append(f'  {i}. {colored(entry.domain, Colors.BOLD)} {priority}{perpetual}')
        lines.append(f'     {colored("Reason:", Colors.DIM)} {entry.reason}')
        lines.append(f'     {colored("Queued:", Colors.DIM)} {age} ago  |  {flow_status}  |  {cookie_str}')

        if entry.attempts_auto:
            lines.append(f'     {colored("Tried:", Colors.DIM)} {", ".join(entry.attempts_auto)}')

        lines.append('')

    return lines


def render_flows_section() -> list[str]:
    """Render flow inventory section."""
    lines = []
    lines.append(colored('FLOWS', Colors.BOLD + Colors.HEADER))
    lines.append(colored('─' * 70, Colors.DIM))

    FLOWS_DIR.mkdir(parents=True, exist_ok=True)
    flow_files = list(FLOWS_DIR.glob('*.flow.json'))

    if not flow_files:
        lines.append(colored('  (no flows recorded)', Colors.DIM))
        lines.append('')
        return lines

    # Sort by modification time (most recent first)
    flow_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for path in flow_files[:10]:  # Show top 10
        domain = path.stem.replace('.flow', '')

        try:
            flow = Flow.load(path)
            action_count = len(flow.actions)
            duration = flow.total_duration_sec

            age_days = get_flow_age_days(domain)
            if age_days is None:
                age_str = '?'
                age_color = Colors.DIM
            elif age_days > 30:
                age_str = f'{age_days:.0f}d'
                age_color = Colors.YELLOW
            elif age_days > 7:
                age_str = f'{age_days:.0f}d'
                age_color = Colors.CYAN
            else:
                age_str = f'{age_days:.0f}d'
                age_color = Colors.GREEN

            lines.append(
                f'  {colored(domain, Colors.BOLD):40} '
                f'{action_count:3} actions  '
                f'{duration:5.0f}s  '
                f'{colored(age_str, age_color):>6} old'
            )

        except Exception as e:
            lines.append(f'  {colored(domain, Colors.BOLD):40} {colored(f"ERROR: {e}", Colors.RED)}')

    if len(flow_files) > 10:
        lines.append(colored(f'  ... and {len(flow_files) - 10} more', Colors.DIM))

    lines.append('')
    return lines


def render_schedule_section() -> list[str]:
    """Render replay schedule section."""
    lines = []
    lines.append(colored('SCHEDULE', Colors.BOLD + Colors.HEADER))
    lines.append(colored('─' * 70, Colors.DIM))

    schedules = load_replay_schedule()

    if not schedules:
        lines.append(colored('  (no scheduled replays)', Colors.DIM))
        lines.append('')
        return lines

    for entry in schedules:
        # Cadence
        cadence = entry.cadence

        # Last success
        if entry.last_success:
            last_age = format_age(entry.last_success)
            last_str = f'{last_age} ago'
        else:
            last_str = 'never'

        # Failure indicator
        if entry.consecutive_failures >= 2:
            status = colored('FAILING', Colors.RED + Colors.BOLD)
        elif entry.consecutive_failures == 1:
            status = colored('1 failure', Colors.YELLOW)
        else:
            status = colored('ok', Colors.GREEN)

        lines.append(
            f'  {colored(entry.domain, Colors.BOLD):40} '
            f'{cadence:8} '
            f'last: {last_str:10} '
            f'{status}'
        )

    lines.append('')
    return lines


def render_cookies_section() -> list[str]:
    """Render cookie status section."""
    lines = []
    lines.append(colored('COOKIES', Colors.BOLD + Colors.HEADER))
    lines.append(colored('─' * 70, Colors.DIM))

    COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    cookie_files = list(COOKIES_DIR.glob('*.json'))

    if not cookie_files:
        lines.append(colored('  (no saved cookies)', Colors.DIM))
        lines.append('')
        return lines

    # Check for issues
    issues = []
    ok_count = 0

    for path in cookie_files:
        domain = path.stem
        count, status, color = get_cookie_status(domain)

        if status == 'EXPIRED':
            issues.append((domain, status, color))
        elif 'left' in status:
            issues.append((domain, status, color))
        else:
            ok_count += 1

    if issues:
        for domain, status, color in issues:
            lines.append(f'  {colored(domain, Colors.BOLD):40} {colored(status, color)}')

    if ok_count > 0:
        lines.append(colored(f'  + {ok_count} domains with valid cookies', Colors.GREEN))

    lines.append('')
    return lines


def render_summary() -> list[str]:
    """Render summary line."""
    queue_count = len(list_queue())
    flow_count = len(list(FLOWS_DIR.glob('*.flow.json'))) if FLOWS_DIR.exists() else 0
    schedule_count = len(load_replay_schedule())
    cookie_count = len(list(COOKIES_DIR.glob('*.json'))) if COOKIES_DIR.exists() else 0

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    parts = [
        f'Queue: {queue_count}',
        f'Flows: {flow_count}',
        f'Scheduled: {schedule_count}',
        f'Cookies: {cookie_count}',
    ]

    return [
        colored('─' * 70, Colors.DIM),
        colored(f'{now}  |  {" | ".join(parts)}', Colors.DIM),
        '',
    ]


def render_dashboard(compact: bool = False) -> str:
    """Render full dashboard."""
    lines = []

    # Header
    lines.append('')
    lines.append(colored('  MONKEY DASHBOARD', Colors.BOLD + Colors.CYAN))
    lines.append('')

    # Sections
    lines.extend(render_queue_section())

    if not compact:
        lines.extend(render_flows_section())
        lines.extend(render_schedule_section())
        lines.extend(render_cookies_section())

    lines.extend(render_summary())

    return '\n'.join(lines)


def clear_screen():
    """Clear terminal screen."""
    print('\033[2J\033[H', end='')


def main():
    parser = argparse.ArgumentParser(
        description='Monkey Dashboard - Rich terminal UI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--watch', '-w', action='store_true', help='Auto-refresh every 5s')
    parser.add_argument('--compact', '-c', action='store_true', help='Minimal output (queue only)')
    parser.add_argument('--interval', '-i', type=int, default=5, help='Refresh interval for --watch')

    args = parser.parse_args()

    if args.watch:
        try:
            while True:
                clear_screen()
                print(render_dashboard(compact=args.compact))
                print(colored(f'Refreshing in {args.interval}s... (Ctrl+C to exit)', Colors.DIM))
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print('\nExiting.')
    else:
        print(render_dashboard(compact=args.compact))


if __name__ == '__main__':
    main()
