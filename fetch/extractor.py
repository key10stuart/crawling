"""
Content extraction layer with fallback chain:
trafilatura → readability-lxml → density scorer
"""

import re
from dataclasses import dataclass, asdict
from typing import Literal

from bs4 import BeautifulSoup, Comment

from .config import FetchConfig
from .quality import check_quality
from .fullpage import extract_full_page, extraction_to_dict
from .structured import extract_jsonld
from .hasher import hash_content
from urllib.parse import urlparse, urljoin
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ExtractionResult:
    """Result of content extraction."""
    text: str
    title: str
    author: str | None
    date: str | None
    method: Literal['trafilatura', 'readability', 'density', 'none']
    link_density: float = 0.0


# Tags to strip for density scorer
STRIP_TAGS = [
    'script', 'style', 'nav', 'header', 'footer', 'aside',
    'noscript', 'iframe', 'form', 'svg', 'path', 'button',
    'input', 'select', 'textarea', 'label',
]

# Classes to strip for density scorer
STRIP_CLASSES = [
    'cookie', 'modal', 'popup', 'advertisement', 'ad-', 'ads-',
    'sidebar', 'widget', 'social', 'share', 'comment', 'related',
    'newsletter', 'subscribe', 'promo', 'banner',
]


def extract_trafilatura(html: str, config: FetchConfig) -> ExtractionResult | None:
    """
    Extract content using trafilatura (primary extractor).

    Args:
        html: Raw HTML content
        config: Fetch configuration

    Returns:
        ExtractionResult or None if extraction failed
    """
    try:
        import trafilatura
    except ImportError:
        return None

    try:
        # bare_extraction returns a Document object with attributes
        doc = trafilatura.bare_extraction(
            html,
            include_comments=config.include_comments,
            include_tables=config.include_tables,
            include_links=False,
            with_metadata=True,
            favor_recall=config.favor_recall,
        )

        if doc is None:
            return None

        # Access as attributes, not dict keys
        text = getattr(doc, 'text', '') or ''
        if not text:
            return None

        return ExtractionResult(
            text=text,
            title=getattr(doc, 'title', '') or '',
            author=getattr(doc, 'author', None),
            date=getattr(doc, 'date', None),
            method='trafilatura',
        )
    except Exception:
        return None


def extract_readability(html: str) -> ExtractionResult | None:
    """
    Extract content using readability-lxml (fallback extractor).

    Args:
        html: Raw HTML content

    Returns:
        ExtractionResult or None if extraction failed
    """
    try:
        from readability import Document
    except ImportError:
        return None

    try:
        doc = Document(html)
        title = doc.title()
        summary_html = doc.summary()

        # Convert summary HTML to plain text
        soup = BeautifulSoup(summary_html, 'lxml')
        text = soup.get_text(separator=' ', strip=True)

        if not text:
            return None

        return ExtractionResult(
            text=text,
            title=title,
            author=None,  # readability doesn't extract author
            date=None,  # readability doesn't extract date
            method='readability',
        )
    except Exception:
        return None


