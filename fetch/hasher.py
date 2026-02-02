"""
Content hashing utilities for citation stability.
"""

import hashlib


def hash_content(text: str, length: int = 16) -> str:
    """
    Hash text content for identity/stability tracking.

    Args:
        text: The text to hash
        length: Length of returned hash (default 16 chars)

    Returns:
        Truncated SHA-256 hex digest
    """
    return hashlib.sha256(text.encode('utf-8', errors='replace')).hexdigest()[:length]


def hash_html(html: str, length: int = 16) -> str:
    """
    Hash raw HTML for detecting source changes.

    Args:
        html: The HTML to hash
        length: Length of returned hash (default 16 chars)

    Returns:
        Truncated SHA-256 hex digest
    """
    return hashlib.sha256(html.encode('utf-8', errors='replace')).hexdigest()[:length]
