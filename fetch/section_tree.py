"""
Section tree builder extracted from scripts/crawl.py (Div 4k Phase 4).
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, Tag

from .content import STRIP_TAGS, STRIP_CLASSES, _is_noise_container, _clean_text, _resolve_img_src


def build_section_tree(html: str, base_url: str, tagged_blocks: list[dict] | None = None) -> dict:
    """
    Build a section tree with interleaved blocks.

    If tagged_blocks are provided, prefer a tagged tree (nav/hero/ui/footer/main).
    Falls back to DOM-order extraction otherwise.
    """
    if tagged_blocks:
        root = {"type": "section", "heading": None, "level": 0, "children": []}
        sections: dict[str, dict] = {}
        order = []
        for block in tagged_blocks:
            block_type = block.get("block_type", "main_block")
            if block_type not in sections:
                section = {"type": "section", "heading": block_type, "level": 1, "children": []}
                sections[block_type] = section
                order.append(section)
        for section in order:
            root["children"].append(section)

        for block in tagged_blocks:
            block_type = block.get("block_type", "main_block")
            section = sections.get(block_type)
            if not section:
                continue
            content_type = block.get("content_type", "text")
            content = block.get("content", "")
            url = block.get("url")
            if content_type == "image":
                section["children"].append({
                    "type": "image",
                    "src": url or "",
                    "src_resolved": url or "",
                    "alt": content,
                    "tag": "tagged",
                })
            elif content_type == "link":
                section["children"].append({
                    "type": "text",
                    "text": content,
                    "tag": "link",
                    "word_count": len(content.split()),
                    "url": url,
                })
            elif content_type == "heading":
                section["children"].append({
                    "type": "text",
                    "text": content,
                    "tag": "heading",
                    "word_count": len(content.split()),
                })
            else:
                section["children"].append({
                    "type": "text",
                    "text": content,
                    "tag": "tagged",
                    "word_count": len(content.split()),
                })

        return root

    soup = BeautifulSoup(html, 'lxml')

    for tag in STRIP_TAGS:
        for el in soup.find_all(tag):
            el.decompose()
    for class_pattern in STRIP_CLASSES:
        for el in soup.find_all(class_=re.compile(class_pattern, re.I)):
            el.decompose()
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    root = {"type": "section", "heading": None, "level": 0, "children": []}
    stack = [root]

    def current_section() -> dict:
        return stack[-1]

    for el in soup.body.descendants if soup.body else []:
        if not isinstance(el, Tag):
            continue

        name = el.name.lower()

        if name in ['script', 'style', 'noscript']:
            continue

        if _is_noise_container(el):
            continue

        if name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            heading_text = _clean_text(el.get_text())
            if not heading_text:
                continue
            level = int(name[1])
            section = {"type": "section", "heading": heading_text, "level": level, "children": []}
            while stack and stack[-1].get("level", 0) >= level:
                stack.pop()
            if not stack:
                stack = [root]
            stack[-1]["children"].append(section)
            stack.append(section)
            continue

        if name in ['p', 'li', 'blockquote', 'figcaption', 'td', 'th']:
            text = _clean_text(el.get_text())
            if text and len(text) >= 20:
                current_section()["children"].append({
                    "type": "text",
                    "text": text,
                    "tag": name,
                    "word_count": len(text.split()),
                })
            continue

        if name == 'img':
            src = _resolve_img_src(el)
            if not src or src.startswith('data:image/gif'):
                continue
            src_resolved = urljoin(base_url, src) if not src.startswith(('http://', 'https://', 'data:')) else src
            alt = el.get('alt')
            title = el.get('title')
            width = el.get('width')
            height = el.get('height')
            try:
                width = int(width) if width else None
            except (ValueError, TypeError):
                width = None
            try:
                height = int(height) if height else None
            except (ValueError, TypeError):
                height = None
            current_section()["children"].append({
                "type": "image",
                "src": src,
                "src_resolved": src_resolved,
                "alt": alt,
                "title": title,
                "width": width,
                "height": height,
                "tag": "img",
            })
            continue

        if name == 'pre':
            code_tag = el.find('code')
            content = code_tag.get_text() if code_tag else el.get_text()
            content = content.strip()
            if content and len(content) >= 20:
                current_section()["children"].append({
                    "type": "code",
                    "content": content,
                    "tag": "pre",
                    "line_count": content.count('\n') + 1,
                    "char_count": len(content),
                })
            continue

        if name == 'code' and not el.find_parent('pre'):
            content = el.get_text().strip()
            if content and len(content) >= 20:
                current_section()["children"].append({
                    "type": "code",
                    "content": content,
                    "tag": "code",
                    "line_count": content.count('\n') + 1,
                    "char_count": len(content),
                })
            continue

    return root


__all__ = ["build_section_tree"]