def extract_density(html: str) -> ExtractionResult | None:
    """
    Extract content using density scoring (final fallback).

    Strategy:
    1. Try <main> tag first if it has substantial content
    2. Otherwise, score containers by: text_density * (1 - link_density)
    3. If best candidate is small relative to body, use body with filtering

    Args:
        html: Raw HTML content

    Returns:
        ExtractionResult or None if extraction failed
    """
    try:
        soup = BeautifulSoup(html, 'lxml')
    except Exception:
        return None

    # Strip only truly non-content tags (keep nav, header, footer for now)
    for tag in STRIP_TAGS:
        for el in soup.find_all(tag):
            el.decompose()

    # Remove HTML comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Extract title
    title = ''
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Strategy 1: Check <main> tag first
    main = soup.find('main')
    if main:
        main_text = main.get_text(separator=' ', strip=True)
        main_words = len(main_text.split())
        if main_words >= 100:  # Substantial content in main
            links = main.find_all('a')
            link_text = sum(len(a.get_text(separator=' ', strip=True)) for a in links)
            link_density = link_text / (len(main_text) + 1)
            return ExtractionResult(
                text=main_text,
                title=title,
                author=None,
                date=None,
                method='density',
                link_density=link_density,
            )

    # Get body text for comparison
    body = soup.body
    body_text = body.get_text(separator=' ', strip=True) if body else ''
    body_words = len(body_text.split())

    # Strategy 2: Score candidate containers
    candidates = []
    for node in soup.find_all(['article', 'main', 'section', 'div']):
        text = node.get_text(separator=' ', strip=True)
        if not text or len(text) < 50:
            continue

        tags = len(node.find_all(True))
        links = node.find_all('a')
        link_text = sum(len(a.get_text(separator=' ', strip=True)) for a in links)

        text_len = len(text)
        text_density = text_len / (tags + 1)
        link_density = link_text / (text_len + 1)

        score = text_density * (1 - link_density)
        word_count = len(text.split())
        candidates.append((score, text, link_density, word_count))

    if candidates:
        # Get highest scoring candidate
        _, best_text, best_link_density, best_words = max(candidates, key=lambda x: x[0])

        # Strategy 3: If best candidate is small relative to body, use body
        # This catches homepages where content is spread across many small divs
        if body_words > 0 and best_words < body_words * 0.25:
            # Best candidate has less than 25% of body text - probably too aggressive
            # Strip high link-density elements and use remaining body
            for el in soup.find_all(['nav', 'header', 'footer']):
                el_text = el.get_text(separator=' ', strip=True)
                el_links = el.find_all('a')
                el_link_text = sum(len(a.get_text(separator=' ', strip=True)) for a in el_links)
                el_link_density = el_link_text / (len(el_text) + 1) if el_text else 1.0
                if el_link_density > 0.5:  # High link density = navigation, strip it
                    el.decompose()

            # Also strip known boilerplate classes
            for class_pattern in STRIP_CLASSES:
                for el in soup.find_all(class_=re.compile(class_pattern, re.I)):
                    el.decompose()

            body_text = soup.body.get_text(separator=' ', strip=True) if soup.body else ''
            if body_text:
                return ExtractionResult(
                    text=body_text,
                    title=title,
                    author=None,
                    date=None,
                    method='density',
                    link_density=0.3,  # estimated after filtering
                )

        return ExtractionResult(
            text=best_text,
            title=title,
            author=None,
            date=None,
            method='density',
            link_density=best_link_density,
        )

    # Final fallback: body text
    if body_text:
        return ExtractionResult(
            text=body_text,
            title=title,
            author=None,
            date=None,
            method='density',
            link_density=0.5,
        )

    return None


def extract_content(html: str, config: FetchConfig | None = None) -> ExtractionResult:
    """
    Extract content using fallback chain.

    Tries: trafilatura → readability → density scorer
    Returns best result that passes quality checks, or best attempt if none pass.

    Args:
        html: Raw HTML content
        config: Fetch configuration

    Returns:
        ExtractionResult (always returns something, even if low quality)
    """
    if config is None:
        config = FetchConfig()

    extractors = [
        ('trafilatura', lambda: extract_trafilatura(html, config)),
        ('readability', lambda: extract_readability(html)),
        ('density', lambda: extract_density(html)),
    ]

    best_result = None
    best_word_count = 0

    for name, extractor in extractors:
        result = extractor()

        if result is None:
            continue

        # Check quality
        passed, reason = check_quality(
            result.text,
            result.title,
            result.link_density,
            config,
        )

        if passed:
            return result

        # Track best attempt even if quality check failed
        word_count = len(result.text.split()) if result.text else 0
        if word_count > best_word_count:
            best_result = result
            best_word_count = word_count

        # If fallback disabled, stop here
        if not config.extract_fallback:
            break

    # Return best attempt or empty result
    if best_result:
        return best_result

    return ExtractionResult(
        text='',
        title='',
        author=None,
        date=None,
        method='none',
    )


