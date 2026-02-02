"""
Configuration and thresholds for fetch module.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# File extensions to skip
SKIP_EXTENSIONS = (
    '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp',
    '.css', '.js', '.woff', '.woff2', '.ttf', '.ico',
    '.mp4', '.mp3', '.avi', '.mov', '.zip', '.tar', '.gz',
)

# Default request headers
DEFAULT_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}


@dataclass
class FetchConfig:
    """Configuration for fetch operations."""

    # Fetch layer settings
    timeout: float = 15.0
    request_delay: float = 0.0  # delay between requests (for batch crawling)
    js_fallback: bool = True  # try playwright if requests yields low content
    js_always: bool = False  # use playwright for every request
    stealth_fallback: bool = False  # try stealth if blocked (requires playwright-stealth)
    js_render_timeout_ms: int = 20000
    js_wait_until: str = "networkidle"
    headless: bool = True  # False = visible browser (bypasses some bot detection)

    # Extract layer settings
    extract_fallback: bool = True  # try readability/density if trafilatura fails
    favor_recall: bool = True  # prefer more content over precision
    include_tables: bool = True
    include_comments: bool = False  # page comments, not HTML comments

    # Asset extraction
    extract_images: bool = False
    extract_code: bool = False
    include_decorative_images: bool = False
    include_inline_code: bool = False
    include_config_code: bool = False
    min_code_block_chars: int = 20

    # Quality thresholds
    min_words: int = 50  # below this, try next strategy
    max_link_density: float = 0.4  # above this, likely nav/boilerplate
    min_text_density: float = 5.0  # chars per tag
    confidence_high_words: int = 200  # above this + good metrics = high
    confidence_low_words: int = 100  # below this = low confidence

    # Archival
    archive_html: bool = True  # save raw HTML
    archive_dir: Path | None = None  # directory for raw HTML files
    return_html: bool = False  # include raw HTML in FetchResult (for link discovery)

    # User agent
    user_agent: str | None = None  # if None, rotates from USER_AGENTS
    rotate_user_agent: bool = True

    # Cookies
    cookie_ref: str | None = None  # domain or file path for cookie load
    cookies_dir: Path | None = None  # optional override for cookie directory


@dataclass
class FetchResult:
    """Result of a fetch operation."""

    # Identity
    url: str
    final_url: str
    content_hash: str

    # Temporal
    fetch_time: str  # ISO 8601 UTC
    publish_date: str | None = None

    # Provenance
    fetch_method: Literal['requests', 'playwright', 'playwright_stealth', 'cache'] = 'requests'
    extract_method: Literal['trafilatura', 'readability', 'density', 'none'] = 'trafilatura'
    confidence: Literal['high', 'medium', 'low'] = 'medium'

    # Content
    title: str = ''
    author: str | None = None
    text: str = ''
    word_count: int = 0
    images: list = field(default_factory=list)
    code_blocks: list = field(default_factory=list)

    # Archival
    raw_html_path: str | None = None
    raw_html_hash: str | None = None
    raw_html: str | None = None

    # Error tracking
    error: str | None = None
    interaction_log: list = field(default_factory=list)

    # Response metadata
    status_code: int | None = None
    response_headers: dict = field(default_factory=dict)
    not_modified: bool = False
