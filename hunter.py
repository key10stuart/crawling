#!/usr/bin/env python3
"""
Hunter - Aggressive content extraction for jbhunt.com

Usage:
    python hunter.py                    # Full site crawl
    python hunter.py --quick            # Sitemap URLs only, no link discovery
    python hunter.py --section shippers # Crawl specific section
    python hunter.py --resume           # Resume from checkpoint

Philosophy: Extract EVERYTHING now, parse later.
"""

import argparse
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
from typing import Optional
import requests

# =============================================================================
# CONFIG
# =============================================================================

DOMAIN = "jbhunt.com"
BASE_URL = "https://www.jbhunt.com"
SITEMAP_URL = "https://www.jbhunt.com/sitemap.xml"

# Directories
PROJECT_ROOT = Path(__file__).parent
CORPUS_DIR = PROJECT_ROOT / "corpus"
RAW_DIR = CORPUS_DIR / "raw" / "jbhunt.com"
HUNTER_DIR = CORPUS_DIR / "hunter"
CHECKPOINT_FILE = HUNTER_DIR / "checkpoint.json"

# Crawl settings
DEFAULT_DEPTH = 3
REQUEST_DELAY = 2.0  # Be polite
REQUEST_TIMEOUT = 30
JS_TIMEOUT_MS = 45000  # Longer timeout for JS-heavy pages
USER_AGENT = "HunterBot/1.0 (Research; thorough extraction)"

# Content thresholds
MIN_WORDS_BEFORE_JS_RETRY = 50
MIN_WORDS_BEFORE_SCROLL_RETRY = 100

# Skip patterns
SKIP_EXTENSIONS = (
    '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp',
    '.css', '.js', '.woff', '.woff2', '.ttf', '.ico', '.mp4', '.mp3',
    '.zip', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'
)
SKIP_PATTERNS = [
    r'/login', r'/logout', r'/auth', r'/oauth',
    r'\?.*redirect', r'/search\?',
]


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class CrawlResult:
    url: str
    final_url: str
    status: str  # success, error, skipped
    html: Optional[str] = None
    word_count: int = 0
    content_hash: Optional[str] = None
    fetch_method: str = "http"  # http, js, js+scroll, js+interact
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class CrawlState:
    """Checkpoint state for resume capability."""
    visited: set = field(default_factory=set)
    queue: list = field(default_factory=list)
    results: list = field(default_factory=list)
    sitemap_urls: list = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def save(self, path: Path):
        data = {
            'visited': list(self.visited),
            'queue': self.queue,
            'results': [asdict(r) for r in self.results],
            'sitemap_urls': self.sitemap_urls,
            'started_at': self.started_at,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: Path) -> 'CrawlState':
        with open(path) as f:
            data = json.load(f)
        state = cls()
        state.visited = set(data['visited'])
        state.queue = data['queue']
        state.results = [CrawlResult(**r) for r in data['results']]
        state.sitemap_urls = data['sitemap_urls']
        state.started_at = data['started_at']
        return state


# =============================================================================
# URL UTILITIES
# =============================================================================

def canonicalize_url(url: str) -> str:
    """Normalize URL for deduplication."""
    parsed = urlparse(url)

    # Lowercase scheme and host, strip www
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower().replace('www.', '')

    # Normalize path
    path = parsed.path.rstrip('/') or '/'

    # Sort query params, remove tracking params
    strip_params = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_content',
                    'utm_term', 'fbclid', 'gclid', 'ref', 'source', '_ga'}
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        params = {k: v for k, v in params.items() if k.lower() not in strip_params}
        query = urlencode(sorted(params.items()), doseq=True)
    else:
        query = ''

    return f"{scheme}://{host}{path}{'?' + query if query else ''}"


def should_skip_url(url: str) -> bool:
    """Check if URL should be skipped."""
    lower = url.lower()

    # Skip non-HTML resources
    if any(lower.endswith(ext) for ext in SKIP_EXTENSIONS):
        return True

    # Skip auth/login pages
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, lower):
            return True

    return False


