#!/usr/bin/env python3
"""
Manual cookie bootstrap tool for CAPTCHA / challenge sites.
"""

import argparse
import json
from pathlib import Path


def save_cookies(domain: str, cookies: list[dict]) -> Path:
    cookies_dir = Path.home() / ".crawl" / "cookies"
    cookies_dir.mkdir(parents=True, exist_ok=True)
    path = cookies_dir / f"{domain}.json"
    path.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap cookies for a domain")
    parser.add_argument("--domain", required=True, help="Domain to open (e.g., knight-swift.com)")
    parser.add_argument("--url", help="Optional full URL (defaults to https://www.{domain})")
    args = parser.parse_args()

    url = args.url or f"https://www.{args.domain}"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is required: pip install playwright && playwright install")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url)
        input(f"Solve any challenges for {args.domain}, then press Enter to save cookies...")
        cookies = context.cookies()
        path = save_cookies(args.domain, cookies)
        print(f"Saved {len(cookies)} cookies to {path}")
        browser.close()


if __name__ == "__main__":
    main()
