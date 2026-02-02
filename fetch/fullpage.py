"""
Full-page extraction for corporate sites.

Unlike article extractors (trafilatura), this preserves:
- Navigation structure
- Header/hero content
- Main content sections
- Footer links
- CTAs and interactive elements

Designed for corporate site corpus, not news articles.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Comment, Tag


@dataclass
class NavLink:
    text: str
    url: str
    children: list['NavLink'] = field(default_factory=list)


@dataclass
class ContentBlock:
    type: str  # 'text', 'heading', 'list', 'cta', 'image'
    content: str
    level: int = 0  # for headings
    url: str = ''  # for CTAs/images


@dataclass
class TaggedBlock:
    """A content block with source region tagging."""
    block_type: str  # 'nav_block', 'footer_block', 'hero_block', 'main_block', 'ui_block'
    content_type: str  # 'link', 'text', 'heading', 'cta', 'image', 'list'
    content: str
    url: str = ''
    level: int = 0  # for headings
    metadata: dict = field(default_factory=dict)  # extra info (e.g., aria labels)


@dataclass
class FullPageExtraction:
    """Full page extraction result."""
    title: str
    meta_description: str

    # Navigation
    primary_nav: list[NavLink]
    utility_nav: list[NavLink]  # login, search, etc.

    # Main content
    hero_text: str
    main_content: list[ContentBlock]

    # Footer
    footer_links: list[NavLink]
    footer_text: str

    # Tagged blocks (all content with source region tags)
    tagged_blocks: list[TaggedBlock] = field(default_factory=list)

    # Full text (for word count, search)
    full_text: str = ''
    word_count: int = 0


def _clean(text: str) -> str:
    """Clean whitespace."""
    return re.sub(r'\s+', ' ', text).strip()


def _extract_nav_links(container: Tag, base_url: str, depth: int = 0) -> list[NavLink]:
    """Extract navigation links from a container."""
    if depth > 2:  # Prevent infinite recursion
        return []

    links = []
    seen_urls = set()

    for a in container.find_all('a', href=True, recursive=(depth == 0)):
        href = a['href']
        if href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
            continue

        text = _clean(a.get_text())
        if not text or len(text) > 100:  # Skip empty or absurdly long
            continue

        url = urljoin(base_url, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Only look for nested dropdowns at top level
        children = []
        if depth == 0:
            parent_li = a.find_parent('li')
            if parent_li:
                # Look for immediate child submenu, not ancestor
                submenu = parent_li.find(['ul'], recursive=False)
                if submenu and submenu != container:
                    children = _extract_nav_links(submenu, base_url, depth + 1)

        links.append(NavLink(text=text, url=url, children=children))

    return links


def _find_nav_container(soup: BeautifulSoup) -> Tag | None:
    """Find the primary navigation container."""
    # Try semantic nav first
    nav = soup.find('nav', class_=re.compile(r'(main|primary|site)', re.I))
    if nav:
        return nav

    # Any nav in header
    header = soup.find('header')
    if header:
        nav = header.find('nav')
        if nav:
            return nav
        # MUI: look for toolbar or nav-like divs in header
        toolbar = header.find(class_=re.compile(r'(toolbar|MuiToolbar|nav)', re.I))
        if toolbar:
            return toolbar
        # Just return header itself - it often contains nav links
        return header

    # Fallback to first nav
    nav = soup.find('nav')
    if nav:
        return nav

    # MUI/custom: look for nav by class patterns
    for pattern in [r'main-nav', r'primary-nav', r'site-nav', r'navigation', r'MuiToolbar']:
        container = soup.find(class_=re.compile(pattern, re.I))
        if container:
            return container

    return None


def _extract_all_nav_links(soup: BeautifulSoup, base_url: str) -> tuple[list[NavLink], list[NavLink]]:
    """
    Extract all navigation-style links from the page.
    Returns (primary_nav, utility_nav) based on link patterns.
    """
    utility_patterns = re.compile(r'(login|log.in|sign.in|register|account|cart|search)', re.I)
    nav_patterns = re.compile(r'(solution|service|carrier|shipper|resource|company|about|contact|equipment)', re.I)

    primary = []
    utility = []
    seen = set()

    # Look in header first
    header = soup.find('header')
    if header:
        for a in header.find_all('a', href=True):
            href = a['href']
            if href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue
            text = _clean(a.get_text())
            if not text or len(text) > 80:
                continue
            url = urljoin(base_url, href)
            if url in seen:
                continue
            seen.add(url)

            link = NavLink(text=text, url=url)
            if utility_patterns.search(text) or utility_patterns.search(href):
                utility.append(link)
            else:
                primary.append(link)

    # Look for main nav menus (often have 'menu' class)
    for menu in soup.find_all(class_=re.compile(r'menu', re.I)):
        # Skip if inside footer
        if menu.find_parent(class_=re.compile(r'footer', re.I)):
            continue
        for a in menu.find_all('a', href=True):
            href = a['href']
            if href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue
            text = _clean(a.get_text())
            if not text or len(text) > 80:
                continue
            url = urljoin(base_url, href)
            if url in seen:
                continue
            seen.add(url)

            # Categorize by text/url pattern
            if nav_patterns.search(text) or nav_patterns.search(href):
                primary.append(NavLink(text=text, url=url))

    return primary, utility


def _find_utility_nav(soup: BeautifulSoup) -> Tag | None:
    """Find utility navigation (login, search, etc.)."""
    # Look for utility nav patterns
    for pattern in [r'util', r'secondary', r'top-nav', r'account', r'user']:
        nav = soup.find(['nav', 'div', 'ul'], class_=re.compile(pattern, re.I))
        if nav:
            return nav
    return None


def _extract_hero(soup: BeautifulSoup) -> str:
    """Extract hero/banner section text."""
    hero_texts = []
    seen = set()

    # Look for hero containers
    for pattern in [r'hero', r'banner', r'jumbotron', r'masthead', r'splash']:
        for container in soup.find_all(class_=re.compile(pattern, re.I)):
            text = _clean(container.get_text())
            # Dedupe and skip duplicates (carousel slides often repeat)
            text_key = text[:100].lower()  # Use first 100 chars as key
            if text and len(text) > 20 and text_key not in seen:
                seen.add(text_key)
                hero_texts.append(text)
                break  # Take first match only
        if hero_texts:
            break

    # Also check for prominent headings near top
    if not hero_texts:
        main = soup.find('main') or soup.body
        if main:
            first_h1 = main.find('h1')
            if first_h1:
                h1_text = _clean(first_h1.get_text())
                if h1_text not in seen:
                    hero_texts.append(h1_text)
                    seen.add(h1_text)
                # Get following paragraph
                next_p = first_h1.find_next('p')
                if next_p:
                    p_text = _clean(next_p.get_text())
                    if p_text not in seen:
                        hero_texts.append(p_text)

    return ' '.join(hero_texts)


def _extract_main_content(soup: BeautifulSoup, base_url: str) -> list[ContentBlock]:
    """Extract main content blocks in DOM order."""
    blocks = []

    # Find main content container
    main = soup.find('main') or soup.find('article') or soup.find(id=re.compile(r'(content|main)', re.I))
    if not main:
        main = soup.body

    if not main:
        return blocks

    # Walk through content elements
    for el in main.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'a', 'img']):
        # Skip if inside nav/header/footer
        if el.find_parent(['nav', 'header', 'footer']):
            continue

        name = el.name.lower()

        if name.startswith('h'):
            level = int(name[1])
            text = _clean(el.get_text())
            if text:
                blocks.append(ContentBlock(type='heading', content=text, level=level))

        elif name == 'p':
            text = _clean(el.get_text())
            if text and len(text) > 20:  # Skip tiny fragments
                blocks.append(ContentBlock(type='text', content=text))

        elif name == 'li':
            # Only if not already captured via parent
            text = _clean(el.get_text())
            if text and len(text) > 10:
                blocks.append(ContentBlock(type='list', content=f"• {text}"))

        elif name == 'a':
            # Check if it's a CTA button
            classes = ' '.join(el.get('class', []))
            if re.search(r'(btn|button|cta)', classes, re.I):
                text = _clean(el.get_text())
                href = el.get('href', '')
                if text and href:
                    url = urljoin(base_url, href)
                    blocks.append(ContentBlock(type='cta', content=text, url=url))

        elif name == 'img':
            alt = el.get('alt', '')
            src = el.get('src') or el.get('data-src', '')
            if alt and src:
                url = urljoin(base_url, src)
                blocks.append(ContentBlock(type='image', content=alt, url=url))

    return blocks


def _extract_footer(soup: BeautifulSoup, base_url: str) -> tuple[list[NavLink], str]:
    """Extract footer links and text."""
    footer = soup.find('footer')

    # Fallback: look for footer by class patterns (including React/CSS module patterns)
    if not footer:
        for pattern in [r'footer', r'site-footer', r'page-footer', r'Footer', r'BottomFooter', r'FooterNav']:
            footer = soup.find(class_=re.compile(pattern, re.I))
            if footer:
                break

    # Fallback: look for footer by id
    if not footer:
        footer = soup.find(id=re.compile(r'footer', re.I))

    # Fallback: find section containing copyright/privacy text
    if not footer:
        for el in soup.find_all(string=re.compile(r'copyright|©', re.I)):
            parent = el.find_parent(['div', 'section', 'footer'])
            if parent:
                # Walk up to find a container with multiple links
                while parent and len(parent.find_all('a')) < 5:
                    parent = parent.find_parent(['div', 'section'])
                if parent and len(parent.find_all('a')) >= 5:
                    footer = parent
                    break

    # Fallback: look for last section with lots of links (common footer pattern)
    if not footer:
        body = soup.body
        if body:
            for div in reversed(body.find_all('div', recursive=False)[-5:]):
                links_in_div = div.find_all('a', href=True)
                if len(links_in_div) > 10:
                    text = div.get_text().lower()
                    if 'copyright' in text or '©' in text or 'privacy' in text:
                        footer = div
                        break

    if not footer:
        return [], ''

    # Extract links
    links = []
    seen = set()
    for a in footer.find_all('a', href=True):
        href = a['href']
        if href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
            continue
        text = _clean(a.get_text())
        if not text or len(text) > 100:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        links.append(NavLink(text=text, url=url))

    # Get footer text (copyright, legal, etc.)
    footer_text = _clean(footer.get_text())

    return links, footer_text


def _build_full_text(soup: BeautifulSoup) -> str:
    """Build full text from entire page (for search/word count)."""
    # Remove scripts/styles
    for tag in soup.find_all(['script', 'style', 'noscript']):
        tag.decompose()

    body = soup.body
    if not body:
        return ''

    return _clean(body.get_text(separator=' '))


def _build_tagged_blocks(
    soup: BeautifulSoup,
    base_url: str,
    primary_nav: list[NavLink],
    utility_nav: list[NavLink],
    hero_text: str,
    main_content: list[ContentBlock],
    footer_links: list[NavLink],
    footer_text: str,
) -> list[TaggedBlock]:
    """
    Build tagged blocks from all page regions.

    Each block is tagged with its source region:
    - nav_block: Navigation links (primary + utility)
    - hero_block: Hero/banner content
    - main_block: Main content (text, headings, lists)
    - ui_block: Interactive UI elements (CTAs, buttons)
    - footer_block: Footer links and text
    """
    blocks = []

    # Nav blocks (primary navigation)
    for link in primary_nav:
        blocks.append(TaggedBlock(
            block_type='nav_block',
            content_type='link',
            content=link.text,
            url=link.url,
            metadata={'nav_type': 'primary'},
        ))
        # Include children if present
        for child in link.children:
            blocks.append(TaggedBlock(
                block_type='nav_block',
                content_type='link',
                content=child.text,
                url=child.url,
                metadata={'nav_type': 'primary', 'parent': link.text},
            ))

    # Utility nav blocks (login, search, etc.)
    for link in utility_nav:
        blocks.append(TaggedBlock(
            block_type='nav_block',
            content_type='link',
            content=link.text,
            url=link.url,
            metadata={'nav_type': 'utility'},
        ))

    # Hero block
    if hero_text:
        blocks.append(TaggedBlock(
            block_type='hero_block',
            content_type='text',
            content=hero_text,
        ))

    # Main content blocks
    for block in main_content:
        if block.type == 'cta':
            # CTAs are UI blocks
            blocks.append(TaggedBlock(
                block_type='ui_block',
                content_type='cta',
                content=block.content,
                url=block.url,
            ))
        elif block.type == 'heading':
            blocks.append(TaggedBlock(
                block_type='main_block',
                content_type='heading',
                content=block.content,
                level=block.level,
            ))
        elif block.type == 'image':
            blocks.append(TaggedBlock(
                block_type='main_block',
                content_type='image',
                content=block.content,
                url=block.url,
            ))
        else:
            blocks.append(TaggedBlock(
                block_type='main_block',
                content_type=block.type,
                content=block.content,
            ))

    # Footer blocks
    for link in footer_links:
        blocks.append(TaggedBlock(
            block_type='footer_block',
            content_type='link',
            content=link.text,
            url=link.url,
        ))

    if footer_text:
        # Extract just copyright/legal text (not full footer)
        copyright_match = re.search(r'(©|copyright).{0,100}', footer_text, re.I)
        if copyright_match:
            blocks.append(TaggedBlock(
                block_type='footer_block',
                content_type='text',
                content=copyright_match.group(0).strip(),
                metadata={'subtype': 'copyright'},
            ))

    return blocks


def extract_full_page(html: str, base_url: str = '') -> FullPageExtraction:
    """
    Extract full page content preserving structure.

    Args:
        html: Raw HTML content
        base_url: Base URL for resolving relative links

    Returns:
        FullPageExtraction with all page components
    """
    soup = BeautifulSoup(html, 'lxml')

    # Remove comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Title and meta
    title = ''
    if soup.title and soup.title.string:
        title = _clean(soup.title.string)

    meta_desc = ''
    meta_tag = soup.find('meta', attrs={'name': 'description'})
    if meta_tag:
        meta_desc = meta_tag.get('content', '')

    # Navigation - use the smarter extractor that looks across the page
    primary_nav, utility_nav = _extract_all_nav_links(soup, base_url)

    # Hero
    hero_text = _extract_hero(soup)

    # Main content
    main_content = _extract_main_content(soup, base_url)

    # Footer
    footer_links, footer_text = _extract_footer(soup, base_url)

    # Full text
    full_text = _build_full_text(soup)
    word_count = len(full_text.split())

    # Build tagged blocks for structured analysis
    tagged_blocks = _build_tagged_blocks(
        soup=soup,
        base_url=base_url,
        primary_nav=primary_nav,
        utility_nav=utility_nav,
        hero_text=hero_text,
        main_content=main_content,
        footer_links=footer_links,
        footer_text=footer_text,
    )

    return FullPageExtraction(
        title=title,
        meta_description=meta_desc,
        primary_nav=primary_nav,
        utility_nav=utility_nav,
        hero_text=hero_text,
        main_content=main_content,
        footer_links=footer_links,
        footer_text=footer_text,
        tagged_blocks=tagged_blocks,
        full_text=full_text,
        word_count=word_count,
    )


def extraction_to_text(extraction: FullPageExtraction) -> str:
    """Convert extraction to readable text format (similar to WebFetch output)."""
    lines = []

    lines.append(f"# {extraction.title}")
    lines.append("")

    if extraction.meta_description:
        lines.append(f"_{extraction.meta_description}_")
        lines.append("")

    # Navigation
    if extraction.utility_nav:
        lines.append("## Quick Links")
        for link in extraction.utility_nav[:10]:  # Limit
            lines.append(f"- {link.text}")
        lines.append("")

    if extraction.primary_nav:
        lines.append("## Navigation")
        for link in extraction.primary_nav[:20]:  # Limit
            if link.children:
                lines.append(f"- **{link.text}**")
                for child in link.children[:10]:
                    lines.append(f"  - {child.text}")
            else:
                lines.append(f"- {link.text}")
        lines.append("")

    # Hero
    if extraction.hero_text:
        lines.append("## Hero")
        lines.append(extraction.hero_text)
        lines.append("")

    # Main content
    if extraction.main_content:
        lines.append("## Content")
        for block in extraction.main_content:
            if block.type == 'heading':
                prefix = '#' * min(block.level + 2, 6)
                lines.append(f"{prefix} {block.content}")
            elif block.type == 'text':
                lines.append(block.content)
                lines.append("")
            elif block.type == 'list':
                lines.append(block.content)
            elif block.type == 'cta':
                lines.append(f"**[{block.content}]**")
            elif block.type == 'image':
                lines.append(f"[Image: {block.content}]")
        lines.append("")

    # Footer
    if extraction.footer_links:
        lines.append("## Footer")
        for link in extraction.footer_links[:30]:  # Limit
            lines.append(f"- {link.text}")
        lines.append("")

    lines.append(f"---")
    lines.append(f"Word count: {extraction.word_count}")

    return '\n'.join(lines)


def extraction_to_dict(extraction: FullPageExtraction) -> dict:
    """Convert extraction to JSON-serializable dict."""
    return {
        'title': extraction.title,
        'meta_description': extraction.meta_description,
        'primary_nav': [
            {'text': l.text, 'url': l.url, 'children': [{'text': c.text, 'url': c.url} for c in l.children]}
            for l in extraction.primary_nav
        ],
        'utility_nav': [{'text': l.text, 'url': l.url} for l in extraction.utility_nav],
        'hero_text': extraction.hero_text,
        'main_content': [
            {'type': b.type, 'content': b.content, 'level': b.level, 'url': b.url}
            for b in extraction.main_content
        ],
        'footer_links': [{'text': l.text, 'url': l.url} for l in extraction.footer_links],
        'footer_text': extraction.footer_text,
        'tagged_blocks': [
            {
                'block_type': b.block_type,
                'content_type': b.content_type,
                'content': b.content,
                'url': b.url,
                'level': b.level,
                'metadata': b.metadata,
            }
            for b in extraction.tagged_blocks
        ],
        'full_text': extraction.full_text,
        'word_count': extraction.word_count,
    }
