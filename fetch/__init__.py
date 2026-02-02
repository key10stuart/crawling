"""
Unified fetch and extract module.

Primary interface:
    from fetch import fetch_source

    result = fetch_source("https://example.com/article")

    # Returns FetchResult with:
    # - url, final_url, content_hash
    # - fetch_time, publish_date
    # - fetch_method, extract_method, confidence
    # - title, author, text, word_count
    # - raw_html_path, raw_html_hash
"""

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .config import FetchConfig, FetchResult
from .fetcher import fetch_html, fetch_playwright
from .extractor import extract_content
from .quality import score_confidence
from .hasher import hash_content, hash_html
from .images import extract_images, ImageBlock
from .code import extract_code, CodeBlock
from .interactive import interactive_fetch


__all__ = [
    'fetch_source',
    'interactive_fetch',
    'FetchConfig',
    'FetchResult',
    'extract_images',
    'ImageBlock',
    'extract_code',
    'CodeBlock',
]


def fetch_source(
    url: str,
    config: FetchConfig | None = None,
    conditional_headers: dict | None = None,
    cached_html_path: str | None = None,
) -> FetchResult | None:
    """
    Fetch URL and extract content.

    This is the primary interface for the fetch module. It:
    1. Fetches HTML (requests → playwright → stealth fallback)
    2. Extracts content (trafilatura → readability → density fallback)
    3. Scores confidence
    4. Archives raw HTML if configured
    5. Returns structured result

    Args:
        url: URL to fetch
        config: Fetch configuration (uses defaults if None)

    Returns:
        FetchResult or None if fetch completely failed
    """
    if config is None:
        config = FetchConfig()

    fetch_time = datetime.now(timezone.utc).isoformat()

    # Fetch HTML
    html, final_url, fetch_method, status_code, response_headers, not_modified = fetch_html(
        url, config, conditional_headers=conditional_headers
    )

    if not_modified:
        cached_html = None
        if cached_html_path:
            try:
                cached_html = Path(cached_html_path).read_text(encoding="utf-8")
            except Exception:
                cached_html = None
        if cached_html:
            html = cached_html
            fetch_method = 'cache'
        else:
            return FetchResult(
                url=url,
                final_url=final_url or url,
                content_hash='',
                fetch_time=fetch_time,
                fetch_method=fetch_method,
                extract_method='none',
                confidence='low',
                error='not_modified_no_cache',
                status_code=status_code,
                response_headers=response_headers,
                not_modified=True,
            )

    if html is None:
        return FetchResult(
            url=url,
            final_url=url,
            content_hash='',
            fetch_time=fetch_time,
            fetch_method=fetch_method,
            extract_method='none',
            confidence='low',
            error='fetch_failed',
            status_code=status_code,
            response_headers=response_headers,
            not_modified=not_modified,
        )

    # Extract content
    extraction = extract_content(html, config)
    extracted_words = len(extraction.text.split()) if extraction.text else 0

    # Post-extract JS fallback for JS-heavy sites
    if (config.js_fallback
            and not config.js_always
            and fetch_method == 'requests'
            and extracted_words < config.min_words):
        js_html, js_final_url = fetch_playwright(url, config, stealth=False)
        js_method = 'playwright'
        if not js_html and config.stealth_fallback:
            js_html, js_final_url = fetch_playwright(url, config, stealth=True)
            js_method = 'playwright_stealth'

        if js_html:
            html = js_html
            final_url = js_final_url or final_url
            fetch_method = js_method
            extraction = extract_content(html, config)

    # Calculate hashes
    content_hash = hash_content(extraction.text) if extraction.text else ''
    raw_html_hash = hash_html(html)

    # Score confidence
    confidence = score_confidence(
        extraction.text,
        extraction.method,
        extraction.link_density,
        config,
    )

    # Archive raw HTML if configured
    raw_html_path = None
    if config.archive_html and config.archive_dir:
        if fetch_method == 'cache' and cached_html_path:
            raw_html_path = cached_html_path
        else:
            raw_html_path = archive_html(html, final_url, config.archive_dir)

    # Optional asset extraction
    images = []
    code_blocks = []
    if config.extract_images:
        images = extract_images(html, final_url or url, include_decorative=config.include_decorative_images)
    if config.extract_code:
        code_blocks = extract_code(
            html,
            include_inline=config.include_inline_code,
            include_config=config.include_config_code,
            min_block_chars=config.min_code_block_chars,
        )

    return FetchResult(
        url=url,
        final_url=final_url or url,
        content_hash=content_hash,
        fetch_time=fetch_time,
        publish_date=extraction.date,
        fetch_method=fetch_method,
        extract_method=extraction.method,
        confidence=confidence,
        title=extraction.title,
        author=extraction.author,
        text=extraction.text,
        word_count=len(extraction.text.split()) if extraction.text else 0,
        images=images,
        code_blocks=code_blocks,
        raw_html_path=raw_html_path,
        raw_html_hash=raw_html_hash,
        raw_html=html if config.return_html else None,
        status_code=status_code,
        response_headers=response_headers,
        not_modified=not_modified,
    )


def archive_html(html: str, url: str, archive_dir: Path) -> str | None:
    """
    Archive raw HTML to file.

    Args:
        html: Raw HTML content
        url: Source URL (used for filename)
        archive_dir: Directory to save files

    Returns:
        Path to saved file, or None on failure
    """
    try:
        archive_dir = Path(archive_dir)
        archive_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename from URL path
        parsed = urlparse(url)
        path = parsed.path.replace('/', '_').strip('_') or 'index'

        # Truncate if too long
        if len(path) > 100:
            path = path[:100]

        filename = f"{path}.html"
        filepath = archive_dir / filename

        # Handle collisions
        counter = 1
        while filepath.exists():
            filepath = archive_dir / f"{path}_{counter}.html"
            counter += 1

        filepath.write_text(html, encoding='utf-8')
        return str(filepath)

    except Exception:
        return None
