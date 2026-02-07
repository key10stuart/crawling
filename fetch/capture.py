"""
Page capture for Div 4i.

Captures complete page state:
- Full rendered HTML (with lazy content expanded)
- Screenshot (optional)
- Asset inventory (URLs + metadata, no downloads)
- Manifest of captured content
"""

import hashlib
import json
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .capture_config import (
    AssetRef,
    CaptureConfig,
    CaptureManifest,
    CaptureResult,
    CaptureTimingInfo,
    PageManifestEntry,
)
from .cookies import load_cookies
from .lazy_expander import expand_all


# Asset detection patterns
DOCUMENT_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.txt', '.rtf', '.csv', '.zip', '.rar', '.7z',
}

VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.m4v'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.m4a', '.flac'}


def hash_content(content: str) -> str:
    """Generate SHA256 hash of content."""
    return hashlib.sha256(content.encode('utf-8', errors='replace')).hexdigest()[:16]


def url_to_filename(url: str, extension: str = '.html') -> str:
    """Convert URL path to safe filename."""
    parsed = urlparse(url)
    path = parsed.path.strip('/')

    if not path or path == '':
        path = 'index'

    # Replace path separators with underscores
    filename = path.replace('/', '_').replace('\\', '_')

    # Remove or replace unsafe characters
    filename = re.sub(r'[<>:"|?*]', '', filename)
    filename = re.sub(r'\.html?$', '', filename, flags=re.I)

    # Truncate if too long
    if len(filename) > 200:
        filename = filename[:200]

    return filename + extension


def parse_image_dimensions(tag) -> tuple[int, int] | None:
    """Extract image dimensions from tag attributes."""
    width = tag.get('width')
    height = tag.get('height')

    if width and height:
        try:
            w = int(re.sub(r'[^\d]', '', str(width)))
            h = int(re.sub(r'[^\d]', '', str(height)))
            if w > 0 and h > 0:
                return (w, h)
        except (ValueError, TypeError):
            pass

    return None


def inventory_assets(html: str, base_url: str) -> list[AssetRef]:
    """
    Parse HTML and inventory all assets (without downloading).

    Finds:
    - Images (<img>, <picture>, background-image)
    - Documents (links to PDFs, DOCs, etc.)
    - Videos (<video>, <source>)
    - Audio (<audio>)

    Returns list of AssetRef with URLs and metadata.
    """
    soup = BeautifulSoup(html, 'lxml')
    assets = []
    seen_urls = set()

    def add_asset(url: str, asset_type: str, **kwargs):
        """Add asset if not already seen."""
        if not url or url.startswith('data:'):
            return

        # Resolve relative URL
        full_url = urljoin(base_url, url)

        if full_url in seen_urls:
            return
        seen_urls.add(full_url)

        assets.append(AssetRef(
            url=full_url,
            asset_type=asset_type,
            **kwargs
        ))

    # Images: <img> tags
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or img.get('data-lazy')
        if src:
            add_asset(
                url=src,
                asset_type='image',
                alt_text=img.get('alt'),
                dimensions=parse_image_dimensions(img),
                srcset=img.get('srcset'),
            )

    # Images: <picture> sources
    for picture in soup.find_all('picture'):
        for source in picture.find_all('source'):
            srcset = source.get('srcset')
            if srcset:
                # Take first URL from srcset
                first_src = srcset.split(',')[0].split()[0]
                add_asset(url=first_src, asset_type='image')

    # Videos: <video> and <source>
    for video in soup.find_all('video'):
        src = video.get('src')
        poster = video.get('poster')

        if src:
            add_asset(url=src, asset_type='video', poster=poster)

        for source in video.find_all('source'):
            src = source.get('src')
            if src:
                add_asset(url=src, asset_type='video', poster=poster)

    # Audio: <audio> and <source>
    for audio in soup.find_all('audio'):
        src = audio.get('src')
        if src:
            add_asset(url=src, asset_type='audio')

        for source in audio.find_all('source'):
            src = source.get('src')
            if src:
                add_asset(url=src, asset_type='audio')

    # Documents: links to PDFs, DOCs, etc.
    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        parsed = urlparse(href)
        ext = Path(parsed.path).suffix.lower()

        if ext in DOCUMENT_EXTENSIONS:
            link_text = a.get_text(strip=True)
            add_asset(
                url=href,
                asset_type='document',
                link_text=link_text if link_text else None,
            )

    # Videos: links to video files
    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        parsed = urlparse(href)
        ext = Path(parsed.path).suffix.lower()

        if ext in VIDEO_EXTENSIONS:
            link_text = a.get_text(strip=True)
            add_asset(
                url=href,
                asset_type='video',
                link_text=link_text if link_text else None,
            )

    return assets