def is_internal_url(url: str, domain: str = DOMAIN) -> bool:
    """Check if URL belongs to the target domain."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace('www.', '')
    return domain in host


def content_hash(html: str) -> str:
    """Hash content for dedup."""
    normalized = ' '.join(html.split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def url_to_filename(url: str) -> str:
    """Convert URL to safe filename."""
    parsed = urlparse(url)
    path = parsed.path.strip('/').replace('/', '_') or 'index'
    if parsed.query:
        path += '_' + hashlib.md5(parsed.query.encode()).hexdigest()[:8]
    return path[:200] + '.html'


# =============================================================================
# SITEMAP PARSING
# =============================================================================

def fetch_sitemap(url: str = SITEMAP_URL) -> list[str]:
    """Fetch and parse sitemap.xml, return list of URLs."""
    print(f"Fetching sitemap: {url}")

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={'User-Agent': USER_AGENT})
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Error fetching sitemap: {e}")
        return []

    urls = []

    try:
        root = ET.fromstring(resp.content)
        # Handle namespace
        ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

        # Check if this is a sitemap index
        sitemap_refs = root.findall('.//sm:sitemap/sm:loc', ns)
        if sitemap_refs:
            print(f"  Found sitemap index with {len(sitemap_refs)} sub-sitemaps")
            for ref in sitemap_refs:
                sub_urls = fetch_sitemap(ref.text)
                urls.extend(sub_urls)
        else:
            # Regular sitemap
            for loc in root.findall('.//sm:url/sm:loc', ns):
                if loc.text:
                    urls.append(loc.text)

            # Try without namespace (some sitemaps don't use it)
            if not urls:
                for loc in root.findall('.//loc'):
                    if loc.text:
                        urls.append(loc.text)

    except ET.ParseError as e:
        print(f"  Error parsing sitemap XML: {e}")
        return []

    print(f"  Found {len(urls)} URLs in sitemap")
    return urls


# =============================================================================
# HTTP FETCHER
# =============================================================================

def get_session() -> requests.Session:
    """Create HTTP session."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    })
    return session


