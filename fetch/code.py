"""
Code block extraction from HTML.

Extracts code candidates with context and language detection:
- <pre> blocks (with or without <code>)
- <code> elements (inline and block)
- Syntax highlighter patterns (Prism, highlight.js, GitHub, etc.)
- <script type="application/json"> config data
- Elements with code-related class hints
"""

import re
from dataclasses import dataclass
from typing import Literal

from bs4 import BeautifulSoup, Tag


@dataclass
class CodeBlock:
    """Extracted code block with context."""
    content: str
    language: str | None = None
    language_confidence: float = 0.0  # 0.0 = guess, 1.0 = explicit

    # Classification
    is_inline: bool = False
    is_config: bool = False  # JSON config, not executable code
    is_truncated: bool = False  # Detected "..." or similar

    # Context
    context_heading: str | None = None
    context_text: str | None = None  # Preceding explanation
    filename_hint: str | None = None

    # Metrics
    line_count: int = 0
    char_count: int = 0

    # Source info
    source_tag: str = 'code'
    xpath: str | None = None


# Language detection from class names
LANGUAGE_CLASS_PATTERNS = [
    # Explicit language classes
    (r'language-(\w+)', 1.0),
    (r'lang-(\w+)', 1.0),
    (r'highlight-source-(\w+)', 1.0),  # GitHub
    (r'(\w+)-code', 0.9),

    # Prism.js / highlight.js patterns
    (r'hljs\s+(\w+)', 0.9),
    (r'prism-(\w+)', 0.9),

    # Generic patterns
    (r'brush:\s*(\w+)', 0.8),  # SyntaxHighlighter
    (r'syntax-(\w+)', 0.8),
    (r'code-(\w+)', 0.7),
]

# Language detection from data attributes
LANGUAGE_DATA_ATTRS = [
    'data-language', 'data-lang', 'data-code-language',
    'data-highlight', 'data-syntax',
]

# Language normalization map
LANGUAGE_ALIASES = {
    'js': 'javascript',
    'ts': 'typescript',
    'py': 'python',
    'rb': 'ruby',
    'sh': 'bash',
    'shell': 'bash',
    'zsh': 'bash',
    'yml': 'yaml',
    'dockerfile': 'docker',
    'objc': 'objective-c',
    'c++': 'cpp',
    'c#': 'csharp',
    'f#': 'fsharp',
    'golang': 'go',
    'rs': 'rust',
    'kt': 'kotlin',
    'md': 'markdown',
    'tex': 'latex',
    'plaintext': 'text',
    'plain': 'text',
    'none': 'text',
}

