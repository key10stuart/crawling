#!/usr/bin/env python3
"""
Flow Diff - Compare old vs new flow for same domain.

Useful for:
- Understanding what changed when re-recording a flow
- Comparing flows before/after site changes
- Validating backup flows against current

Usage:
    python scripts/flow_diff.py flow1.json flow2.json
    python scripts/flow_diff.py --domain knight-swift.com  # compares current vs backup
    python scripts/flow_diff.py --domain knight-swift.com --history  # show all versions
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fetch.monkey import Flow, FLOWS_DIR


def load_flow_file(path: Path) -> Flow:
    """Load flow from path."""
    return Flow.load(path)


def action_signature(action) -> str:
    """Create a signature string for action comparison."""
    if action.action == 'navigate':
        return f'navigate:{action.url}'
    elif action.action == 'click':
        # Normalize position to grid for fuzzy matching
        x_grid = round((action.x or 0) / 50) * 50
        y_grid = round((action.y or 0) / 50) * 50
        selector = action.selector[:30] if action.selector else ''
        meta_text = action.meta.get('text', '')[:20] if action.meta else ''
        return f'click:({x_grid},{y_grid}):{selector}:{meta_text}'
    elif action.action == 'scroll':
        return f'scroll:{action.direction}:{action.amount}'
    elif action.action == 'type':
        return f'type:{action.text}'
    else:
        return action.action


def compare_flows(flow1: Flow, flow2: Flow) -> dict:
    """
    Compare two flows and return diff analysis.

    Returns dict with:
    - matching_actions: int
    - total_actions: (int, int)
    - added_actions: list of actions in flow2 not in flow1
    - removed_actions: list of actions in flow1 not in flow2
    - modified_actions: list of (flow1_action, flow2_action) pairs
    - url_diff: changes in visited URLs
    - timing_diff: difference in total timing
    """
    # Get action signatures
    sigs1 = [action_signature(a) for a in flow1.actions]
    sigs2 = [action_signature(a) for a in flow2.actions]

    # Use SequenceMatcher for alignment
    matcher = SequenceMatcher(None, sigs1, sigs2)

    added = []
    removed = []
    modified = []
    matching = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            matching += i2 - i1
            # Check for timing differences even in matching actions
            for k in range(i2 - i1):
                a1, a2 = flow1.actions[i1 + k], flow2.actions[j1 + k]
                if abs(a1.delay_since_last - a2.delay_since_last) > 0.5:
                    modified.append((i1 + k, a1, j1 + k, a2, 'timing'))
        elif tag == 'replace':
            for k in range(max(i2 - i1, j2 - j1)):
                if k < i2 - i1 and k < j2 - j1:
                    modified.append((i1 + k, flow1.actions[i1 + k], j1 + k, flow2.actions[j1 + k], 'replaced'))
                elif k < i2 - i1:
                    removed.append((i1 + k, flow1.actions[i1 + k]))
                else:
                    added.append((j1 + k, flow2.actions[j1 + k]))
        elif tag == 'delete':
            for k in range(i1, i2):
                removed.append((k, flow1.actions[k]))
        elif tag == 'insert':
            for k in range(j1, j2):
                added.append((k, flow2.actions[k]))

    # Extract URLs visited
    urls1 = [a.url for a in flow1.actions if a.action == 'navigate' and a.url]
    urls2 = [a.url for a in flow2.actions if a.action == 'navigate' and a.url]

    urls_added = set(urls2) - set(urls1)
    urls_removed = set(urls1) - set(urls2)

    return {
        'matching': matching,
        'total': (len(flow1.actions), len(flow2.actions)),
        'added': added,
        'removed': removed,
        'modified': modified,
        'urls_added': list(urls_added),
        'urls_removed': list(urls_removed),
        'timing_diff': flow2.total_duration_sec - flow1.total_duration_sec,
        'similarity': matcher.ratio(),
    }


def format_action(action, verbose: bool = False) -> str:
    """Format action for display."""
    if action.action == 'navigate':
        return f'navigate -> {action.url}'
    elif action.action == 'click':
        pos = f'({action.x:.0f}, {action.y:.0f})' if action.x else ''
        text = action.meta.get('text', '')[:30] if action.meta else ''
        return f'click {pos} "{text}"' if text else f'click {pos}'
    elif action.action == 'scroll':
        return f'scroll {action.direction} {action.amount}px'
    elif action.action == 'type':
        return f'type "{action.text}"'
    else:
        return action.action


def print_diff(diff: dict, flow1_name: str, flow2_name: str, verbose: bool = False):
    """Print formatted diff output."""
    print(f'Comparing flows:')
    print(f'  OLD: {flow1_name} ({diff["total"][0]} actions)')
    print(f'  NEW: {flow2_name} ({diff["total"][1]} actions)')
    print()

    similarity_pct = diff['similarity'] * 100
    print(f'Similarity: {similarity_pct:.1f}%')
    print(f'Matching actions: {diff["matching"]}')
    print(f'Timing difference: {diff["timing_diff"]:+.1f}s')
    print()

    # URL changes
    if diff['urls_added'] or diff['urls_removed']:
        print('URL Changes:')
        for url in diff['urls_removed']:
            print(f'  - {url}')
        for url in diff['urls_added']:
            print(f'  + {url}')
        print()

    # Removed actions
    if diff['removed']:
        print(f'Removed Actions ({len(diff["removed"])}):')
        for idx, action in diff['removed']:
            print(f'  [{idx}] - {format_action(action)}')
        print()

    # Added actions
    if diff['added']:
        print(f'Added Actions ({len(diff["added"])}):')
        for idx, action in diff['added']:
            print(f'  [{idx}] + {format_action(action)}')
        print()

    # Modified actions
    if diff['modified'] and verbose:
        print(f'Modified Actions ({len(diff["modified"])}):')
        for idx1, a1, idx2, a2, change_type in diff['modified']:
            print(f'  [{idx1}] -> [{idx2}] ({change_type})')
            print(f'    OLD: {format_action(a1)}')
            print(f'    NEW: {format_action(a2)}')
        print()

    # Summary
    if not diff['added'] and not diff['removed'] and not diff['urls_added'] and not diff['urls_removed']:
        if diff['similarity'] > 0.99:
            print('Flows are essentially identical.')
        else:
            print('Flows have minor timing differences only.')


def find_backup(domain: str) -> Path | None:
    """Find backup file for domain."""
    backup = FLOWS_DIR / f'{domain}.flow.json.bak'
    return backup if backup.exists() else None


def list_flow_history(domain: str):
    """List all flow versions for a domain."""
    base_path = FLOWS_DIR / f'{domain}.flow.json'

    versions = []

    # Current flow
    if base_path.exists():
        flow = Flow.load(base_path)
        versions.append(('current', base_path, flow.recorded))

    # Backup
    backup = FLOWS_DIR / f'{domain}.flow.json.bak'
    if backup.exists():
        try:
            flow = Flow.load(backup)
            versions.append(('backup', backup, flow.recorded))
        except Exception:
            versions.append(('backup', backup, 'unknown'))

    # Numbered backups
    for i in range(1, 10):
        numbered = FLOWS_DIR / f'{domain}.flow.json.{i}'
        if numbered.exists():
            try:
                flow = Flow.load(numbered)
                versions.append((f'v{i}', numbered, flow.recorded))
            except Exception:
                versions.append((f'v{i}', numbered, 'unknown'))

    if not versions:
        print(f'No flows found for {domain}')
        return

    print(f'Flow history for {domain}:')
    print()
    for label, path, recorded in versions:
        print(f'  {label:10} {path.name:30} recorded: {recorded}')


def cmd_compare(path1: str, path2: str, verbose: bool = False):
    """Compare two flow files."""
    flow1 = load_flow_file(Path(path1))
    flow2 = load_flow_file(Path(path2))

    diff = compare_flows(flow1, flow2)
    print_diff(diff, path1, path2, verbose=verbose)


def cmd_domain(domain: str, verbose: bool = False):
    """Compare current flow vs backup for domain."""
    current = FLOWS_DIR / f'{domain}.flow.json'
    backup = find_backup(domain)

    if not current.exists():
        print(f'No current flow for {domain}')
        sys.exit(1)

    if not backup:
        print(f'No backup flow for {domain}')
        print('Create a backup with: cp ~/.crawl/flows/{domain}.flow.json ~/.crawl/flows/{domain}.flow.json.bak')
        sys.exit(1)

    flow1 = Flow.load(backup)
    flow2 = Flow.load(current)

    diff = compare_flows(flow1, flow2)
    print_diff(diff, f'{domain} (backup)', f'{domain} (current)', verbose=verbose)


def main():
    parser = argparse.ArgumentParser(
        description='Flow Diff - Compare flow files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('files', nargs='*', help='Two flow files to compare')
    parser.add_argument('--domain', '-d', help='Compare current vs backup for domain')
    parser.add_argument('--history', action='store_true', help='Show flow history for domain')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if args.domain and args.history:
        list_flow_history(args.domain)
    elif args.domain:
        cmd_domain(args.domain, verbose=args.verbose)
    elif len(args.files) == 2:
        cmd_compare(args.files[0], args.files[1], verbose=args.verbose)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
