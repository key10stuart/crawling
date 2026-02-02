"""
Image extraction from HTML.

Extracts all image candidates with context:
- <img> tags (src, srcset, alt, title, dimensions)
- <picture> sources
- <figure> + <figcaption> associations
- CSS background-image URLs
- Open Graph / Twitter card images
- Lazy-load patterns (data-src, data-lazy)
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag


@dataclass
class ImageBlock:
    """Extracted image with context."""
    src: str
    src_resolved: str
    alt: str | None = None
    title: str | None = None
    caption: str | None = None
    width: int | None = None
    height: int | None = None
    srcset: str | None = None

    # Context
    context_heading: str | None = None  # Nearest heading
    context_text: str | None = None     # Surrounding paragraph
    figure_caption: str | None = None   # <figcaption> if in <figure>

    # Classification
    classification: str = 'unknown'  # photo, diagram, screenshot, icon, logo, unknown
    is_lazy: bool = False            # Was loaded via lazy-load pattern
    is_decorative: bool = False      # Likely decorative (no alt, tiny, etc.)

    # Source info
    source_tag: str = 'img'          # img, picture, background, og:image, etc.
    xpath: str | None = None


# Patterns for lazy-load attributes
LAZY_LOAD_ATTRS = [
    'data-src', 'data-lazy', 'data-original', 'data-srcset',
    'data-lazy-src', 'data-bg', 'data-background',
    'loading',  # native lazy loading
]

# Patterns suggesting decorative images
DECORATIVE_PATTERNS = [
    r'spacer', r'pixel', r'blank', r'transparent',
    r'1x1', r'sprite', r'icon-', r'-icon',
]

# Patterns for classification
LOGO_PATTERNS = [r'logo', r'brand', r'wordmark']
ICON_PATTERNS = [r'icon', r'ico-', r'-ico', r'favicon', r'sprite']
DIAGRAM_PATTERNS = [r'diagram', r'chart', r'graph', r'flow', r'architecture']
SCREENSHOT_PATTERNS = [r'screenshot', r'screen-', r'capture', r'preview']


def classify_image(src: str, alt: str | None, width: int | None, height: int | None) -> tuple[str, bool]:
    """
    Classify image type and determine if decorative.

    Returns:
        Tuple of (classification, is_decorative)
    """
    src_lower = src.lower()
    alt_lower = (alt or '').lower()
    combined = f"{src_lower} {alt_lower}"

    # Check for decorative
    is_decorative = False
    for pattern in DECORATIVE_PATTERNS:
        if re.search(pattern, combined):
            is_decorative = True
            break

    # Size-based decorative detection
    if width and height:
        if width <= 3 and height <= 3:
            is_decorative = True
        elif width <= 50 and height <= 50 and not alt:
            is_decorative = True  # Tiny with no alt = likely decorative

    # Classification
    for pattern in LOGO_PATTERNS:
        if re.search(pattern, combined):
            return 'logo', is_decorative

    for pattern in ICON_PATTERNS:
        if re.search(pattern, combined):
            return 'icon', is_decorative

    for pattern in DIAGRAM_PATTERNS:
        if re.search(pattern, combined):
            return 'diagram', is_decorative

    for pattern in SCREENSHOT_PATTERNS:
        if re.search(pattern, combined):
            return 'screenshot', is_decorative

    # Default to photo for larger images, unknown for smaller
    if width and height and width > 200 and height > 200:
        return 'photo', is_decorative

    return 'unknown', is_decorative


def resolve_lazy_src(tag: Tag) -> str | None:
    """Extract actual src from lazy-load patterns."""
    for attr in LAZY_LOAD_ATTRS:
        value = tag.get(attr)
        if value and isinstance(value, str) and value.startswith(('http', '/', 'data:')):
            return value
    return None


def get_dimensions(tag: Tag) -> tuple[int | None, int | None]:
    """Extract width and height from tag attributes."""
    width = tag.get('width')
    height = tag.get('height')

    # Try to parse as int
    try:
        width = int(width) if width else None
    except (ValueError, TypeError):
        width = None

    try:
        height = int(height) if height else None
    except (ValueError, TypeError):
        height = None

    return width, height


def find_nearest_heading(tag: Tag) -> str | None:
    """Find the nearest preceding heading for context."""
    # Walk up and back to find heading
    for parent in tag.parents:
        if parent.name in ['article', 'section', 'div', 'main']:
            # Look for heading in this container
            heading = parent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if heading:
                return heading.get_text(strip=True)

    # Try previous siblings
    for sibling in tag.find_all_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        text = sibling.get_text(strip=True)
        if text:
            return text

    return None


def find_context_text(tag: Tag, max_chars: int = 200) -> str | None:
    """Find surrounding paragraph text for context."""
    # Check if in figure with figcaption
    parent = tag.parent
    while parent:
        if parent.name == 'figure':
            figcaption = parent.find('figcaption')
            if figcaption:
                return figcaption.get_text(strip=True)[:max_chars]
        parent = parent.parent

    # Look for adjacent paragraph
    for sibling in tag.find_all_previous(['p'], limit=2):
        text = sibling.get_text(strip=True)
        if text and len(text) > 20:
            return text[:max_chars]

    for sibling in tag.find_all_next(['p'], limit=2):
        text = sibling.get_text(strip=True)
        if text and len(text) > 20:
            return text[:max_chars]

    return None


def extract_img_tags(soup: BeautifulSoup, base_url: str) -> list[ImageBlock]:
    """Extract images from <img> tags."""
    images = []

    for img in soup.find_all('img'):
        src = img.get('src', '')

        # Check for lazy-load
        lazy_src = resolve_lazy_src(img)
        is_lazy = lazy_src is not None
        if lazy_src:
            src = lazy_src

        if not src or src.startswith('data:image/gif'):  # Skip tiny data URIs
            continue

        # Resolve relative URLs
        src_resolved = urljoin(base_url, src) if not src.startswith(('http://', 'https://', 'data:')) else src

        alt = img.get('alt')
        title = img.get('title')
        srcset = img.get('srcset')
        width, height = get_dimensions(img)

        classification, is_decorative = classify_image(src, alt, width, height)

        images.append(ImageBlock(
            src=src,
            src_resolved=src_resolved,
            alt=alt,
            title=title,
            width=width,
            height=height,
            srcset=srcset,
            context_heading=find_nearest_heading(img),
            context_text=find_context_text(img),
            classification=classification,
            is_lazy=is_lazy,
            is_decorative=is_decorative,
            source_tag='img',
        ))

    return images


def extract_picture_tags(soup: BeautifulSoup, base_url: str) -> list[ImageBlock]:
    """Extract images from <picture> elements."""
    images = []

    for picture in soup.find_all('picture'):
        # Get the fallback img
        img = picture.find('img')
        if not img:
            continue

        src = img.get('src', '')
        lazy_src = resolve_lazy_src(img)
        is_lazy = lazy_src is not None
        if lazy_src:
            src = lazy_src

        if not src:
            # Try first source
            source = picture.find('source')
            if source:
                src = source.get('srcset', '').split(',')[0].split()[0]

        if not src:
            continue

        src_resolved = urljoin(base_url, src) if not src.startswith(('http://', 'https://')) else src

        alt = img.get('alt')
        width, height = get_dimensions(img)
        classification, is_decorative = classify_image(src, alt, width, height)

        images.append(ImageBlock(
            src=src,
            src_resolved=src_resolved,
            alt=alt,
            title=img.get('title'),
            width=width,
            height=height,
            context_heading=find_nearest_heading(picture),
            context_text=find_context_text(picture),
            classification=classification,
            is_lazy=is_lazy,
            is_decorative=is_decorative,
            source_tag='picture',
        ))

    return images


def extract_og_images(soup: BeautifulSoup, base_url: str) -> list[ImageBlock]:
    """Extract Open Graph and Twitter card images."""
    images = []

    og_tags = [
        ('og:image', 'og:image'),
        ('og:image:url', 'og:image'),
        ('twitter:image', 'twitter:image'),
        ('twitter:image:src', 'twitter:image'),
    ]

    for attr, source_tag in og_tags:
        meta = soup.find('meta', property=attr) or soup.find('meta', attrs={'name': attr})
        if meta:
            content = meta.get('content')
            if content:
                src_resolved = urljoin(base_url, content) if not content.startswith(('http://', 'https://')) else content

                # Avoid duplicates
                if not any(img.src_resolved == src_resolved for img in images):
                    images.append(ImageBlock(
                        src=content,
                        src_resolved=src_resolved,
                        classification='photo',  # OG images are typically main photos
                        is_decorative=False,
                        source_tag=source_tag,
                    ))

    return images


def extract_background_images(soup: BeautifulSoup, base_url: str) -> list[ImageBlock]:
    """Extract CSS background-image URLs from inline styles."""
    images = []
    bg_pattern = re.compile(r'background(?:-image)?\s*:\s*url\([\'"]?([^\'")]+)[\'"]?\)', re.I)

    for tag in soup.find_all(style=True):
        style = tag.get('style', '')
        matches = bg_pattern.findall(style)

        for src in matches:
            if src.startswith('data:'):
                continue

            src_resolved = urljoin(base_url, src) if not src.startswith(('http://', 'https://')) else src

            images.append(ImageBlock(
                src=src,
                src_resolved=src_resolved,
                context_heading=find_nearest_heading(tag),
                context_text=find_context_text(tag),
                classification='unknown',
                is_decorative=False,  # Background images are often decorative but may be content
                source_tag='background',
            ))

    return images


def extract_images(html: str, base_url: str, include_decorative: bool = False) -> list[ImageBlock]:
    """
    Extract all images from HTML.

    Args:
        html: Raw HTML content
        base_url: Base URL for resolving relative paths
        include_decorative: Whether to include decorative images (spacers, icons, etc.)

    Returns:
        List of ImageBlock objects
    """
    soup = BeautifulSoup(html, 'lxml')

    images = []

    # Extract from different sources
    images.extend(extract_img_tags(soup, base_url))
    images.extend(extract_picture_tags(soup, base_url))
    images.extend(extract_og_images(soup, base_url))
    images.extend(extract_background_images(soup, base_url))

    # Dedupe by resolved URL
    seen = set()
    deduped = []
    for img in images:
        if img.src_resolved not in seen:
            seen.add(img.src_resolved)
            deduped.append(img)

    # Filter decorative if requested
    if not include_decorative:
        deduped = [img for img in deduped if not img.is_decorative]

    return deduped
