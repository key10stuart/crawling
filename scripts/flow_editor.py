#!/usr/bin/env python3
"""
Flow Editor - Debug/edit recorded flows without re-recording.

Commands:
    --show DOMAIN       Show flow actions in detail
    --validate DOMAIN   Validate flow file structure
    --trim DOMAIN       Remove actions after specified index
    --remove DOMAIN     Remove specific action by index
    --adjust-delays DOMAIN  Scale all delays by factor
    --export DOMAIN     Export to simpler format for manual editing
    --import FILE       Import from edited file

Usage:
    python scripts/flow_editor.py --show knight-swift.com
    python scripts/flow_editor.py --validate knight-swift.com
    python scripts/flow_editor.py --trim knight-swift.com --after 5
    python scripts/flow_editor.py --remove knight-swift.com --index 3
    python scripts/flow_editor.py --adjust-delays knight-swift.com --factor 1.5
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fetch.monkey import Flow, FlowAction, FLOWS_DIR


def cmd_show(domain: str, verbose: bool = False):
    """Show flow actions in detail."""
    flow_path = FLOWS_DIR / f'{domain}.flow.json'

    if not flow_path.exists():
        print(f'No flow found for {domain}')
        sys.exit(1)

    flow = Flow.load(flow_path)

    print(f'Flow: {domain}')
    print(f'Recorded: {flow.recorded}')
    print(f'Duration: {flow.total_duration_sec:.1f}s')
    print(f'Viewport: {flow.viewport["width"]}x{flow.viewport["height"]}')
    print(f'Actions: {len(flow.actions)}')
    print()
    print('Actions:')
    print('-' * 60)

    cumulative_time = 0
    for i, action in enumerate(flow.actions):
        cumulative_time += action.delay_since_last

        # Format action based on type
        if action.action == 'navigate':
            desc = f'navigate -> {action.url}'
        elif action.action == 'click':
            pos = f'({action.x:.0f}, {action.y:.0f})' if action.x else ''
            sel = action.selector[:50] if action.selector else ''
            meta_text = action.meta.get('text', '')[:30] if action.meta else ''
            desc = f'click {pos} {sel}'
            if meta_text:
                desc += f' "{meta_text}"'
        elif action.action == 'scroll':
            desc = f'scroll {action.direction} {action.amount}px'
        elif action.action == 'type':
            desc = f'type "{action.text[:30]}..."' if len(action.text or '') > 30 else f'type "{action.text}"'
        else:
            desc = action.action

        delay_str = f'+{action.delay_since_last:.2f}s' if action.delay_since_last > 0 else ''
        time_str = f'{cumulative_time:.1f}s'

        print(f'[{i:3d}] {time_str:>8} {delay_str:>8}  {desc}')

        if verbose and action.meta:
            for k, v in action.meta.items():
                if v:
                    print(f'                         {k}: {v}')

    print('-' * 60)


def cmd_validate(domain: str) -> bool:
    """Validate flow file structure."""
    flow_path = FLOWS_DIR / f'{domain}.flow.json'

    if not flow_path.exists():
        print(f'ERROR: No flow found for {domain}')
        return False

    errors = []
    warnings = []

    try:
        flow = Flow.load(flow_path)
    except Exception as e:
        print(f'ERROR: Failed to parse flow: {e}')
        return False

    # Check required fields
    if not flow.domain:
        errors.append('Missing domain')
    if not flow.recorded:
        errors.append('Missing recorded timestamp')
    if not flow.viewport:
        errors.append('Missing viewport')
    if not flow.actions:
        warnings.append('Flow has no actions')

    # Validate actions
    for i, action in enumerate(flow.actions):
        if not action.action:
            errors.append(f'Action {i}: missing action type')

        if action.action == 'navigate' and not action.url:
            errors.append(f'Action {i}: navigate missing url')

        if action.action == 'click':
            if not action.x and not action.selector:
                warnings.append(f'Action {i}: click has no position or selector')

        if action.delay_since_last < 0:
            errors.append(f'Action {i}: negative delay')

    # Check for suspicious patterns
    total_delay = sum(a.delay_since_last for a in flow.actions)
    if total_delay < 1 and len(flow.actions) > 5:
        warnings.append('Very fast flow - may trigger bot detection')

    navigate_count = sum(1 for a in flow.actions if a.action == 'navigate')
    if navigate_count == 0:
        warnings.append('No navigation actions - flow may be incomplete')

    # Report results
    print(f'Validating: {domain}')
    print()

    if errors:
        print('ERRORS:')
        for e in errors:
            print(f'  - {e}')

    if warnings:
        print('WARNINGS:')
        for w in warnings:
            print(f'  - {w}')

    if not errors and not warnings:
        print('Flow is valid.')

    return len(errors) == 0


def cmd_trim(domain: str, after: int):
    """Remove actions after specified index."""
    flow_path = FLOWS_DIR / f'{domain}.flow.json'

    if not flow_path.exists():
        print(f'No flow found for {domain}')
        sys.exit(1)

    flow = Flow.load(flow_path)
    original_count = len(flow.actions)

    if after < 0 or after >= original_count:
        print(f'Invalid index: {after} (flow has {original_count} actions)')
        sys.exit(1)

    # Keep actions up to and including 'after'
    flow.actions = flow.actions[:after + 1]

    # Recalculate duration
    flow.total_duration_sec = sum(a.delay_since_last for a in flow.actions)

    # Backup original
    backup_path = flow_path.with_suffix('.flow.json.bak')
    backup_path.write_text(flow_path.read_text())

    # Save trimmed flow
    flow.save(flow_path)

    removed = original_count - len(flow.actions)
    print(f'Trimmed {removed} actions (kept {len(flow.actions)})')
    print(f'Backup saved to {backup_path}')


def cmd_remove(domain: str, index: int):
    """Remove specific action by index."""
    flow_path = FLOWS_DIR / f'{domain}.flow.json'

    if not flow_path.exists():
        print(f'No flow found for {domain}')
        sys.exit(1)

    flow = Flow.load(flow_path)

    if index < 0 or index >= len(flow.actions):
        print(f'Invalid index: {index} (flow has {len(flow.actions)} actions)')
        sys.exit(1)

    # Get action info before removing
    removed_action = flow.actions[index]
    print(f'Removing action {index}: {removed_action.action}')

    # If removing non-first action, add its delay to next action
    if index < len(flow.actions) - 1:
        flow.actions[index + 1].delay_since_last += removed_action.delay_since_last

    # Remove action
    flow.actions.pop(index)

    # Recalculate duration
    flow.total_duration_sec = sum(a.delay_since_last for a in flow.actions)

    # Backup original
    backup_path = flow_path.with_suffix('.flow.json.bak')
    backup_path.write_text(flow_path.read_text())

    # Save modified flow
    flow.save(flow_path)

    print(f'Action removed. Flow now has {len(flow.actions)} actions.')
    print(f'Backup saved to {backup_path}')


def cmd_adjust_delays(domain: str, factor: float):
    """Scale all delays by factor."""
    flow_path = FLOWS_DIR / f'{domain}.flow.json'

    if not flow_path.exists():
        print(f'No flow found for {domain}')
        sys.exit(1)

    if factor <= 0:
        print('Factor must be positive')
        sys.exit(1)

    flow = Flow.load(flow_path)

    # Adjust delays
    for action in flow.actions:
        action.delay_since_last *= factor

    # Recalculate duration
    flow.total_duration_sec *= factor

    # Backup original
    backup_path = flow_path.with_suffix('.flow.json.bak')
    backup_path.write_text(flow_path.read_text())

    # Save modified flow
    flow.save(flow_path)

    print(f'Delays scaled by {factor}x')
    print(f'New duration: {flow.total_duration_sec:.1f}s')
    print(f'Backup saved to {backup_path}')


def cmd_export(domain: str, output: str | None = None):
    """Export to simpler YAML format for manual editing."""
    import yaml

    flow_path = FLOWS_DIR / f'{domain}.flow.json'

    if not flow_path.exists():
        print(f'No flow found for {domain}')
        sys.exit(1)

    flow = Flow.load(flow_path)

    # Convert to simpler format
    export_data = {
        'domain': flow.domain,
        'recorded': flow.recorded,
        'viewport': flow.viewport,
        'actions': []
    }

    for i, action in enumerate(flow.actions):
        entry = {
            'index': i,
            'action': action.action,
            'delay': round(action.delay_since_last, 2),
        }

        if action.url:
            entry['url'] = action.url
        if action.selector:
            entry['selector'] = action.selector
        if action.x is not None:
            entry['x'] = round(action.x)
            entry['y'] = round(action.y)
        if action.direction:
            entry['direction'] = action.direction
            entry['amount'] = action.amount
        if action.text:
            entry['text'] = action.text
        if action.meta and action.meta.get('text'):
            entry['element_text'] = action.meta['text'][:50]

        export_data['actions'].append(entry)

    output_path = Path(output) if output else Path(f'{domain}.flow.yaml')
    output_path.write_text(yaml.dump(export_data, default_flow_style=False, sort_keys=False))

    print(f'Exported to {output_path}')
    print('Edit the file, then import with --import')


def cmd_import(filepath: str):
    """Import from edited YAML file."""
    import yaml

    path = Path(filepath)
    if not path.exists():
        print(f'File not found: {filepath}')
        sys.exit(1)

    data = yaml.safe_load(path.read_text())
    domain = data['domain']

    # Convert back to Flow format
    actions = []
    for entry in data['actions']:
        action = FlowAction(
            action=entry['action'],
            timestamp=0,  # Will be reconstructed
            delay_since_last=entry.get('delay', 0),
            url=entry.get('url'),
            selector=entry.get('selector'),
            x=entry.get('x'),
            y=entry.get('y'),
            direction=entry.get('direction'),
            amount=entry.get('amount'),
            text=entry.get('text'),
            meta={'text': entry.get('element_text')} if entry.get('element_text') else {},
        )
        actions.append(action)

    # Reconstruct timestamps
    current_time = 0
    for action in actions:
        current_time += action.delay_since_last
        action.timestamp = current_time

    flow = Flow(
        domain=domain,
        recorded=data.get('recorded', datetime.now().isoformat()),
        total_duration_sec=current_time,
        viewport=data.get('viewport', {'width': 1920, 'height': 1080}),
        user_agent=None,
        actions=actions,
    )

    # Backup existing flow if present
    flow_path = FLOWS_DIR / f'{domain}.flow.json'
    if flow_path.exists():
        backup_path = flow_path.with_suffix('.flow.json.bak')
        backup_path.write_text(flow_path.read_text())
        print(f'Backed up existing flow to {backup_path}')

    # Save new flow
    flow.save(flow_path)
    print(f'Imported {len(actions)} actions for {domain}')


def cmd_insert(domain: str, after: int, action_type: str, **kwargs):
    """Insert a new action after specified index."""
    flow_path = FLOWS_DIR / f'{domain}.flow.json'

    if not flow_path.exists():
        print(f'No flow found for {domain}')
        sys.exit(1)

    flow = Flow.load(flow_path)

    if after < -1 or after >= len(flow.actions):
        print(f'Invalid index: {after} (flow has {len(flow.actions)} actions)')
        sys.exit(1)

    # Create new action
    new_action = FlowAction(
        action=action_type,
        timestamp=0,
        delay_since_last=kwargs.get('delay', 1.0),
        url=kwargs.get('url'),
        selector=kwargs.get('selector'),
        x=kwargs.get('x'),
        y=kwargs.get('y'),
        direction=kwargs.get('direction'),
        amount=kwargs.get('amount'),
        text=kwargs.get('text'),
    )

    # Insert after specified index
    flow.actions.insert(after + 1, new_action)

    # Recalculate duration
    flow.total_duration_sec = sum(a.delay_since_last for a in flow.actions)

    # Backup and save
    backup_path = flow_path.with_suffix('.flow.json.bak')
    backup_path.write_text(flow_path.read_text())
    flow.save(flow_path)

    print(f'Inserted {action_type} action at index {after + 1}')
    print(f'Backup saved to {backup_path}')


def main():
    parser = argparse.ArgumentParser(
        description='Flow Editor - Debug/edit recorded flows',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--show', metavar='DOMAIN', help='Show flow actions')
    group.add_argument('--validate', metavar='DOMAIN', help='Validate flow')
    group.add_argument('--trim', metavar='DOMAIN', help='Trim flow after index')
    group.add_argument('--remove', metavar='DOMAIN', help='Remove action at index')
    group.add_argument('--adjust-delays', metavar='DOMAIN', help='Scale delays')
    group.add_argument('--export', metavar='DOMAIN', help='Export to YAML')
    group.add_argument('--import', dest='import_file', metavar='FILE', help='Import from YAML')

    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--after', type=int, help='Index for --trim')
    parser.add_argument('--index', type=int, help='Index for --remove')
    parser.add_argument('--factor', type=float, help='Factor for --adjust-delays')
    parser.add_argument('--output', '-o', help='Output file for --export')

    args = parser.parse_args()

    if args.show:
        cmd_show(args.show, verbose=args.verbose)
    elif args.validate:
        valid = cmd_validate(args.validate)
        sys.exit(0 if valid else 1)
    elif args.trim:
        if args.after is None:
            print('--trim requires --after INDEX')
            sys.exit(1)
        cmd_trim(args.trim, args.after)
    elif args.remove:
        if args.index is None:
            print('--remove requires --index INDEX')
            sys.exit(1)
        cmd_remove(args.remove, args.index)
    elif args.adjust_delays:
        if args.factor is None:
            print('--adjust-delays requires --factor N')
            sys.exit(1)
        cmd_adjust_delays(args.adjust_delays, args.factor)
    elif args.export:
        cmd_export(args.export, args.output)
    elif args.import_file:
        cmd_import(args.import_file)


if __name__ == '__main__':
    main()