# =============================================================================
# Capture-based extraction (Div 4i)
# =============================================================================

_DOCUMENT_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)


def _classify_block_type(el) -> str:
    """Classify an element by nearest semantic container."""
    if el is None:
        return "unknown"

    # Walk up parents looking for semantic containers
    for tag in el.parents:
        if not hasattr(tag, 'name'):
            continue

        # Check for hero/banner sections first (more specific)
        if tag.name in ("section", "article", "div"):
            class_list = tag.get("class", []) or []
            class_text = " ".join(class_list).lower()
            if "hero" in class_text or "banner" in class_text or "jumbotron" in class_text:
                return "hero"

        # Semantic HTML5 containers
        if tag.name == "nav":
            return "nav"
        if tag.name == "header":
            # Check if this is page header (contains nav) vs section header
            if tag.find("nav"):
                return "header"
            return "header"
        if tag.name == "footer":
            return "footer"
        if tag.name == "aside":
            return "sidebar"
        if tag.name == "main":
            return "main"

    return "main"


def _classify_image(alt_text: str | None, block_type: str, url: str | None) -> str:
    """Classify image by context: logo, hero_image, content_image, icon, decorative."""
    alt_lower = (alt_text or "").lower()
    url_lower = (url or "").lower()

    # Logo detection
    if "logo" in alt_lower or "logo" in url_lower:
        return "logo"

    # Hero images
    if block_type == "hero":
        return "hero_image"
    if "hero" in url_lower or "banner" in url_lower:
        return "hero_image"

    # Icons (small, usually in nav/buttons)
    if block_type in ("nav", "header") and not alt_text:
        return "icon"
    if "icon" in url_lower or "icons" in url_lower:
        return "icon"

    # Decorative (no alt text in main content)
    if block_type == "main" and not alt_text:
        return "decorative"

    # Default to content image
    return "content_image"


def _nearest_text(el: BeautifulSoup, limit: int = 200) -> str:
    """Get nearby text around an element."""
    if el is None:
        return ""
    parent = el.parent
    if not parent:
        return ""
    text = parent.get_text(separator=" ", strip=True)
    return text[:limit]


def _inventory_assets_from_html(html: str, base_url: str | None = None) -> list[dict]:
    """Lightweight asset inventory when capture metadata is absent."""
    assets = []
    soup = BeautifulSoup(html, "lxml")

    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if base_url and src:
            src = urljoin(base_url, src)
        assets.append({
            "url": src,
            "asset_type": "image",
            "alt_text": img.get("alt"),
            "link_text": None,
            "dimensions": (
                int(img.get("width")) if img.get("width") else None,
                int(img.get("height")) if img.get("height") else None,
            ),
            "srcset": img.get("srcset"),
        })

    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        if base_url and href:
            href = urljoin(base_url, href)
        if href.lower().endswith(_DOCUMENT_EXTENSIONS):
            assets.append({
                "url": href,
                "asset_type": "document",
                "alt_text": None,
                "link_text": a.get_text(strip=True),
                "dimensions": None,
                "srcset": None,
            })

    for video in soup.find_all("video"):
        src = video.get("src") or ""
        if base_url and src:
            src = urljoin(base_url, src)
        if src:
            assets.append({
                "url": src,
                "asset_type": "video",
                "alt_text": None,
                "link_text": None,
                "dimensions": None,
                "srcset": None,
            })

    return assets