def take_screenshot(page, output_path: Path, config: CaptureConfig) -> bool:
    """
    Take screenshot of page.

    Args:
        page: Playwright page object
        output_path: Path to save screenshot
        config: Capture configuration

    Returns:
        True if successful
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        screenshot_opts = {
            'path': str(output_path),
            'full_page': config.screenshot_full_page,
        }

        if config.screenshot_format == 'jpeg':
            screenshot_opts['type'] = 'jpeg'
            screenshot_opts['quality'] = config.screenshot_quality

        page.screenshot(**screenshot_opts)
        return True

    except Exception:
        return False


def capture_page_playwright(
    url: str,
    config: CaptureConfig,
    archive_dir: Path,
) -> CaptureResult:
    """
    Capture page using Playwright (for JS-heavy sites).

    Handles:
    - Page load and rendering
    - Lazy content expansion
    - Screenshot capture
    - HTML extraction

    Args:
        url: URL to capture
        config: Capture configuration
        archive_dir: Directory to save captured files

    Returns:
        CaptureResult
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return CaptureResult(
            url=url,
            final_url=url,
            html_path=None,
            screenshot_path=None,
            asset_inventory=[],
            manifest_path=None,
            content_hash='',
            captured_at=datetime.now(timezone.utc).isoformat(),
            fetch_method='playwright',
            timing=None,
            headers={},
            cookies=[],
            html_size_bytes=0,
            error='playwright_not_installed',
        )

    timing = CaptureTimingInfo()
    timing.fetch_start_ms = time.time() * 1000

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=config.headless)

            context_args = {
                'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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

            # Apply stealth if configured
            if config.stealth:
                try:
                    from playwright_stealth import Stealth
                    page = context.new_page()
                    Stealth().apply_stealth_sync(page)
                except ImportError:
                    page = context.new_page()
            else:
                page = context.new_page()

            # Navigate
            try:
                page.goto(url, wait_until='networkidle', timeout=config.timeout_ms)
            except Exception:
                # Try with just domcontentloaded if networkidle times out
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=config.timeout_ms)
                except Exception as e:
                    return CaptureResult(
                        url=url,
                        final_url=url,
                        html_path=None,
                        screenshot_path=None,
                        asset_inventory=[],
                        manifest_path=None,
                        content_hash='',
                        captured_at=datetime.now(timezone.utc).isoformat(),
                        fetch_method='playwright',
                        timing=None,
                        headers={},
                        cookies=[],
                        html_size_bytes=0,
                        error=f'navigation_failed: {type(e).__name__}',
                    )

            timing.fetch_end_ms = time.time() * 1000
            final_url = page.url

            # Expand lazy content
            timing.expansion_start_ms = time.time() * 1000
            expansion = expand_all(page, config)
            timing.expansion_end_ms = time.time() * 1000

            # Get final HTML state
            html = page.content()
            content_hash = hash_content(html)
            html_size = len(html.encode('utf-8', errors='replace'))

            # Setup archive paths
            domain = urlparse(final_url).netloc.replace('www.', '')
            pages_dir = archive_dir / domain / 'pages'
            pages_dir.mkdir(parents=True, exist_ok=True)

            # Save HTML
            html_filename = url_to_filename(final_url, '.html')
            html_path = pages_dir / html_filename
            html_path.write_text(html, encoding='utf-8')

            # Screenshot
            screenshot_path = None
            if config.take_screenshot:
                screenshots_dir = archive_dir / domain / 'screenshots'
                screenshots_dir.mkdir(parents=True, exist_ok=True)
                ss_filename = url_to_filename(final_url, f'.{config.screenshot_format}')
                ss_path = screenshots_dir / ss_filename

                timing_ss_start = time.time() * 1000
                if take_screenshot(page, ss_path, config):
                    screenshot_path = ss_path
                timing.screenshot_ms = time.time() * 1000 - timing_ss_start

            # Get cookies and headers
            page_cookies = context.cookies()
            headers = {}  # Would need to intercept response for headers

            # Inventory assets
            assets = inventory_assets(html, final_url)

            timing.total_ms = time.time() * 1000 - timing.fetch_start_ms

            # Clean up
            page.close()
            context.close()
            browser.close()

            return CaptureResult(
                url=url,
                final_url=final_url,
                html_path=html_path,
                screenshot_path=screenshot_path,
                asset_inventory=assets,
                manifest_path=archive_dir / domain / 'manifest.json',
                content_hash=content_hash,
                captured_at=datetime.now(timezone.utc).isoformat(),
                fetch_method='playwright' if not config.stealth else 'stealth',
                timing=timing,
                headers=headers,
                cookies=page_cookies,
                html_size_bytes=html_size,
                error=None,
                interaction_log=expansion.get("interaction_log", []),
                expansion_stats=expansion.get("stats", {}),
            )

    except Exception as e:
        return CaptureResult(
            url=url,
            final_url=url,
            html_path=None,
            screenshot_path=None,
            asset_inventory=[],
            manifest_path=None,
            content_hash='',
            captured_at=datetime.now(timezone.utc).isoformat(),
            fetch_method='playwright',
            timing=None,
            headers={},
            cookies=[],
            html_size_bytes=0,
            error=f'capture_error: {type(e).__name__}: {str(e)[:100]}',
        )


