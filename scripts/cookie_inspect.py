#!/usr/bin/env python3
"""
Cookie Inspector - Check expiry, test validity, prompt refresh.

Commands:
    --list              List all saved cookies
    --show DOMAIN       Show cookies for domain
    --check DOMAIN      Check if cookies are valid (test request)
    --expiring DAYS     Show cookies expiring within N days
    --refresh DOMAIN    Open browser to refresh cookies
    --delete DOMAIN     Delete cookies for domain
    --export DOMAIN     Export cookies to clipboard (Netscape format)

Usage:
    python scripts/cookie_inspect.py --list
    python scripts/cookie_inspect.py --show knight-swift.com
    python scripts/cookie_inspect.py --check knight-swift.com
    python scripts/cookie_inspect.py --expiring 7
    python scripts/cookie_inspect.py --refresh knight-swift.com
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fetch.monkey import COOKIES_DIR, load_site_cookies, save_site_cookies


def format_expiry(expires: float | None) -> str:
    """Format cookie expiry timestamp."""
    if expires is None or expires < 0:
        return 'session'

    try:
        dt = datetime.fromtimestamp(expires, tz=timezone.utc)
        now = datetime.now(timezone.utc)

        if dt < now:
            return 'EXPIRED'

        delta = dt - now
        if delta.days > 365:
            return f'{delta.days // 365}y'
        elif delta.days > 30:
            return f'{delta.days // 30}mo'
        elif delta.days > 0:
            return f'{delta.days}d'
        elif delta.seconds > 3600:
            return f'{delta.seconds // 3600}h'
        else:
            return f'{delta.seconds // 60}m'
    except Exception:
        return 'unknown'


def days_until_expiry(expires: float | None) -> float | None:
    """Get days until cookie expires."""
    if expires is None or expires < 0:
        return None

    try:
        dt = datetime.fromtimestamp(expires, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = dt - now
        return delta.total_seconds() / 86400
    except Exception:
        return None


def cmd_list():
    """List all saved cookie files."""
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)

    cookie_files = list(COOKIES_DIR.glob('*.json'))

    if not cookie_files:
        print('No saved cookies.')
        return

    print(f'Saved Cookies ({len(cookie_files)} domains):')
    print()

    for path in sorted(cookie_files):
        domain = path.stem
        try:
            cookies = json.loads(path.read_text())
            count = len(cookies)

            # Find soonest expiry
            expires_list = [c.get('expires', -1) for c in cookies if c.get('expires', -1) > 0]
            if expires_list:
                soonest = min(expires_list)
                expiry_str = format_expiry(soonest)
                days = days_until_expiry(soonest)
                if days is not None and days < 0:
                    status = ' [EXPIRED]'
                elif days is not None and days < 7:
                    status = ' [EXPIRING SOON]'
                else:
                    status = ''
            else:
                expiry_str = 'session'
                status = ''

            # File age
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            age = datetime.now(timezone.utc) - mtime
            if age.days > 0:
                age_str = f'{age.days}d ago'
            else:
                age_str = f'{age.seconds // 3600}h ago'

            print(f'  {domain:30} {count:3} cookies  expires: {expiry_str:8}  saved: {age_str}{status}')

        except Exception as e:
            print(f'  {domain:30} ERROR: {e}')


def cmd_show(domain: str):
    """Show cookies for domain in detail."""
    cookies = load_site_cookies(domain)

    if not cookies:
        print(f'No cookies found for {domain}')
        return

    print(f'Cookies for {domain} ({len(cookies)}):')
    print()

    for cookie in sorted(cookies, key=lambda c: c.get('name', '')):
        name = cookie.get('name', 'unknown')
        value = cookie.get('value', '')
        domain_str = cookie.get('domain', '')
        path = cookie.get('path', '/')
        expires = cookie.get('expires', -1)
        http_only = cookie.get('httpOnly', False)
        secure = cookie.get('secure', False)
        same_site = cookie.get('sameSite', 'None')

        expiry_str = format_expiry(expires)
        flags = []
        if http_only:
            flags.append('HttpOnly')
        if secure:
            flags.append('Secure')
        if same_site != 'None':
            flags.append(f'SameSite={same_site}')

        # Truncate long values
        value_display = value[:50] + '...' if len(value) > 50 else value

        print(f'  {name}')
        print(f'    Value:   {value_display}')
        print(f'    Domain:  {domain_str}')
        print(f'    Path:    {path}')
        print(f'    Expires: {expiry_str}')
        if flags:
            print(f'    Flags:   {", ".join(flags)}')
        print()


def cmd_check(domain: str) -> bool:
    """Check if cookies are valid by making test request."""
    import requests

    cookies = load_site_cookies(domain)

    if not cookies:
        print(f'No cookies found for {domain}')
        return False

    # Check for expired cookies
    now = datetime.now(timezone.utc).timestamp()
    expired = [c for c in cookies if c.get('expires', -1) > 0 and c.get('expires') < now]
    if expired:
        print(f'WARNING: {len(expired)} cookies are expired')

    # Build requests cookie jar
    cookie_dict = {}
    for c in cookies:
        if c.get('expires', -1) < 0 or c.get('expires', 0) > now:
            cookie_dict[c['name']] = c['value']

    print(f'Testing {len(cookie_dict)} valid cookies against {domain}...')

    try:
        url = f'https://www.{domain}'
        resp = requests.get(
            url,
            cookies=cookie_dict,
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml',
            },
            timeout=15,
            allow_redirects=True,
        )

        # Check response
        status = resp.status_code
        content_len = len(resp.text)

        # Look for block indicators
        block_indicators = [
            'access denied', '403 forbidden', 'rate limit',
            'captcha', 'challenge', 'blocked', 'bot detected'
        ]
        text_lower = resp.text.lower()
        blocked = any(ind in text_lower for ind in block_indicators)

        print()
        print(f'Status: {status}')
        print(f'Content length: {content_len:,} bytes')

        if status == 200 and content_len > 5000 and not blocked:
            print('Result: VALID - cookies appear to work')
            return True
        elif status == 403 or blocked:
            print('Result: BLOCKED - cookies may be expired or invalid')
            return False
        elif status == 202:
            print('Result: CHALLENGE - site is presenting verification')
            return False
        else:
            print(f'Result: UNCERTAIN - status {status}, check manually')
            return False

    except requests.RequestException as e:
        print(f'Request failed: {e}')
        return False


def cmd_expiring(days: int):
    """Show cookies expiring within N days."""
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)

    print(f'Cookies expiring within {days} days:')
    print()

    found_any = False
    for path in sorted(COOKIES_DIR.glob('*.json')):
        domain = path.stem
        try:
            cookies = json.loads(path.read_text())

            expiring = []
            for c in cookies:
                d = days_until_expiry(c.get('expires'))
                if d is not None and d < days:
                    expiring.append((c.get('name'), d))

            if expiring:
                found_any = True
                print(f'{domain}:')
                for name, d in sorted(expiring, key=lambda x: x[1]):
                    if d < 0:
                        print(f'  {name}: EXPIRED')
                    else:
                        print(f'  {name}: {d:.1f} days')
                print()

        except Exception:
            pass

    if not found_any:
        print('No cookies expiring soon.')


async def cmd_refresh(domain: str):
    """Open browser to refresh cookies."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print('playwright not installed')
        return

    print(f'Opening browser for {domain}...')
    print('Navigate and solve any challenges, then press ENTER when done.')
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()

        # Load existing cookies if available
        existing = load_site_cookies(domain)
        if existing:
            await context.add_cookies(existing)
            print(f'Loaded {len(existing)} existing cookies')

        page = await context.new_page()
        await page.goto(f'https://www.{domain}', wait_until='networkidle')

        # Wait for user
        await asyncio.get_event_loop().run_in_executor(None, input)

        # Save cookies
        cookies = await context.cookies()
        save_site_cookies(domain, cookies)
        print(f'Saved {len(cookies)} cookies')

        await browser.close()