def _enrich_assets_with_context(html: str, assets: list[dict]) -> list[dict]:
    """Add context fields to asset inventory."""
    soup = BeautifulSoup(html, "lxml")
    enriched = []

    for asset in assets:
        url = asset.get("url") or ""
        asset_type = asset.get("asset_type")
        el = None

        # Find element - try multiple matching strategies
        if asset_type == "image":
            # Try exact match first
            el = soup.find("img", src=url)
            # Try matching just the path portion
            if not el and url:
                url_path = urlparse(url).path
                for img in soup.find_all("img", src=True):
                    if img.get("src", "").endswith(url_path) or url_path.endswith(img.get("src", "")):
                        el = img
                        break
        elif asset_type == "document":
            el = soup.find("a", href=url)
            if not el and url:
                url_path = urlparse(url).path
                for a in soup.find_all("a", href=True):
                    if a.get("href", "").endswith(url_path) or url_path.endswith(a.get("href", "")):
                        el = a
                        break
        elif asset_type == "video":
            el = soup.find("video", src=url)

        block_type = _classify_block_type(el)
        context_text = _nearest_text(el)
        selector_hint = el.name if el else None

        asset_ctx = dict(asset)
        asset_ctx["block_type"] = block_type
        asset_ctx["context_text"] = context_text
        asset_ctx["context_selector"] = selector_hint

        # Add classification for images
        if asset_type == "image":
            asset_ctx["classification"] = _classify_image(
                asset.get("alt_text"),
                block_type,
                url,
            )

        enriched.append(asset_ctx)

    return enriched


def _categorize_links(html: str, base_url: str | None = None) -> dict:
    soup = BeautifulSoup(html, "lxml")
    nav_links = set()
    primary_nav, utility_nav = [], []
    try:
        from .fullpage import _extract_all_nav_links  # type: ignore
        primary_nav, utility_nav = _extract_all_nav_links(soup, base_url or "")
    except Exception:
        pass

    for link in (primary_nav + utility_nav):
        nav_links.add(link.url)

    categories = {"nav": [], "content": [], "external": [], "documents": []}
    base_domain = urlparse(base_url).netloc if base_url else ""

    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        if base_url:
            href = urljoin(base_url, href)
        text = a.get_text(strip=True)
        if href.lower().endswith(_DOCUMENT_EXTENSIONS):
            categories["documents"].append({"url": href, "text": text})
        elif href in nav_links:
            categories["nav"].append({"url": href, "text": text})
        else:
            if base_domain and urlparse(href).netloc and urlparse(href).netloc != base_domain:
                categories["external"].append({"url": href, "text": text})
            else:
                categories["content"].append({"url": href, "text": text})

    return categories


def extract_from_capture(
    html_path: str | Path,
    url: str | None = None,
    asset_inventory: list[dict] | None = None,
    screenshot_path: str | None = None,
    interaction_log: list[dict] | None = None,
    expansion_stats: dict | None = None,
    config: FetchConfig | None = None,
) -> dict:
    """
    Extract structured content from archived HTML capture.
    """
    html_path = Path(html_path)
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    base_url = url or ""
    config = config or FetchConfig()

    extraction = extract_content(html, config)
    fullpage = extract_full_page(html, base_url)
    tagged_blocks = extraction_to_dict(fullpage).get("tagged_blocks", [])
    trigger_actions = sorted({
        entry.get("action")
        for entry in (interaction_log or [])
        if entry.get("action")
    })
    if trigger_actions:
        for block in tagged_blocks:
            if isinstance(block, dict):
                block["trigger_actions"] = trigger_actions

    assets = asset_inventory or _inventory_assets_from_html(html, base_url)
    assets = _enrich_assets_with_context(html, assets)

    links = _categorize_links(html, base_url)
    structured = asdict(extract_jsonld(html)) if html else {}

    return {
        "url": url,
        "title": extraction.title or fullpage.title,
        "content_hash": hash_content(extraction.text) if extraction.text else "",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "main_content": {
            "text": extraction.text,
            "word_count": len(extraction.text.split()) if extraction.text else 0,
            "method": extraction.method,
        },
        "tagged_blocks": tagged_blocks,
        "assets": assets,
        "links": links,
        "structured_data": structured,
        "interaction_log": interaction_log or [],
        "expansion_stats": expansion_stats or {},
        "archive": {
            "html_path": str(html_path),
            "screenshot_path": screenshot_path,
        },
    }
