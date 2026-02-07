"""
Capture configuration for Div 4i.

Defines settings for page capture: fetch method, lazy expansion,
screenshots, and asset inventory.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AccessOutcome:
    """Classification result for a single access attempt/page."""
    outcome: str
    reason: str
    http_status: int | None = None
    detected_markers: list[str] = field(default_factory=list)
    waf_hint: str | None = None
    challenge_detected: bool = False
    word_count_estimate: int = 0
    link_density_estimate: float | None = None
    final_url: str | None = None


@dataclass
class AccessAttempt:
    """Attempt telemetry for access strategy execution."""
    attempt_index: int
    strategy: str
    started_at: str
    duration_ms: int
    outcome: AccessOutcome
    capture_error: str | None = None
    html_size_bytes: int | None = None


@dataclass
class CaptureConfig:
    """Configuration for page capture."""

    # Fetch settings
    js_required: bool = False
    stealth: bool = False
    headless: bool = True
    timeout_ms: int = 30000
    no_js_fallback: bool = False  # If True, never fall back to Playwright

    # Expansion settings - wait as long as needed
    expand_lazy_content: bool = True
    scroll_to_bottom: bool = True
    scroll_pause_ms: int = 500       # Pause between scroll steps
    click_accordions: bool = True
    accordion_selectors: list[str] = field(default_factory=lambda: [
        '[data-toggle="collapse"]',
        '[aria-expanded="false"]',
        '.accordion-button:not(.collapsed)',
        '.expandable:not(.expanded)',
        'details:not([open]) summary',
        '[role="button"][aria-expanded="false"]',
    ])
    wait_after_expansion_ms: int = 2000  # Wait after all expansions

    # Screenshot settings
    take_screenshot: bool = True
    screenshot_full_page: bool = True
    screenshot_format: str = 'png'    # png or jpeg
    screenshot_quality: int = 80      # For jpeg

    # Cookie/auth
    cookie_ref: str | None = None
    cookies_dir: Path | None = None

    # Archive paths (set by capture_page)
    archive_dir: Path | None = None


@dataclass
class AssetRef:
    """Reference to an asset (URL + metadata, not downloaded)."""
    url: str
    asset_type: str                     # image, document, video, audio
    alt_text: str | None = None         # For images
    link_text: str | None = None        # For document links
    dimensions: tuple[int, int] | None = None  # (width, height)
    srcset: str | None = None           # For responsive images
    poster: str | None = None           # For videos
    found_in_selector: str | None = None  # CSS selector hint
    found_on_pages: list[str] = field(default_factory=list)


@dataclass
class CaptureTimingInfo:
    """Timing information for a capture."""
    fetch_start_ms: float = 0
    fetch_end_ms: float = 0
    expansion_start_ms: float = 0
    expansion_end_ms: float = 0
    screenshot_ms: float = 0
    total_ms: float = 0


@dataclass
class CaptureResult:
    """Result of capturing a page."""
    url: str
    final_url: str
    html_path: Path | None              # corpus/raw/{domain}/pages/{page}.html
    screenshot_path: Path | None        # corpus/raw/{domain}/screenshots/{page}.png
    asset_inventory: list[AssetRef]
    manifest_path: Path | None          # corpus/raw/{domain}/manifest.json
    content_hash: str
    captured_at: str                    # ISO timestamp
    fetch_method: str                   # requests, playwright, stealth
    timing: CaptureTimingInfo | None
    headers: dict
    cookies: list[dict]
    html_size_bytes: int
    error: str | None = None
    interaction_log: list[dict] = field(default_factory=list)
    expansion_stats: dict = field(default_factory=dict)
    access_outcome: AccessOutcome | None = None
    attempts: list[AccessAttempt] = field(default_factory=list)


@dataclass
class PageManifestEntry:
    """Entry for a single page in the capture manifest."""
    url: str
    final_url: str
    html_path: str                      # Relative to manifest
    screenshot_path: str | None
    captured_at: str
    fetch_method: str
    content_hash: str
    html_size_bytes: int
    interaction_log: list[dict] = field(default_factory=list)
    expansion_stats: dict = field(default_factory=dict)
    final_access_outcome: dict | None = None
    attempts: list[dict] = field(default_factory=list)


@dataclass
class CaptureManifest:
    """Manifest for a captured site."""
    domain: str
    captured: str                       # ISO timestamp of capture start
    corpus_version: int = 2
    pages: list[PageManifestEntry] = field(default_factory=list)
    assets: list[AssetRef] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    site_profile: dict | None = None