# Heuristic language detection patterns
LANGUAGE_HEURISTICS = [
    # Python (check first - REPL prompts are strong signal)
    (r'>>>\s', 'python', 0.8),  # Python REPL prompt
    (r'^\s*(def |class |import |from .+ import |if __name__|async def )', 'python', 0.7),
    (r'print\(|self\.|\.append\(|\.items\(\)|\.get\(|\.keys\(\)', 'python', 0.5),
    (r'pip install|python -m|python3', 'python', 0.6),

    # JavaScript/TypeScript
    (r'^\s*(const |let |var |function |=>|import .+ from |export )', 'javascript', 0.7),
    (r'console\.log|document\.|window\.|\.addEventListener', 'javascript', 0.5),
    (r':\s*(string|number|boolean|interface |type )', 'typescript', 0.6),

    # Rust
    (r'^\s*(fn |let mut |impl |pub fn |use |mod )', 'rust', 0.7),
    (r'\.unwrap\(\)|\.expect\(|&str|&mut|Option<|Result<', 'rust', 0.5),

    # Go
    (r'^\s*(func |package |import \(|type .+ struct)', 'go', 0.7),
    (r':= |fmt\.Print|\.Error\(\)', 'go', 0.5),

    # Java
    (r'^\s*(public |private |protected |class |interface |@Override)', 'java', 0.7),
    (r'System\.out\.print|\.equals\(|new [A-Z]', 'java', 0.5),

    # C/C++
    (r'^\s*(#include |int main|void |printf\()', 'c', 0.6),
    (r'std::|cout|cin|#include <iostream>|nullptr', 'cpp', 0.6),

    # Ruby
    (r'^\s*(def |end$|require |class .+ < |attr_accessor)', 'ruby', 0.7),
    (r'\.each do|puts |\.nil\?|\.map \{', 'ruby', 0.5),

    # PHP
    (r'^\s*(<\?php|\$[a-z_]+\s*=|function .+\()', 'php', 0.7),
    (r'\$this->|->|echo |require_once', 'php', 0.5),

    # SQL
    (r'^\s*(SELECT |INSERT |UPDATE |DELETE |CREATE TABLE|ALTER TABLE)', 'sql', 0.8),
    (r'\bFROM\b|\bWHERE\b|\bJOIN\b|\bGROUP BY\b', 'sql', 0.5),

    # HTML
    (r'^\s*<!DOCTYPE|<html|<head|<body|<div', 'html', 0.7),
    (r'<[a-z]+[^>]*>.*</[a-z]+>', 'html', 0.4),

    # CSS (more specific to avoid false positives with comments)
    (r'^\s*(@media|@import|@keyframes|@font-face)', 'css', 0.7),
    (r'\{\s*(color|background|margin|padding|font-|display|position)\s*:', 'css', 0.6),
    (r'\.([\w-]+)\s*\{', 'css', 0.4),  # class selector with block

    # JSON
    (r'^\s*[\[{]', 'json', 0.3),
    (r'"[^"]+"\s*:\s*["\d\[\{]', 'json', 0.5),

    # YAML
    (r'^\s*[a-z_]+:\s*($|\n|["\'\d\[])', 'yaml', 0.5),
    (r'^\s*- [a-z_]+:', 'yaml', 0.4),

    # Bash/Shell
    (r'^\s*\$\s+\w', 'bash', 0.7),  # Shell prompt
    (r'^\s*(#!/bin/|if \[\[|for .+ in|while |export |echo \$)', 'bash', 0.7),
    (r'\$\{|\|\||&&|sudo |apt-get|apt |npm |pip |brew ', 'bash', 0.4),
    (r'cat |trafilatura |curl |wget ', 'bash', 0.5),

    # Markdown
    (r'^\s*(#{1,6} |```|\*\*|__|\[.+\]\(.+\))', 'markdown', 0.6),
]


def normalize_language(lang: str | None) -> str | None:
    """Normalize language name to canonical form."""
    if not lang:
        return None

    lang = lang.lower().strip()
    return LANGUAGE_ALIASES.get(lang, lang)


def detect_language_from_classes(tag: Tag) -> tuple[str | None, float]:
    """Detect language from class attribute."""
    classes = ' '.join(tag.get('class', []))
    if not classes:
        return None, 0.0

    for pattern, confidence in LANGUAGE_CLASS_PATTERNS:
        match = re.search(pattern, classes, re.I)
        if match:
            lang = match.group(1)
            return normalize_language(lang), confidence

    return None, 0.0


def detect_language_from_attrs(tag: Tag) -> tuple[str | None, float]:
    """Detect language from data attributes."""
    for attr in LANGUAGE_DATA_ATTRS:
        value = tag.get(attr)
        if value:
            return normalize_language(value), 1.0

    return None, 0.0


def detect_language_heuristic(code: str) -> tuple[str | None, float]:
    """Detect language using heuristic patterns."""
    if not code or len(code) < 10:
        return None, 0.0

    best_lang = None
    best_confidence = 0.0

    for pattern, lang, confidence in LANGUAGE_HEURISTICS:
        if re.search(pattern, code, re.MULTILINE | re.I):
            if confidence > best_confidence:
                best_lang = lang
                best_confidence = confidence

    return best_lang, best_confidence


def detect_language(tag: Tag, code: str) -> tuple[str | None, float]:
    """Detect language using all available signals."""
    # Check tag attributes first (highest confidence)
    lang, conf = detect_language_from_attrs(tag)
    if lang:
        return lang, conf

    # Check class names
    lang, conf = detect_language_from_classes(tag)
    if lang:
        return lang, conf

    # Check parent for class hints (common pattern: <pre class="lang"><code>)
    if tag.parent:
        lang, conf = detect_language_from_classes(tag.parent)
        if lang:
            return lang, conf

        # Check grandparent too
        if tag.parent.parent:
            lang, conf = detect_language_from_classes(tag.parent.parent)
            if lang:
                return lang, conf

    # Fall back to heuristics
    return detect_language_heuristic(code)