def fetch_http(session: requests.Session, url: str) -> tuple[str | None, str | None, str | None]:
    """Fetch via HTTP. Returns (html, final_url, error)."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get('Content-Type', '').lower()
        if 'text/html' not in content_type and 'application/xhtml' not in content_type:
            return None, resp.url, f"Non-HTML content-type: {content_type[:50]}"

        return resp.text, resp.url, None

    except requests.RequestException as e:
        return None, None, str(e)


# =============================================================================
# PLAYWRIGHT FETCHER (JS Rendering)
# =============================================================================

class JSFetcher:
    """Playwright-based fetcher for JS-heavy pages."""

    def __init__(self, timeout_ms: int = JS_TIMEOUT_MS):
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent=USER_AGENT,
            viewport={'width': 1920, 'height': 1080},
        )
        return self

    def __exit__(self, *args):
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def fetch(self, url: str, scroll: bool = False, interact: bool = False) -> tuple[str | None, str | None, str | None]:
        """
        Fetch page with JS rendering.

        Args:
            scroll: Scroll to bottom to trigger lazy loading
            interact: Click through tabs/carousels

        Returns: (html, final_url, error)
        """
        page = self._context.new_page()

        try:
            # Navigate
            page.goto(url, wait_until='networkidle', timeout=self.timeout_ms)

            # Scroll to trigger lazy loading
            if scroll:
                self._scroll_page(page)

            # Interact with dynamic elements
            if interact:
                self._interact_with_page(page)

            html = page.content()
            final_url = page.url

            return html, final_url, None

        except Exception as e:
            return None, None, f"JS error: {type(e).__name__}: {str(e)[:100]}"

        finally:
            page.close()

    def _scroll_page(self, page):
        """Scroll to bottom incrementally to trigger lazy loading."""
        try:
            # Get page height
            prev_height = 0
            for _ in range(10):  # Max 10 scroll iterations
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(500)

                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == prev_height:
                    break
                prev_height = new_height

            # Scroll back to top
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(300)

        except Exception:
            pass  # Scroll errors are non-fatal

    def _interact_with_page(self, page):
        """Click through tabs, carousels, accordions to reveal hidden content."""

        # Common tab/carousel selectors
        tab_selectors = [
            '[role="tab"]',
            '.tab',
            '.nav-tab',
            '[data-toggle="tab"]',
            '.carousel-control-next',
            '.slick-next',
            '.swiper-button-next',
            'button[aria-label*="next"]',
            'button[aria-label*="Next"]',
        ]

        # Accordion/expander selectors
        accordion_selectors = [
            '[data-toggle="collapse"]',
            '.accordion-button',
            'details summary',
            '[aria-expanded="false"]',
        ]

        clicked = 0

        # Click tabs
        for selector in tab_selectors:
            try:
                elements = page.query_selector_all(selector)
                for el in elements[:10]:  # Limit clicks per selector
                    try:
                        el.click()
                        page.wait_for_timeout(300)
                        clicked += 1
                    except Exception:
                        pass
            except Exception:
                pass

        # Expand accordions
        for selector in accordion_selectors:
            try:
                elements = page.query_selector_all(selector)
                for el in elements[:20]:
                    try:
                        el.click()
                        page.wait_for_timeout(200)
                        clicked += 1
                    except Exception:
                        pass
            except Exception:
                pass

        if clicked > 0:
            # Wait for any animations to settle
            page.wait_for_timeout(500)


# =============================================================================
# LINK EXTRACTION
# =============================================================================

def extract_links(html: str, base_url: str) -> set[str]:
    """Extract all internal links from HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'lxml')
    links = set()

    for a in soup.find_all('a', href=True):
        href = a['href']

        # Skip non-http links
        if href.startswith(('#', 'javascript:', 'mailto:', 'tel:', 'data:')):
            continue

        # Resolve relative URLs
        full_url = urljoin(base_url, href)

        # Only keep internal links
        if is_internal_url(full_url):
            clean = canonicalize_url(full_url)
            if not should_skip_url(clean):
                links.add(clean)

    return links