def cmd_delete(domain: str):
    """Delete cookies for domain."""
    path = COOKIES_DIR / f'{domain}.json'

    if not path.exists():
        print(f'No cookies found for {domain}')
        return

    path.unlink()
    print(f'Deleted cookies for {domain}')


def cmd_export(domain: str):
    """Export cookies in Netscape format."""
    cookies = load_site_cookies(domain)

    if not cookies:
        print(f'No cookies found for {domain}')
        return

    # Netscape cookie format
    lines = ['# Netscape HTTP Cookie File']

    for c in cookies:
        domain_str = c.get('domain', '')
        # Netscape format: include_subdomains is TRUE if domain starts with .
        include_sub = 'TRUE' if domain_str.startswith('.') else 'FALSE'
        path = c.get('path', '/')
        secure = 'TRUE' if c.get('secure') else 'FALSE'
        expires = int(c.get('expires', 0))
        name = c.get('name', '')
        value = c.get('value', '')

        line = f'{domain_str}\t{include_sub}\t{path}\t{secure}\t{expires}\t{name}\t{value}'
        lines.append(line)

    output = '\n'.join(lines)
    print(output)
    print()
    print(f'# {len(cookies)} cookies exported')


def main():
    parser = argparse.ArgumentParser(
        description='Cookie Inspector - Manage saved cookies',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--list', action='store_true', help='List all saved cookies')
    group.add_argument('--show', metavar='DOMAIN', help='Show cookies for domain')
    group.add_argument('--check', metavar='DOMAIN', help='Test if cookies are valid')
    group.add_argument('--expiring', type=int, metavar='DAYS', help='Show cookies expiring within N days')
    group.add_argument('--refresh', metavar='DOMAIN', help='Open browser to refresh cookies')
    group.add_argument('--delete', metavar='DOMAIN', help='Delete cookies for domain')
    group.add_argument('--export', metavar='DOMAIN', help='Export cookies (Netscape format)')

    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.show:
        cmd_show(args.show)
    elif args.check:
        valid = cmd_check(args.check)
        sys.exit(0 if valid else 1)
    elif args.expiring:
        cmd_expiring(args.expiring)
    elif args.refresh:
        asyncio.run(cmd_refresh(args.refresh))
    elif args.delete:
        cmd_delete(args.delete)
    elif args.export:
        cmd_export(args.export)


if __name__ == '__main__':
    main()