def is_inline_code(tag: Tag) -> bool:
    """Determine if code element is inline or block."""
    # <pre> is always block
    if tag.name == 'pre':
        return False

    # Check if inside <pre>
    if tag.find_parent('pre'):
        return False

    # Check display style
    style = tag.get('style', '')
    if 'display: block' in style or 'display:block' in style:
        return False

    # Single line = likely inline
    text = tag.get_text()
    if '\n' not in text and len(text) < 100:
        return True

    return False


def clean_code_content(text: str) -> tuple[str, bool]:
    """
    Clean code content and detect truncation.

    Returns:
        Tuple of (cleaned_text, is_truncated)
    """
    # Detect truncation markers
    is_truncated = bool(re.search(r'\.\.\.$|…$|# \.\.\.|// \.\.\.', text.strip()))

    # Strip common line number patterns
    lines = text.split('\n')
    cleaned_lines = []

    for line in lines:
        # Remove leading line numbers (common in copied code)
        # Pattern: "  123  actual code" or "123: actual code"
        cleaned = re.sub(r'^\s*\d+[\s:]+', '', line)
        cleaned_lines.append(cleaned)

    # Only use cleaned version if it changed significantly
    cleaned_text = '\n'.join(cleaned_lines)
    if len(cleaned_text) < len(text) * 0.5:
        # Too much removed, probably not line numbers
        cleaned_text = text

    return cleaned_text.strip(), is_truncated


def find_context_heading(tag: Tag) -> str | None:
    """Find the nearest heading for context."""
    for parent in tag.parents:
        if parent.name in ['article', 'section', 'div', 'main']:
            heading = parent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if heading:
                return heading.get_text(strip=True)

    for sibling in tag.find_all_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        text = sibling.get_text(strip=True)
        if text:
            return text

    return None


def find_context_text(tag: Tag, max_chars: int = 300) -> str | None:
    """Find preceding explanation text."""
    # Look for preceding paragraph
    for sibling in tag.find_all_previous(['p'], limit=3):
        text = sibling.get_text(strip=True)
        if text and len(text) > 30:
            return text[:max_chars]

    return None


def find_filename_hint(tag: Tag) -> str | None:
    """Look for filename hints in surrounding context."""
    # Check for filename in class or data attrs
    for attr in ['data-filename', 'data-file', 'data-path']:
        value = tag.get(attr)
        if value:
            return value

    # Check parent
    if tag.parent:
        for attr in ['data-filename', 'data-file', 'data-path']:
            value = tag.parent.get(attr)
            if value:
                return value

    # Look for code header pattern (common in docs)
    prev = tag.find_previous_sibling()
    if prev and prev.name in ['div', 'span', 'p']:
        text = prev.get_text(strip=True)
        # Pattern: "file.py" or "src/file.js"
        if re.match(r'^[\w./\\-]+\.\w+$', text) and len(text) < 50:
            return text

    return None


def extract_pre_blocks(soup: BeautifulSoup) -> list[CodeBlock]:
    """Extract code from <pre> blocks."""
    blocks = []

    for pre in soup.find_all('pre'):
        # Get code content - prefer nested <code> if present
        code_tag = pre.find('code')
        if code_tag:
            content = code_tag.get_text()
            lang_tag = code_tag
        else:
            content = pre.get_text()
            lang_tag = pre

        if not content.strip():
            continue

        content, is_truncated = clean_code_content(content)
        language, confidence = detect_language(lang_tag, content)

        blocks.append(CodeBlock(
            content=content,
            language=language,
            language_confidence=confidence,
            is_inline=False,
            is_truncated=is_truncated,
            context_heading=find_context_heading(pre),
            context_text=find_context_text(pre),
            filename_hint=find_filename_hint(pre),
            line_count=content.count('\n') + 1,
            char_count=len(content),
            source_tag='pre',
        ))

    return blocks


