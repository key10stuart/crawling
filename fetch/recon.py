"""
Lightweight pre-crawl reconnaissance with caching.

Includes:
- recon_site(): HTTP probe, CDN/WAF detection, JS requirements
- probe_homepage(): Extract nav structure, tech stack, login detection
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, urljoin
import threading

import requests
from bs4 import BeautifulSoup

from .config import DEFAULT_HEADERS, USER_AGENTS
from .js_detect import detect_js_required


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_PATH = PROJECT_ROOT / "corpus" / "access" / "recon_cache.json"
_CACHE_LOCK = threading.Lock()


@dataclass
class ReconResult:
    domain: str
    url: str
    status_code: int | None
    headers: dict
    cdn: str | None
    waf: str | None
    challenge_detected: bool
    js_required: bool
    js_confidence: str | None
    js_signals: list[str]
    framework: str | None
    notes: list[str]
    fetched_at: str


@dataclass
class HomepageProbe:
    """Result of homepage structural analysis."""
    url: str

    # Navigation structure
    nav_links: list[str] = field(default_factory=list)  # Primary nav URLs
    nav_labels: dict = field(default_factory=dict)      # URL -> link text

    # Tech stack signals
    tech_stack: list[str] = field(default_factory=list)  # Detected technologies
    meta_generator: str | None = None                    # <meta name="generator">

    # Page patterns
    has_login: bool = False
    has_search: bool = False
    has_cookie_banner: bool = False
    has_lazy_images: bool = False
    has_infinite_scroll: bool = False

    # Content signals
    main_content_selector: str | None = None  # Best guess at main content area
    estimated_nav_depth: int = 0              # Max path segments in nav links

    # Raw counts
    total_links: int = 0
    internal_links: int = 0
    external_links: int = 0


_CHALLENGE_MARKERS = [
    'checking your browser',
    'checking the site connection security',
    'just a moment',
    'please wait',
    'ddos protection',
    'cf-browser-verification',
    'access denied',
    'captcha',
    'sg-captcha',
]


def _detect_cdn(headers: dict) -> tuple[str | None, str | None]:
    lower = {k.lower(): v for k, v in headers.items()}
    server = lower.get("server", "").lower()

    if 'cf-ray' in lower or 'cf-cache-status' in lower:
        return "cloudflare", "cloudflare"
    if 'sg-captcha' in lower:
        return "stackpath", "stackpath"
    if 'x-akamai' in lower or 'akamai' in server:
        return "akamai", "akamai"
    if 'x-fastly' in lower or 'fastly' in server:
        return "fastly", "fastly"
    if 'x-cdn' in lower:
        return lower.get('x-cdn'), None
    return None, None


def _detect_challenge(html: str | None) -> bool:
    if not html:
        return False
    html_lower = html.lower()
    return any(marker in html_lower for marker in _CHALLENGE_MARKERS)


def _cache_key(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    return domain.replace("www.", "")


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def recon_site(url: str, cache_path: Path | None = None, ttl_days: int = 7) -> ReconResult:
    cache_path = cache_path or DEFAULT_CACHE_PATH
    key = _cache_key(url)
    now = datetime.now(timezone.utc)

    with _CACHE_LOCK:
        cache = _load_cache(cache_path)
        cached = cache.get(key)
        if cached:
            try:
                fetched_at = datetime.fromisoformat(cached.get("fetched_at"))
                if now - fetched_at < timedelta(days=ttl_days):
                    return ReconResult(**cached)
            except Exception:
                pass

    headers = DEFAULT_HEADERS.copy()
    headers["User-Agent"] = USER_AGENTS[0]

    status_code = None
    html = None
    resp_headers = {}
    notes = []

    try:
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        status_code = resp.status_code
        resp_headers = dict(resp.headers)
        if resp.text and len(resp.text) < 2_000_000:
            html = resp.text
    except Exception as exc:
        notes.append(f"recon_error:{type(exc).__name__}")

    cdn, waf = _detect_cdn(resp_headers)
    challenge = _detect_challenge(html)

    js_required = False
    js_confidence = None
    js_signals = []
    framework = None
    if html:
        js_result = detect_js_required(html)
        js_required = js_result.js_required
        js_confidence = js_result.confidence
        js_signals = js_result.signals
        framework = js_result.framework

    result = ReconResult(
        domain=_cache_key(url),
        url=url,
        status_code=status_code,
        headers={k.lower(): v for k, v in resp_headers.items()},
        cdn=cdn,
        waf=waf,
        challenge_detected=challenge,
        js_required=js_required,
        js_confidence=js_confidence,
        js_signals=js_signals,
        framework=framework,
        notes=notes,
        fetched_at=now.isoformat(),
    )

    with _CACHE_LOCK:
        cache = _load_cache(cache_path)
        cache[key] = asdict(result)
        _save_cache(cache_path, cache)
    return result


# ---------------------------------------------------------------------------
# Homepage Probe - structural analysis of landing page
# ---------------------------------------------------------------------------

# Tech detection patterns
_TECH_PATTERNS = {
    'react': [r'react', r'_react', r'__NEXT_DATA__', r'data-reactroot'],
    'vue': [r'vue', r'__vue__', r'data-v-[a-f0-9]'],
    'angular': [r'ng-version', r'ng-app', r'angular', r'<app-root'],
    'next.js': [r'__NEXT_DATA__', r'_next/static'],
    'nuxt': [r'__NUXT__', r'_nuxt/'],
    'wordpress': [r'wp-content', r'wp-includes', r'wordpress'],
    'drupal': [r'drupal', r'/sites/default/'],
    'shopify': [r'shopify', r'cdn.shopify'],
    'squarespace': [r'squarespace', r'static1.squarespace'],
    'wix': [r'wix.com', r'parastorage.com'],
    'hubspot': [r'hubspot', r'hs-scripts', r'hbspt'],
    'gtm': [r'googletagmanager', r'gtm.js'],
    'ga4': [r'gtag', r'google-analytics', r'analytics.js'],
    'hotjar': [r'hotjar', r'static.hotjar.com'],
    'aem': [r'/etc.clientlibs/', r'/content/dam/', r'aem'],
    'sitecore': [r'sitecore', r'/sitecore/'],
}

_COOKIE_BANNER_PATTERNS = [
    r'cookie-consent', r'cookie-banner', r'cookie-notice', r'cookie-policy',
    r'gdpr', r'cc-window', r'cc-banner', r'onetrust', r'cookiebot',
    r'privacy-banner', r'consent-banner', r'accept-cookies',
]

_LOGIN_PATTERNS = [
    r'/login', r'/signin', r'/sign-in', r'/auth', r'/account',
    r'/portal', r'/my-account', r'/customer',
]


def probe_homepage(html: str, url: str) -> HomepageProbe:
    """
    Analyze homepage HTML for structural patterns.

    Use this during PROFILE phase to understand site structure
    before full capture begins.

    Args:
        html: Homepage HTML content
        url: Homepage URL (for resolving relative links)

    Returns:
        HomepageProbe with nav structure, tech stack, and patterns
    """
    result = HomepageProbe(url=url)
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.replace('www.', '')

    soup = BeautifulSoup(html, 'lxml')
    html_lower = html.lower()

    # --- Tech stack detection ---
    detected_tech = []
    for tech, patterns in _TECH_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, html_lower):
                detected_tech.append(tech)
                break
    result.tech_stack = detected_tech

    # Meta generator tag
    gen_tag = soup.find('meta', attrs={'name': 'generator'})
    if gen_tag:
        result.meta_generator = gen_tag.get('content', '')[:100]

    # --- Navigation extraction ---
    nav_links = []
    nav_labels = {}

    # Look for nav elements first
    nav_elements = soup.find_all(['nav', 'header'])
    if not nav_elements:
        nav_elements = [soup]  # Fall back to whole page

    for nav in nav_elements:
        for a in nav.find_all('a', href=True):
            href = a['href']

            # Skip anchors, javascript, mailto, tel
            if href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue

            # Resolve relative URLs
            full_url = urljoin(url, href)
            link_parsed = urlparse(full_url)

            # Only internal links
            link_domain = link_parsed.netloc.replace('www.', '')
            if link_domain != domain:
                continue

            # Normalize path
            path = link_parsed.path.rstrip('/') or '/'

            # Skip if already seen
            if path in nav_links:
                continue

            # Get link text
            text = a.get_text(strip=True)[:50]
            if text:
                nav_links.append(path)
                nav_labels[path] = text

    result.nav_links = nav_links[:50]  # Limit
    result.nav_labels = {k: nav_labels[k] for k in nav_links[:50] if k in nav_labels}

    # Estimate nav depth
    if nav_links:
        depths = [p.count('/') for p in nav_links if p != '/']
        result.estimated_nav_depth = max(depths) if depths else 0

    # --- Link counts ---
    all_links = soup.find_all('a', href=True)
    result.total_links = len(all_links)

    internal = 0
    external = 0
    for a in all_links:
        href = a['href']
        if href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
            continue
        full = urljoin(url, href)
        if domain in urlparse(full).netloc:
            internal += 1
        else:
            external += 1
    result.internal_links = internal
    result.external_links = external

    # --- Login detection ---
    # Check for login links
    for pattern in _LOGIN_PATTERNS:
        if re.search(pattern, html_lower):
            result.has_login = True
            break

    # Check for password fields
    if soup.find('input', attrs={'type': 'password'}):
        result.has_login = True

    # --- Search detection ---
    if soup.find('input', attrs={'type': 'search'}):
        result.has_search = True
    if soup.find('form', attrs={'role': 'search'}):
        result.has_search = True
    if re.search(r'/search|search-results|q=', html_lower):
        result.has_search = True

    # --- Cookie banner detection ---
    for pattern in _COOKIE_BANNER_PATTERNS:
        if re.search(pattern, html_lower):
            result.has_cookie_banner = True
            break

    # --- Lazy loading detection ---
    if soup.find('img', attrs={'loading': 'lazy'}):
        result.has_lazy_images = True
    if soup.find(attrs={'data-src': True}):
        result.has_lazy_images = True
    if re.search(r'lazyload|lazy-load', html_lower):
        result.has_lazy_images = True

    # --- Infinite scroll detection ---
    if re.search(r'infinite.?scroll|load.?more|pagination', html_lower):
        result.has_infinite_scroll = True

    # --- Main content selector guess ---
    for selector in ['main', 'article', '[role="main"]', '#content', '.content', '#main']:
        if soup.select_one(selector):
            result.main_content_selector = selector
            break

    return result
