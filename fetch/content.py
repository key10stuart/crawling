"""
Content processing utilities extracted from scripts/crawl.py (Div 4k Phase 3).
"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .fullpage import extract_full_page


# Elements to strip from content extraction
STRIP_TAGS = [
    'script', 'style', 'nav', 'header', 'footer', 'aside',
    'noscript', 'iframe', 'form', 'svg', 'path',
]
STRIP_CLASSES = ['cookie', 'modal', 'popup', 'advertisement', 'cc-window', 'cc-banner']


# Page type classification patterns (from schema.py)
PAGE_TYPE_PATTERNS = {
    "home": [r"^/$", r"^/index", r"^/?$"],
    "service": [r"/service", r"/solution", r"/shipping", r"/freight", r"/transport", r"/mode"],
    "about": [r"/about", r"/company", r"/who-we-are", r"/our-story", r"/history", r"/leadership"],
    "careers": [r"/career", r"/job", r"/hiring", r"/driver", r"/employment", r"/work-with-us"],
    "contact": [r"/contact", r"/location", r"/find-us", r"/get-in-touch"],
    "news": [r"/news", r"/press", r"/media", r"/blog", r"/article", r"/insights"],
    "investor": [r"/investor", r"/shareholder", r"/financial", r"/sec-filing", r"/stock"],
    "technology": [r"/tech", r"/platform", r"/digital", r"/innovation", r"/360", r"/tools"],
    "sustainability": [r"/sustain", r"/environment", r"/esg", r"/green", r"/carbon"],
    "customer_portal": [r"/login", r"/portal", r"/my-account", r"/track", r"/quote"],
    "carrier": [r"/carrier", r"/owner-operator", r"/partner"],
}


# Terms to count
TRACKED_TERMS = [
    "ai", "artificial intelligence", "machine learning", "automation",
    "digital", "platform", "technology", "visibility", "real-time", "analytics",
    "api", "integration", "iot",
    "intermodal", "truckload", "ltl", "drayage", "last mile", "final mile",
    "dedicated", "brokerage", "3pl", "supply chain", "logistics",
    "sustainability", "carbon", "emissions", "green",
    "safety", "reliable", "on-time", "capacity", "network",
    "partner", "solution", "nationwide", "north america", "global",
]


def classify_page_type(path: str) -> str:
    """Classify page type based on URL path."""
    path_lower = path.lower()
    for page_type, patterns in PAGE_TYPE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, path_lower):
                return page_type
    return "other"


def extract_page_content(html: str, url: str) -> dict:
    """
    Extract structured content from HTML using dual extraction:
    - full_text: Complete page (nav, hero, main, footer) for structural analysis
    - main_content: Article-focused extraction (trafilatura) for content analysis
    """
    extraction = extract_full_page(html, url)

    main_content = ''
    try:
        import trafilatura
        doc = trafilatura.bare_extraction(html, include_tables=True, favor_recall=True)
        if doc:
            main_content = getattr(doc, 'text', '') or ''
    except Exception:
        pass

    soup = BeautifulSoup(html, 'lxml')
    h1_tag = soup.find('h1')
    h1 = h1_tag.get_text(strip=True) if h1_tag else None

    sections = [{
        'heading': None,
        'heading_level': None,
        'text': extraction.full_text,
        'word_count': extraction.word_count,
    }]

    nav_links = [{'text': link.text, 'url': link.url} for link in extraction.primary_nav]

    return {
        'title': extraction.title,
        'h1': h1,
        'meta_description': extraction.meta_description,
        'sections': sections,
        'full_text': extraction.full_text,
        'main_content': main_content,
        'word_count': extraction.word_count,
        'main_content_word_count': len(main_content.split()) if main_content else 0,
        'nav_links': nav_links,
        'hero_text': extraction.hero_text,
    }


def count_terms(text: str) -> dict[str, int]:
    """Count occurrences of tracked terms in text."""
    text_lower = text.lower()
    counts = {}
    for term in TRACKED_TERMS:
        count = len(re.findall(r'\b' + re.escape(term) + r'\b', text_lower))
        if count > 0:
            counts[term] = count
    return counts


def discover_links(html: str, base_url: str, domain: str) -> set[str]:
    """Find internal links on a page."""
    soup = BeautifulSoup(html, 'lxml')
    links = set()

    for a in soup.find_all('a', href=True):
        href = a['href']

        if href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
            continue

        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        if parsed.netloc.replace('www.', '') == domain.replace('www.', ''):
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean_url += f"?{parsed.query}"
            links.add(clean_url)

    return links


def _is_noise_container(tag: Tag) -> bool:
    """Check if tag is inside a likely boilerplate container."""
    for parent in tag.parents:
        if parent.name in ['nav', 'header', 'footer', 'aside', 'form']:
            return True
        class_attr = ' '.join(parent.get('class', []))
        for pattern in STRIP_CLASSES:
            if re.search(pattern, class_attr, re.I):
                return True
    return False


def _clean_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def _resolve_img_src(tag: Tag) -> str | None:
    """Resolve image source, honoring common lazy-load attributes."""
    for attr in ['data-src', 'data-original', 'data-lazy', 'data-srcset']:
        val = tag.get(attr)
        if val and isinstance(val, str):
            return val.split(',')[0].split()[0]
    src = tag.get('src')
    if src and isinstance(src, str):
        return src
    return None


__all__ = [
    "STRIP_TAGS",
    "STRIP_CLASSES",
    "PAGE_TYPE_PATTERNS",
    "TRACKED_TERMS",
    "classify_page_type",
    "extract_page_content",
    "count_terms",
    "discover_links",
    "_is_noise_container",
    "_clean_text",
    "_resolve_img_src",
]