def capture_page_requests(
    url: str,
    config: CaptureConfig,
    archive_dir: Path,
) -> CaptureResult:
    """
    Capture page using requests (for simple static sites).

    No JS rendering, no screenshots - just HTML capture.

    Args:
        url: URL to capture
        config: Capture configuration
        archive_dir: Directory to save captured files

    Returns:
        CaptureResult
    """
    import requests

    timing = CaptureTimingInfo()
    timing.fetch_start_ms = time.time() * 1000

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    try:
        resp = requests.get(url, headers=headers, timeout=config.timeout_ms / 1000, allow_redirects=True)

        timing.fetch_end_ms = time.time() * 1000

        # Stash status code in headers for classifier access
        # (until CaptureResult gets a formal http_status field from Stream A)
        resp_headers = dict(resp.headers)
        resp_headers["_http_status"] = str(resp.status_code)

        # Non-success HTTP statuses: still capture body for classification
        # but record the status in error field for downstream awareness
        http_error = None
        if resp.status_code >= 400:
            http_error = f"http_{resp.status_code}"

        # Check content type
        content_type = resp.headers.get('Content-Type', '').lower()
        if 'text/html' not in content_type and 'application/xhtml' not in content_type:
            return CaptureResult(
                url=url,
                final_url=resp.url,
                html_path=None,
                screenshot_path=None,
                asset_inventory=[],
                manifest_path=None,
                content_hash='',
                captured_at=datetime.now(timezone.utc).isoformat(),
                fetch_method='requests',
                timing=timing,
                headers=resp_headers,
                cookies=[],
                html_size_bytes=0,
                error=http_error or f'not_html: {content_type}',
            )

        html = resp.text
        content_hash = hash_content(html)
        html_size = len(html.encode('utf-8', errors='replace'))
        final_url = resp.url

        # Setup archive paths
        domain = urlparse(final_url).netloc.replace('www.', '')
        pages_dir = archive_dir / domain / 'pages'
        pages_dir.mkdir(parents=True, exist_ok=True)

        # Save HTML — even for error pages, for classifier inspection
        html_filename = url_to_filename(final_url, '.html')
        html_path = pages_dir / html_filename
        html_path.write_text(html, encoding='utf-8')

        # Inventory assets
        assets = inventory_assets(html, final_url)

        timing.total_ms = time.time() * 1000 - timing.fetch_start_ms

        return CaptureResult(
            url=url,
            final_url=final_url,
            html_path=html_path,
            screenshot_path=None,  # No screenshots with requests
            asset_inventory=assets,
            manifest_path=archive_dir / domain / 'manifest.json',
            content_hash=content_hash,
            captured_at=datetime.now(timezone.utc).isoformat(),
            fetch_method='requests',
            timing=timing,
            headers=resp_headers,
            cookies=[{'name': c.name, 'value': c.value, 'domain': c.domain} for c in resp.cookies],
            html_size_bytes=html_size,
            error=http_error,
        )

    except requests.RequestException as e:
        # Extract status code from HTTPError if available
        status_code = None
        if hasattr(e, 'response') and e.response is not None:
            status_code = e.response.status_code
        error_headers = {}
        if status_code:
            error_headers["_http_status"] = str(status_code)
        return CaptureResult(
            url=url,
            final_url=url,
            html_path=None,
            screenshot_path=None,
            asset_inventory=[],
            manifest_path=None,
            content_hash='',
            captured_at=datetime.now(timezone.utc).isoformat(),
            fetch_method='requests',
            timing=timing,
            headers=error_headers,
            cookies=[],
            html_size_bytes=0,
            error=f'request_error: {type(e).__name__}' + (f' http_{status_code}' if status_code else ''),
        )


