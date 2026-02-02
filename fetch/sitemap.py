"""
Sitemap discovery and parsing for comprehensive URL discovery.

Supports:
- Standard sitemap.xml
- Sitemap index files (nested sitemaps)
- Common alternate locations
- Extraction of lastmod, changefreq, priority

Usage:
    from fetch.sitemap import discover_sitemap, parse_sitemap

    sitemap_url = discover_sitemap("https://example.com")
    if sitemap_url:
        urls = parse_sitemap(sitemap_url)
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator
from urllib.parse import urljoin, urlparse

import requests


# Common sitemap locations to try
SITEMAP_PATHS = [
    '/sitemap.xml',
    '/sitemap_index.xml',
    '/sitemaps/sitemap.xml',
    '/sitemap/sitemap.xml',
    '/wp-sitemap.xml',  # WordPress
    '/sitemap-index.xml',
    '/sitemap1.xml',
]

# XML namespaces
SITEMAP_NS = {
    'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9',
    'xhtml': 'http://www.w3.org/1999/xhtml',
}

REQUEST_TIMEOUT = 10
USER_AGENT = "TruckingCorpusBot/1.0 (Research)"


@dataclass
class SitemapURL:
    """A URL entry from a sitemap."""
    loc: str
    lastmod: str | None = None
    changefreq: str | None = None
    priority: float | None = None
    source_sitemap: str = ''


@dataclass
class SitemapResult:
    """Result of sitemap discovery and parsing."""
    found: bool = False
    sitemap_url: str = ''
    is_index: bool = False
    urls: list[SitemapURL] = field(default_factory=list)
    child_sitemaps: list[str] = field(default_factory=list)
    error: str | None = None
    fetch_time: str = ''


def _get(url: str) -> tuple[str | None, int]:
    """Fetch URL, return (content, status_code)."""
    try:
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={'User-Agent': USER_AGENT},
            allow_redirects=True,
        )
        if resp.status_code == 200:
            return resp.text, resp.status_code
        return None, resp.status_code
    except requests.RequestException:
        return None, 0


def discover_sitemap(base_url: str, robots_hints: list[str] | None = None) -> str | None:
    """
    Discover sitemap URL for a domain.

    Args:
        base_url: Base URL (e.g., "https://example.com")
        robots_hints: Sitemap URLs found in robots.txt (checked first)

    Returns:
        Sitemap URL if found, None otherwise
    """
    # Normalize base URL
    parsed = urlparse(base_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Try robots.txt hints first (most reliable)
    if robots_hints:
        for hint in robots_hints:
            content, status = _get(hint)
            if content and _looks_like_sitemap(content):
                return hint

    # Try common paths
    for path in SITEMAP_PATHS:
        url = urljoin(base, path)
        content, status = _get(url)
        if content and _looks_like_sitemap(content):
            return url

    return None


def _looks_like_sitemap(content: str) -> bool:
    """Quick check if content looks like a sitemap XML."""
    content_start = content[:500].lower()
    return (
        '<?xml' in content_start
        and ('urlset' in content_start or 'sitemapindex' in content_start)
    )


def _parse_datetime(date_str: str | None) -> str | None:
    """Parse various date formats to ISO string."""
    if not date_str:
        return None

    # Try common formats
    formats = [
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S.%f%z',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d',
    ]

    # Handle timezone suffix like +00:00
    date_str = date_str.strip()

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.isoformat()
        except ValueError:
            continue

    # Return as-is if can't parse
    return date_str


def parse_sitemap(
    sitemap_url: str,
    follow_index: bool = True,
    max_urls: int = 10000,
) -> SitemapResult:
    """
    Parse a sitemap and extract URLs.

    Args:
        sitemap_url: URL of the sitemap
        follow_index: If True, recursively fetch child sitemaps
        max_urls: Maximum URLs to return (prevents memory issues)

    Returns:
        SitemapResult with URLs and metadata
    """
    result = SitemapResult(
        fetch_time=datetime.utcnow().isoformat(),
        sitemap_url=sitemap_url,
    )

    content, status = _get(sitemap_url)
    if not content:
        result.error = f"Failed to fetch sitemap (status {status})"
        return result

    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        result.error = f"XML parse error: {e}"
        return result

    result.found = True

    # Check if this is a sitemap index
    if root.tag.endswith('sitemapindex') or 'sitemapindex' in root.tag:
        result.is_index = True
        result.child_sitemaps = _parse_sitemap_index(root)

        # Recursively fetch child sitemaps
        if follow_index:
            for child_url in result.child_sitemaps:
                if len(result.urls) >= max_urls:
                    break
                child_result = parse_sitemap(
                    child_url,
                    follow_index=False,  # Don't recurse further
                    max_urls=max_urls - len(result.urls),
                )
                result.urls.extend(child_result.urls)
    else:
        # Regular sitemap with URLs
        result.urls = list(_parse_urlset(root, sitemap_url, max_urls))

    return result


def _parse_sitemap_index(root: ET.Element) -> list[str]:
    """Parse sitemap index and return child sitemap URLs."""
    child_urls = []

    # Try with namespace
    for sitemap in root.findall('sm:sitemap', SITEMAP_NS):
        loc = sitemap.find('sm:loc', SITEMAP_NS)
        if loc is not None and loc.text:
            child_urls.append(loc.text.strip())

    # Try without namespace (some sitemaps don't use it)
    if not child_urls:
        for sitemap in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap'):
            loc = sitemap.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
            if loc is not None and loc.text:
                child_urls.append(loc.text.strip())

    # Try bare tags (no namespace)
    if not child_urls:
        for sitemap in root.findall('.//sitemap'):
            loc = sitemap.find('loc')
            if loc is not None and loc.text:
                child_urls.append(loc.text.strip())

    return child_urls


def _parse_urlset(
    root: ET.Element,
    source_sitemap: str,
    max_urls: int,
) -> Iterator[SitemapURL]:
    """Parse urlset and yield SitemapURL objects."""
    count = 0

    # Try with namespace
    urls = root.findall('sm:url', SITEMAP_NS)
    if not urls:
        urls = root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}url')
    if not urls:
        urls = root.findall('.//url')

    for url_elem in urls:
        if count >= max_urls:
            break

        # Extract loc (required)
        loc = None
        for tag in ['sm:loc', '{http://www.sitemaps.org/schemas/sitemap/0.9}loc', 'loc']:
            loc_elem = url_elem.find(tag, SITEMAP_NS) if ':' in tag else url_elem.find(tag)
            if loc_elem is not None and loc_elem.text:
                loc = loc_elem.text.strip()
                break

        if not loc:
            continue

        # Extract optional fields
        lastmod = _get_text(url_elem, ['sm:lastmod', '{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod', 'lastmod'])
        changefreq = _get_text(url_elem, ['sm:changefreq', '{http://www.sitemaps.org/schemas/sitemap/0.9}changefreq', 'changefreq'])
        priority_str = _get_text(url_elem, ['sm:priority', '{http://www.sitemaps.org/schemas/sitemap/0.9}priority', 'priority'])

        priority = None
        if priority_str:
            try:
                priority = float(priority_str)
            except ValueError:
                pass

        yield SitemapURL(
            loc=loc,
            lastmod=_parse_datetime(lastmod),
            changefreq=changefreq,
            priority=priority,
            source_sitemap=source_sitemap,
        )
        count += 1


def _get_text(elem: ET.Element, tags: list[str]) -> str | None:
    """Get text from first matching child tag."""
    for tag in tags:
        if ':' in tag and not tag.startswith('{'):
            child = elem.find(tag, SITEMAP_NS)
        else:
            child = elem.find(tag)
        if child is not None and child.text:
            return child.text.strip()
    return None


def sitemap_to_dict(result: SitemapResult) -> dict:
    """Convert SitemapResult to JSON-serializable dict."""
    return {
        'found': result.found,
        'sitemap_url': result.sitemap_url,
        'is_index': result.is_index,
        'url_count': len(result.urls),
        'child_sitemaps': result.child_sitemaps,
        'error': result.error,
        'fetch_time': result.fetch_time,
        'urls': [
            {
                'loc': u.loc,
                'lastmod': u.lastmod,
                'changefreq': u.changefreq,
                'priority': u.priority,
            }
            for u in result.urls[:100]  # Limit for JSON output
        ],
    }
