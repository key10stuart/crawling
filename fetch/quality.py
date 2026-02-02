"""
Quality checks and confidence scoring for extracted content.
"""

from typing import Literal
from .config import FetchConfig


# Common boilerplate patterns that indicate failed extraction
BOILERPLATE_PATTERNS = [
    'enable javascript',
    'javascript is required',
    'please enable cookies',
    'access denied',
    '403 forbidden',
    '404 not found',
    'page not found',
    'sorry, you have been blocked',
    'checking your browser',
    'just a moment',
    'attention required',
]


def calculate_link_density(text: str, link_text: str) -> float:
    """
    Calculate ratio of link text to total text.

    Args:
        text: Total extracted text
        link_text: Text that was inside links

    Returns:
        Link density ratio (0.0 to 1.0)
    """
    if not text:
        return 1.0
    return len(link_text) / (len(text) + 1)


def is_boilerplate(text: str) -> bool:
    """
    Check if text looks like boilerplate/error content.

    Args:
        text: Extracted text to check

    Returns:
        True if text matches boilerplate patterns
    """
    if not text:
        return True

    text_lower = text.lower()[:500]  # only check beginning

    for pattern in BOILERPLATE_PATTERNS:
        if pattern in text_lower:
            return True

    return False


def is_degenerate(text: str, title: str) -> bool:
    """
    Check if extraction is degenerate (title repeated, minimal content).

    Args:
        text: Extracted text
        title: Page title

    Returns:
        True if extraction looks degenerate
    """
    if not text:
        return True

    # Text is just the title repeated
    if title and text.strip() == title.strip():
        return True

    # Text is extremely short
    if len(text.strip()) < 20:
        return True

    return False


def check_quality(
    text: str,
    title: str = '',
    link_density: float = 0.0,
    config: FetchConfig | None = None,
) -> tuple[bool, str]:
    """
    Check if extraction meets quality thresholds.

    Args:
        text: Extracted text
        title: Page title
        link_density: Calculated link density
        config: Fetch configuration with thresholds

    Returns:
        Tuple of (passed, reason)
    """
    if config is None:
        config = FetchConfig()

    word_count = len(text.split()) if text else 0

    # Check word count
    if word_count < config.min_words:
        return False, f"word_count {word_count} < {config.min_words}"

    # Check link density
    if link_density > config.max_link_density:
        return False, f"link_density {link_density:.2f} > {config.max_link_density}"

    # Check boilerplate
    if is_boilerplate(text):
        return False, "matches boilerplate pattern"

    # Check degenerate
    if is_degenerate(text, title):
        return False, "degenerate extraction"

    return True, "passed"


def score_confidence(
    text: str,
    extract_method: str,
    link_density: float = 0.0,
    config: FetchConfig | None = None,
) -> Literal['high', 'medium', 'low']:
    """
    Assign confidence score to extraction.

    Args:
        text: Extracted text
        extract_method: Which extractor succeeded
        link_density: Calculated link density
        config: Fetch configuration with thresholds

    Returns:
        Confidence level: 'high', 'medium', or 'low'
    """
    if config is None:
        config = FetchConfig()

    word_count = len(text.split()) if text else 0

    # High confidence: good word count, low link density, primary extractor
    if (word_count >= config.confidence_high_words
            and link_density < 0.3
            and extract_method == 'trafilatura'):
        return 'high'

    # Medium confidence: decent word count, acceptable link density
    if (word_count >= config.confidence_low_words
            and link_density < config.max_link_density):
        return 'medium'

    # Low confidence: everything else
    return 'low'
