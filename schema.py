"""
Schema definitions for trucking web corpus.

This defines the data structures for:
- Individual pages (with sections, text, term vectors)
- Full site extractions (sitemap, all pages, metadata)
- Aggregate analysis (cross-site comparisons, "mean website")
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class ImageBlock:
    """An extracted image with context."""
    src: str
    src_resolved: str
    alt: Optional[str] = None
    title: Optional[str] = None
    caption: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    srcset: Optional[str] = None
    context_heading: Optional[str] = None
    context_text: Optional[str] = None
    figure_caption: Optional[str] = None
    classification: str = "unknown"
    is_lazy: bool = False
    is_decorative: bool = False
    source_tag: str = "img"
    xpath: Optional[str] = None


@dataclass
class CodeBlock:
    """An extracted code block with context."""
    content: str
    language: Optional[str] = None
    language_confidence: float = 0.0
    is_inline: bool = False
    is_config: bool = False
    is_truncated: bool = False
    context_heading: Optional[str] = None
    context_text: Optional[str] = None
    filename_hint: Optional[str] = None
    line_count: int = 0
    char_count: int = 0
    source_tag: str = "code"
    xpath: Optional[str] = None


@dataclass
class Section:
    """A semantic block within a page (heading + content)"""
    heading: Optional[str]  # None for intro/hero content before first heading
    text: str
    heading_level: Optional[int]  # h1=1, h2=2, etc.
    word_count: int = 0


@dataclass
class Page:
    """A single crawled page"""
    url: str
    path: str  # URL path component, e.g., "/services/intermodal"
    title: str
    page_type: str  # home, service, about, careers, news, contact, investor, etc.

    sections: list[Section] = field(default_factory=list)
    section_tree: Optional[dict] = None
    full_text: str = ""  # All text concatenated
    images: list[ImageBlock] = field(default_factory=list)
    code_blocks: list[CodeBlock] = field(default_factory=list)

    # Structural metadata
    h1: Optional[str] = None
    meta_description: Optional[str] = None

    # Computed
    word_count: int = 0
    term_counts: dict[str, int] = field(default_factory=dict)

    # Raw storage refs
    html_file: Optional[str] = None
    screenshot_file: Optional[str] = None


@dataclass
class SiteStructure:
    """Sitemap / information architecture of a site"""
    total_pages: int
    max_depth: int
    page_types: dict[str, int]  # page_type -> count
    url_tree: dict  # nested dict representing URL hierarchy


@dataclass
class Site:
    """Full extraction of a single company's website"""
    domain: str
    company_name: str
    category: list[str]  # tl, ltl, 3pl, intermodal, specialty
    tier: int

    snapshot_date: str
    crawl_duration_sec: float

    pages: list[Page] = field(default_factory=list)
    structure: Optional[SiteStructure] = None

    # Aggregate stats
    total_word_count: int = 0
    term_counts: dict[str, int] = field(default_factory=dict)  # Across all pages

    # Assets
    js_files: list[str] = field(default_factory=list)
    css_files: list[str] = field(default_factory=list)
    image_count: int = 0
    code_block_count: int = 0


# Page type classification heuristics
PAGE_TYPE_PATTERNS = {
    "home": [r"^/$", r"^/index"],
    "service": [r"/service", r"/solution", r"/shipping", r"/freight", r"/transport"],
    "about": [r"/about", r"/company", r"/who-we-are", r"/our-story"],
    "careers": [r"/career", r"/job", r"/hiring", r"/driver", r"/employment"],
    "contact": [r"/contact", r"/location", r"/find-us"],
    "news": [r"/news", r"/press", r"/media", r"/blog", r"/article"],
    "investor": [r"/investor", r"/shareholder", r"/financial", r"/sec-filing"],
    "technology": [r"/tech", r"/platform", r"/digital", r"/innovation", r"/360"],
    "sustainability": [r"/sustain", r"/environment", r"/esg", r"/green"],
    "customer_portal": [r"/login", r"/portal", r"/my-account", r"/track"],
}

# Terms to track across corpus
TRACKED_TERMS = [
    # Tech buzzwords
    "ai", "artificial intelligence", "machine learning", "ml", "automation",
    "digital", "platform", "technology", "visibility", "real-time", "analytics",
    "api", "integration", "iot", "blockchain",

    # Industry terms
    "intermodal", "truckload", "ltl", "drayage", "last mile", "final mile",
    "dedicated", "brokerage", "3pl", "4pl", "supply chain", "logistics",

    # Value props
    "sustainability", "carbon", "emissions", "green", "environment",
    "safety", "reliable", "on-time", "capacity", "network",
    "partner", "solution", "customer", "service",

    # Scale signals
    "nationwide", "north america", "global", "international",
]
