"""
Fetch layer with fallback chain:
requests → playwright → playwright+stealth
"""

import random
from typing import Literal
from urllib.parse import urlparse

import requests

from .config import FetchConfig, USER_AGENTS, DEFAULT_HEADERS, SKIP_EXTENSIONS
from .cookies import load_cookies


class FetchError(Exception):
    """Raised when all fetch strategies fail."""
    pass


def should_skip_url(url: str) -> bool:
    """Check if URL should be skipped (non-HTML resources)."""
    parsed = urlparse(url)
    path_lower = parsed.path.lower()
    return any(path_lower.endswith(ext) for ext in SKIP_EXTENSIONS)


def get_user_agent(config: FetchConfig) -> str:
    """Get user agent string (fixed or rotated)."""
    if config.user_agent:
        return config.user_agent
    if config.rotate_user_agent:
        return random.choice(USER_AGENTS)
    return USER_AGENTS[0]


def fetch_requests(
    url: str,
    config: FetchConfig,
    conditional_headers: dict | None = None,
) -> tuple[str | None, str | None, int | None, dict, bool]:
    """
    Fetch URL using requests library.

    Args:
        url: URL to fetch
        config: Fetch configuration

    Returns:
        Tuple of (html, final_url) or (None, None) on failure
    """
    headers = DEFAULT_HEADERS.copy()
    headers['User-Agent'] = get_user_agent(config)
    if conditional_headers:
        headers.update(conditional_headers)

    try:
        resp = requests.get(
            url,
            headers=headers,
            timeout=config.timeout,
            allow_redirects=True,
        )

        if resp.status_code == 304:
            return None, resp.url, resp.status_code, dict(resp.headers), True

        resp.raise_for_status()

        # Check content type
        content_type = resp.headers.get('Content-Type', '').lower()
        if 'text/html' not in content_type and 'application/xhtml' not in content_type:
            return None, None, resp.status_code, dict(resp.headers), False

        return resp.text, resp.url, resp.status_code, dict(resp.headers), False

    except requests.RequestException:
        return None, None, None, {}, False


def fetch_playwright(url: str, config: FetchConfig, stealth: bool = False) -> tuple[str | None, str | None]:
    """
    Fetch URL using Playwright (headless browser).

    Args:
        url: URL to fetch
        config: Fetch configuration
        stealth: Whether to use playwright-stealth for anti-bot evasion

    Returns:
        Tuple of (html, final_url) or (None, None) on failure
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=config.headless)

            context_args = {
                'user_agent': get_user_agent(config),
            }

            context = browser.new_context(**context_args)

            # Load cookies if configured
            if config.cookie_ref:
                cookies = load_cookies(config.cookie_ref, cookies_dir=config.cookies_dir)
                if cookies:
                    try:
                        context.add_cookies(cookies)
                    except Exception:
                        pass

            # Apply stealth if requested
            if stealth:
                try:
                    from playwright_stealth import Stealth
                    page = context.new_page()
                    Stealth().apply_stealth_sync(page)
                except ImportError:
                    page = context.new_page()
            else:
                page = context.new_page()

            try:
                page.goto(
                    url,
                    wait_until=config.js_wait_until,
                    timeout=config.js_render_timeout_ms,
                )

                import time
                import random

                # Check for Cloudflare/bot challenge pages and wait
                html = page.content()
                challenge_indicators = [
                    'checking your browser',
                    'checking the site connection security',
                    'just a moment',
                    'please wait',
                    'ddos protection',
                    'cf-browser-verification',
                    'access denied',
                    '403 forbidden',
                    'rate limit',
                ]
                block_indicators = [
                    'access denied',
                    '403 forbidden',
                    'rate limit',
                    'too many requests',
                    'blocked',
                ]
                html_lower = html.lower()

                # Handle challenge pages (wait for JS to complete)
                if any(ind in html_lower for ind in challenge_indicators):
                    # Wait for challenge to complete (up to 30 seconds with polling)
                    for attempt in range(30):
                        time.sleep(1)
                        html = page.content()
                        html_lower = html.lower()
                        if not any(ind in html_lower for ind in challenge_indicators):
                            break

                # If still blocked, do exponential backoff retry
                if any(ind in html_lower for ind in block_indicators):
                    for retry in range(3):
                        backoff = (2 ** retry) * 10 + random.uniform(0, 5)  # 10-15s, 20-25s, 40-45s
                        time.sleep(backoff)
                        page.reload(wait_until=config.js_wait_until, timeout=config.js_render_timeout_ms)
                        html = page.content()
                        html_lower = html.lower()
                        if not any(ind in html_lower for ind in block_indicators):
                            break

                final_url = page.url
                return html, final_url

            except Exception:
                return None, None

            finally:
                page.close()
                context.close()
                browser.close()

    except Exception:
        return None, None


def fetch_html(
    url: str,
    config: FetchConfig | None = None,
    conditional_headers: dict | None = None,
) -> tuple[str | None, str | None, Literal['requests', 'playwright', 'playwright_stealth'], int | None, dict, bool]:
    """
    Fetch HTML with fallback chain.

    Tries: requests → playwright → playwright+stealth

    Args:
        url: URL to fetch
        config: Fetch configuration

    Returns:
        Tuple of (html, final_url, method) or (None, None, 'requests') on failure
    """
    if config is None:
        config = FetchConfig()

    # Skip non-HTML resources
    if should_skip_url(url):
        return None, None, 'requests'

    # Strategy 1: Plain requests (unless js_always is set)
    if not config.js_always:
        html, final_url, status, resp_headers, not_modified = fetch_requests(
            url, config, conditional_headers=conditional_headers
        )
        if not_modified:
            return None, final_url, 'requests', status, resp_headers, True
        if html:
            return html, final_url, 'requests', status, resp_headers, False

    # Strategy 2: Playwright (if enabled)
    if config.js_always or config.js_fallback:
        html, final_url = fetch_playwright(url, config, stealth=False)
        if html:
            return html, final_url, 'playwright', None, {}, False

    # Strategy 3: Playwright + stealth (if enabled)
    if config.stealth_fallback:
        html, final_url = fetch_playwright(url, config, stealth=True)
        if html:
            return html, final_url, 'playwright_stealth', None, {}, False

    return None, None, 'requests', None, {}, False