def count_words(html: str) -> int:
    """Quick word count from HTML."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'lxml')

    # Remove script/style
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()

    text = soup.get_text(separator=' ', strip=True)
    return len(text.split())


# =============================================================================
# MAIN CRAWLER
# =============================================================================

def crawl_url(
    url: str,
    session: requests.Session,
    js_fetcher: Optional[JSFetcher] = None,
) -> CrawlResult:
    """
    Crawl a single URL with escalating fetch strategies.

    Strategy:
    1. Try HTTP first
    2. If low content, retry with JS
    3. If still low, retry with JS + scroll
    4. If still low, retry with JS + scroll + interact
    """

    if should_skip_url(url):
        return CrawlResult(url=url, final_url=url, status='skipped', error='Matches skip pattern')

    # Strategy 1: Plain HTTP
    html, final_url, error = fetch_http(session, url)

    if error:
        # If HTTP failed and we have JS, try that
        if js_fetcher:
            html, final_url, error = js_fetcher.fetch(url)
            if html:
                return CrawlResult(
                    url=url,
                    final_url=final_url,
                    status='success',
                    html=html,
                    word_count=count_words(html),
                    content_hash=content_hash(html),
                    fetch_method='js',
                )

        return CrawlResult(url=url, final_url=final_url or url, status='error', error=error)

    word_count = count_words(html)

    # Strategy 2: If low content, try JS
    if word_count < MIN_WORDS_BEFORE_JS_RETRY and js_fetcher:
        js_html, js_final_url, js_error = js_fetcher.fetch(url)
        if js_html:
            js_word_count = count_words(js_html)
            if js_word_count > word_count:
                html = js_html
                final_url = js_final_url
                word_count = js_word_count
                fetch_method = 'js'
            else:
                fetch_method = 'http'
        else:
            fetch_method = 'http'
    else:
        fetch_method = 'http'

    # Strategy 3: If still low, try JS + scroll
    if word_count < MIN_WORDS_BEFORE_SCROLL_RETRY and js_fetcher:
        scroll_html, scroll_final_url, scroll_error = js_fetcher.fetch(url, scroll=True)
        if scroll_html:
            scroll_word_count = count_words(scroll_html)
            if scroll_word_count > word_count:
                html = scroll_html
                final_url = scroll_final_url
                word_count = scroll_word_count
                fetch_method = 'js+scroll'

    # Strategy 4: If still low, try JS + scroll + interact
    if word_count < MIN_WORDS_BEFORE_SCROLL_RETRY and js_fetcher:
        interact_html, interact_final_url, interact_error = js_fetcher.fetch(url, scroll=True, interact=True)
        if interact_html:
            interact_word_count = count_words(interact_html)
            if interact_word_count > word_count:
                html = interact_html
                final_url = interact_final_url
                word_count = interact_word_count
                fetch_method = 'js+scroll+interact'

    return CrawlResult(
        url=url,
        final_url=final_url,
        status='success',
        html=html,
        word_count=word_count,
        content_hash=content_hash(html),
        fetch_method=fetch_method,
    )


def save_result(result: CrawlResult, raw_dir: Path = RAW_DIR):
    """Save crawl result to disk."""
    if result.status != 'success' or not result.html:
        return

    raw_dir.mkdir(parents=True, exist_ok=True)
    filename = url_to_filename(result.url)
    filepath = raw_dir / filename
    filepath.write_text(result.html)


def hunt(
    max_depth: int = DEFAULT_DEPTH,
    use_sitemap: bool = True,
    discover_links: bool = True,
    section: Optional[str] = None,
    resume: bool = False,
    checkpoint_interval: int = 10,
):
    """
    Main hunt function - thorough crawl of jbhunt.com

    Args:
        max_depth: Maximum crawl depth from seeds
        use_sitemap: Seed from sitemap.xml
        discover_links: Follow discovered links (BFS)
        section: Only crawl URLs matching this path prefix (e.g., 'shippers')
        resume: Resume from checkpoint
        checkpoint_interval: Save checkpoint every N pages
    """

    print("=" * 60)
    print("HUNTER - Aggressive JB Hunt Extraction")
    print("=" * 60)

    # Initialize or resume state
    if resume and CHECKPOINT_FILE.exists():
        print(f"Resuming from checkpoint: {CHECKPOINT_FILE}")
        state = CrawlState.load(CHECKPOINT_FILE)
        print(f"  Visited: {len(state.visited)}, Queue: {len(state.queue)}")
    else:
        state = CrawlState()

        # Seed from sitemap
        if use_sitemap:
            state.sitemap_urls = fetch_sitemap()
            print(f"Sitemap URLs: {len(state.sitemap_urls)}")

        # Build initial queue
        seeds = state.sitemap_urls if state.sitemap_urls else [BASE_URL]

        # Filter by section if specified
        if section:
            section_path = f"/{section.strip('/')}"
            seeds = [u for u in seeds if section_path in urlparse(u).path]
            print(f"Filtered to section '{section}': {len(seeds)} URLs")

        # Add seeds to queue with depth 0
        for url in seeds:
            canonical = canonicalize_url(url)
            if canonical not in state.visited:
                state.queue.append((canonical, 0))

    # Setup fetchers
    session = get_session()

    print(f"\nStarting crawl...")
    print(f"  Max depth: {max_depth}")
    print(f"  Link discovery: {discover_links}")
    print(f"  Initial queue: {len(state.queue)}")
    print()

    # Ensure output dirs exist
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    HUNTER_DIR.mkdir(parents=True, exist_ok=True)

    crawled_count = 0
    start_time = time.time()

    with JSFetcher() as js_fetcher:
        while state.queue:
            url, depth = state.queue.pop(0)

            # Skip if already visited
            canonical = canonicalize_url(url)
            if canonical in state.visited:
                continue

            state.visited.add(canonical)

            # Crawl
            print(f"[{crawled_count + 1}] (d={depth}) {urlparse(url).path or '/'}", end=' ')

            result = crawl_url(url, session, js_fetcher)
            state.results.append(result)

            if result.status == 'success':
                print(f"→ {result.word_count} words [{result.fetch_method}]")
                save_result(result)

                # Discover new links
                if discover_links and depth < max_depth and result.html:
                    new_links = extract_links(result.html, result.final_url)
                    added = 0
                    for link in new_links:
                        link_canonical = canonicalize_url(link)
                        if link_canonical not in state.visited:
                            # Filter by section if specified
                            if section:
                                section_path = f"/{section.strip('/')}"
                                if section_path not in urlparse(link).path:
                                    continue
                            state.queue.append((link_canonical, depth + 1))
                            added += 1
                    if added > 0:
                        print(f"       +{added} new URLs queued")

            elif result.status == 'skipped':
                print(f"→ SKIP: {result.error}")
            else:
                print(f"→ ERROR: {result.error}")

            crawled_count += 1

            # Checkpoint
            if crawled_count % checkpoint_interval == 0:
                state.save(CHECKPOINT_FILE)
                print(f"  [checkpoint saved]")

            # Polite delay
            time.sleep(REQUEST_DELAY)

    # Final save
    state.save(CHECKPOINT_FILE)

    # Summary
    elapsed = time.time() - start_time
    success_count = sum(1 for r in state.results if r.status == 'success')
    total_words = sum(r.word_count for r in state.results if r.status == 'success')

    print()
    print("=" * 60)
    print("HUNT COMPLETE")
    print("=" * 60)
    print(f"  Pages crawled: {crawled_count}")
    print(f"  Successful: {success_count}")
    print(f"  Total words: {total_words:,}")
    print(f"  Time: {elapsed:.1f}s ({elapsed/max(crawled_count,1):.1f}s/page)")
    print(f"  Raw HTML: {RAW_DIR}")
    print(f"  Checkpoint: {CHECKPOINT_FILE}")

    # Fetch method breakdown
    methods = {}
    for r in state.results:
        if r.status == 'success':
            methods[r.fetch_method] = methods.get(r.fetch_method, 0) + 1

    print(f"\n  Fetch methods:")
    for method, count in sorted(methods.items(), key=lambda x: -x[1]):
        print(f"    {method}: {count}")

    # Save summary
    summary = {
        'domain': DOMAIN,
        'crawled_at': datetime.now().isoformat(),
        'pages_crawled': crawled_count,
        'pages_successful': success_count,
        'total_words': total_words,
        'elapsed_seconds': elapsed,
        'fetch_methods': methods,
        'sitemap_urls': len(state.sitemap_urls),
        'results': [
            {
                'url': r.url,
                'status': r.status,
                'word_count': r.word_count,
                'fetch_method': r.fetch_method,
                'error': r.error,
            }
            for r in state.results
        ]
    }

    summary_file = HUNTER_DIR / 'summary.json'
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"  Summary: {summary_file}")


# =============================================================================
# TEST MODE
# =============================================================================

def test_homepage():
    """
    Quick test: fetch homepage with all strategies and compare results.
    Shows whether JS/scroll/interact capture more content.
    """
    print("=" * 60)
    print("HUNTER TEST - Homepage Extraction Comparison")
    print("=" * 60)
    print(f"URL: {BASE_URL}\n")

    session = get_session()
    results = []

    # Strategy 1: Plain HTTP
    print("[1] HTTP only...", end=' ', flush=True)
    html, final_url, error = fetch_http(session, BASE_URL)
    if html:
        words = count_words(html)
        print(f"{words} words")
        results.append(('HTTP', words, html))
    else:
        print(f"ERROR: {error}")
        results.append(('HTTP', 0, None))

    # Strategy 2-4: JS variants
    with JSFetcher() as js:
        # JS only
        print("[2] JS render...", end=' ', flush=True)
        html, final_url, error = js.fetch(BASE_URL, scroll=False, interact=False)
        if html:
            words = count_words(html)
            print(f"{words} words")
            results.append(('JS', words, html))
        else:
            print(f"ERROR: {error}")
            results.append(('JS', 0, None))

        # JS + scroll
        print("[3] JS + scroll...", end=' ', flush=True)
        html, final_url, error = js.fetch(BASE_URL, scroll=True, interact=False)
        if html:
            words = count_words(html)
            print(f"{words} words")
            results.append(('JS+scroll', words, html))
        else:
            print(f"ERROR: {error}")
            results.append(('JS+scroll', 0, None))

        # JS + scroll + interact
        print("[4] JS + scroll + interact...", end=' ', flush=True)
        html, final_url, error = js.fetch(BASE_URL, scroll=True, interact=True)
        if html:
            words = count_words(html)
            print(f"{words} words")
            results.append(('JS+scroll+interact', words, html))
        else:
            print(f"ERROR: {error}")
            results.append(('JS+scroll+interact', 0, None))

    # Summary
    print()
    print("-" * 40)
    print("RESULTS:")
    print("-" * 40)

    best_method, best_words, best_html = max(results, key=lambda x: x[1])

    for method, words, html in results:
        marker = " <-- BEST" if method == best_method else ""
        bar = "█" * (words // 20)
        print(f"  {method:20} {words:5} words {bar}{marker}")

    # Show improvement
    http_words = results[0][1]
    if best_words > http_words:
        improvement = ((best_words - http_words) / max(http_words, 1)) * 100
        print(f"\nImprovement: +{best_words - http_words} words (+{improvement:.0f}%) with {best_method}")
    else:
        print(f"\nNo improvement over HTTP")

    # Save best result for inspection
    if best_html:
        test_file = HUNTER_DIR / 'test_homepage.html'
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(best_html)
        print(f"\nBest HTML saved: {test_file}")

        # Also show a snippet of extracted text
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(best_html, 'lxml')
        for tag in soup(['script', 'style', 'noscript', 'nav', 'footer']):
            tag.decompose()
        text = soup.get_text(separator=' ', strip=True)[:500]
        print(f"\nContent preview:\n{'-'*40}\n{text}...")

    print()
    return best_words > http_words


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Hunter - Aggressive JB Hunt content extraction',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python hunter.py -t                  # Quick test on homepage
    python hunter.py                     # Full crawl with sitemap + link discovery
    python hunter.py --quick             # Sitemap URLs only, no link following
    python hunter.py --section shippers  # Only /shippers/* pages
    python hunter.py --section blog      # Only /blog/* pages
    python hunter.py --depth 5           # Deeper crawl
    python hunter.py --resume            # Resume interrupted crawl
        """
    )

    parser.add_argument('-t', '--test', action='store_true',
                        help='Quick test: compare fetch strategies on homepage')
    parser.add_argument('--depth', type=int, default=DEFAULT_DEPTH,
                        help=f'Max crawl depth (default: {DEFAULT_DEPTH})')
    parser.add_argument('--quick', action='store_true',
                        help='Sitemap URLs only, no link discovery')
    parser.add_argument('--section', type=str,
                        help='Only crawl URLs matching this path prefix')
    parser.add_argument('--no-sitemap', action='store_true',
                        help='Skip sitemap, start from homepage')
    parser.add_argument('--resume', action='store_true',
                        help='Resume from checkpoint')
    parser.add_argument('--checkpoint-interval', type=int, default=10,
                        help='Save checkpoint every N pages (default: 10)')

    args = parser.parse_args()

    # Test mode
    if args.test:
        test_homepage()
        return

    hunt(
        max_depth=args.depth,
        use_sitemap=not args.no_sitemap,
        discover_links=not args.quick,
        section=args.section,
        resume=args.resume,
        checkpoint_interval=args.checkpoint_interval,
    )


if __name__ == '__main__':
    main()
