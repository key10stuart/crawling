#!/usr/bin/env python3
"""Test interactive fetch."""

import sys
sys.path.insert(0, '.')

from fetch.interactive import interactive_fetch
from fetch.config import FetchConfig

url = sys.argv[1] if len(sys.argv) > 1 else 'https://www.jbhunt.com'
force = '--force' in sys.argv
debug = '--debug' in sys.argv

print(f'Testing: {url}')
if force:
    print('(forcing interactive mode)')
    config = FetchConfig(min_words=9999)
else:
    config = FetchConfig()

if debug:
    # Debug mode: run interactions manually with verbose output
    from playwright.sync_api import sync_playwright
    from fetch.extractor import extract_content

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print('  Loading page...')
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(3000)

        # Check what we find
        selectors = [
            ('accordions', 'details:not([open]) > summary, [aria-expanded="false"]'),
            ('tabs', '[role="tab"]:not([aria-selected="true"])'),
            ('load-more', 'button:has-text("Load"), button:has-text("More")'),
        ]
        for name, sel in selectors:
            loc = page.locator(sel)
            count = loc.count()
            print(f'  {name}: {count} found')

            # Try clicking first one
            if count > 0:
                before = len(page.inner_text('body').split())
                try:
                    loc.first.click(timeout=3000)
                    page.wait_for_timeout(500)
                    after = len(page.inner_text('body').split())
                    print(f'    clicked first → {before}→{after} words (delta: {after-before})')
                except Exception as e:
                    print(f'    click failed: {e}')

        browser.close()
else:
    result = interactive_fetch(url, config)
    print(f'Words: {result.word_count}')
    print(f'Method: {result.extract_method}')
    print(f'Interactions: {len(result.interaction_log)}')
    for log in result.interaction_log:
        print(f'  {log}')