def extract_code_tags(soup: BeautifulSoup) -> list[CodeBlock]:
    """Extract code from standalone <code> tags (not in <pre>)."""
    blocks = []

    for code in soup.find_all('code'):
        # Skip if inside <pre> (handled separately)
        if code.find_parent('pre'):
            continue

        content = code.get_text()
        if not content.strip():
            continue

        is_inline = is_inline_code(code)

        # Skip very short inline code (likely just variable names)
        if is_inline and len(content) < 5:
            continue

        content, is_truncated = clean_code_content(content)
        language, confidence = detect_language(code, content)

        blocks.append(CodeBlock(
            content=content,
            language=language,
            language_confidence=confidence,
            is_inline=is_inline,
            is_truncated=is_truncated,
            context_heading=find_context_heading(code) if not is_inline else None,
            context_text=find_context_text(code) if not is_inline else None,
            filename_hint=find_filename_hint(code),
            line_count=content.count('\n') + 1,
            char_count=len(content),
            source_tag='code',
        ))

    return blocks


def extract_script_data(soup: BeautifulSoup) -> list[CodeBlock]:
    """Extract JSON/config data from <script> tags."""
    blocks = []

    for script in soup.find_all('script'):
        script_type = script.get('type', '')

        # Only extract data scripts, not executable JS
        if script_type in ['application/json', 'application/ld+json', 'text/template']:
            content = script.get_text().strip()
            if not content:
                continue

            blocks.append(CodeBlock(
                content=content,
                language='json' if 'json' in script_type else 'html',
                language_confidence=1.0,
                is_inline=False,
                is_config=True,
                line_count=content.count('\n') + 1,
                char_count=len(content),
                source_tag='script',
            ))

    return blocks


def extract_highlighted_blocks(soup: BeautifulSoup) -> list[CodeBlock]:
    """Extract code from syntax highlighter elements."""
    blocks = []

    # Common highlighter container classes
    highlighter_patterns = [
        r'highlight',
        r'syntax',
        r'code-block',
        r'sourceCode',
        r'blob-code',  # GitHub
        r'CodeMirror',
        r'ace_editor',
    ]

    for pattern in highlighter_patterns:
        for el in soup.find_all(class_=re.compile(pattern, re.I)):
            # Skip if already handled by pre/code extraction
            if el.name in ['pre', 'code']:
                continue
            if el.find_parent(['pre', 'code']):
                continue

            # Get text content
            content = el.get_text()
            if not content.strip() or len(content) < 10:
                continue

            # Check if this is a container that should be skipped
            if el.find('pre') or el.find('code'):
                continue  # Let pre/code extraction handle it

            content, is_truncated = clean_code_content(content)
            language, confidence = detect_language(el, content)

            blocks.append(CodeBlock(
                content=content,
                language=language,
                language_confidence=confidence,
                is_inline=False,
                is_truncated=is_truncated,
                context_heading=find_context_heading(el),
                context_text=find_context_text(el),
                filename_hint=find_filename_hint(el),
                line_count=content.count('\n') + 1,
                char_count=len(content),
                source_tag='highlight',
            ))

    return blocks


def extract_code(
    html: str,
    include_inline: bool = False,
    include_config: bool = False,
    min_block_chars: int = 20,
) -> list[CodeBlock]:
    """
    Extract all code blocks from HTML.

    Args:
        html: Raw HTML content
        include_inline: Whether to include inline code snippets
        include_config: Whether to include JSON config scripts
        min_block_chars: Minimum characters for a block to be included

    Returns:
        List of CodeBlock objects
    """
    soup = BeautifulSoup(html, 'lxml')

    blocks = []

    # Extract from different sources
    blocks.extend(extract_pre_blocks(soup))
    blocks.extend(extract_code_tags(soup))
    blocks.extend(extract_highlighted_blocks(soup))

    if include_config:
        blocks.extend(extract_script_data(soup))

    # Filter
    filtered = []
    for block in blocks:
        # Filter inline if not requested
        if block.is_inline and not include_inline:
            continue

        # Filter by minimum size
        if block.char_count < min_block_chars:
            continue

        filtered.append(block)

    # Dedupe by content hash
    seen = set()
    deduped = []
    for block in filtered:
        content_hash = hash(block.content)
        if content_hash not in seen:
            seen.add(content_hash)
            deduped.append(block)

    return deduped