def capture_page(
    url: str,
    config: CaptureConfig,
    archive_dir: Path,
) -> CaptureResult:
    """
    Capture a complete page.

    Chooses between requests (simple) and playwright (JS-heavy)
    based on config.

    Args:
        url: URL to capture
        config: Capture configuration
        archive_dir: Directory to save captured files

    Returns:
        CaptureResult with HTML path, screenshot, assets, etc.
    """
    if config.js_required or config.stealth:
        return capture_page_playwright(url, config, archive_dir)
    else:
        # Try requests first
        result = capture_page_requests(url, config, archive_dir)

        # Fall back to playwright if requests fails or gets blocked
        # (unless no_js_fallback is set)
        if not config.no_js_fallback and (result.error or result.html_size_bytes < 1000):
            config_js = CaptureConfig(
                js_required=True,
                stealth=config.stealth,
                headless=config.headless,
                timeout_ms=config.timeout_ms,
                expand_lazy_content=config.expand_lazy_content,
                scroll_to_bottom=config.scroll_to_bottom,
                click_accordions=config.click_accordions,
                take_screenshot=config.take_screenshot,
                cookie_ref=config.cookie_ref,
                cookies_dir=config.cookies_dir,
            )
            return capture_page_playwright(url, config_js, archive_dir)

        return result


def write_manifest(
    domain: str,
    archive_dir: Path,
    captures: list[CaptureResult],
    site_profile: dict | None = None,
) -> Path:
    """
    Write capture manifest for a domain.

    Args:
        domain: Domain name
        archive_dir: Archive directory
        captures: List of capture results

    Returns:
        Path to manifest file
    """
    manifest_root = archive_dir / domain

    def manifest_rel(path: Path | None) -> str:
        """Return a stable manifest path for same-domain and redirected captures."""
        if not path:
            return ""
        try:
            return str(path.relative_to(manifest_root))
        except ValueError:
            try:
                return str(path.relative_to(archive_dir))
            except ValueError:
                return str(path)

    # Aggregate all assets across pages
    all_assets: dict[str, AssetRef] = {}
    for capture in captures:
        for asset in capture.asset_inventory:
            if asset.url not in all_assets:
                all_assets[asset.url] = asset
                all_assets[asset.url].found_on_pages = []

            # Track which pages reference this asset
            if capture.html_path:
                rel_path = manifest_rel(capture.html_path)
                if rel_path not in all_assets[asset.url].found_on_pages:
                    all_assets[asset.url].found_on_pages.append(rel_path)

    # Build manifest
    manifest = CaptureManifest(
        domain=domain,
        captured=datetime.now(timezone.utc).isoformat(),
        corpus_version=2,
        pages=[
            PageManifestEntry(
                url=c.url,
                final_url=c.final_url,
                html_path=manifest_rel(c.html_path),
                screenshot_path=manifest_rel(c.screenshot_path) if c.screenshot_path else None,
                captured_at=c.captured_at,
                fetch_method=c.fetch_method,
                content_hash=c.content_hash,
                html_size_bytes=c.html_size_bytes,
                interaction_log=c.interaction_log,
                expansion_stats=c.expansion_stats,
                final_access_outcome=asdict(c.access_outcome) if c.access_outcome else None,
                attempts=[asdict(a) for a in c.attempts],
            )
            for c in captures
            if c.html_path  # Only include successful captures
        ],
        assets=list(all_assets.values()),
        stats={
            'pages': len([c for c in captures if c.html_path]),
            'pages_failed': len([c for c in captures if c.error]),
            'images': len([a for a in all_assets.values() if a.asset_type == 'image']),
            'documents': len([a for a in all_assets.values() if a.asset_type == 'document']),
            'videos': len([a for a in all_assets.values() if a.asset_type == 'video']),
            'total_html_kb': sum(c.html_size_bytes for c in captures) // 1024,
        },
        site_profile=site_profile,
    )

    # Write manifest
    manifest_path = archive_dir / domain / 'manifest.json'
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to dict, handling dataclass fields
    def asdict_asset(a: AssetRef) -> dict:
        return {
            'url': a.url,
            'type': a.asset_type,
            'alt': a.alt_text,
            'link_text': a.link_text,
            'dimensions': list(a.dimensions) if a.dimensions else None,
            'srcset': a.srcset,
            'poster': a.poster,
            'found_on': a.found_on_pages,
        }

    manifest_dict = {
        'domain': manifest.domain,
        'captured': manifest.captured,
        'corpus_version': manifest.corpus_version,
        'pages': [asdict(p) for p in manifest.pages],
        'assets': [asdict_asset(a) for a in manifest.assets],
        'stats': manifest.stats,
        'site_profile': manifest.site_profile,
    }

    with open(manifest_path, 'w') as f:
        json.dump(manifest_dict, f, indent=2)

    return manifest_path
