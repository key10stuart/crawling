"""
Interaction plan heuristics for interactive crawling.

Provides selectors and helpers for finding interactive UI elements
(accordions, tabs, carousels, load-more buttons) and detecting content changes.

This module defines the interface contract between the interaction plan
and the interactive fetch implementation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page, Locator


# =============================================================================
# Configuration
# =============================================================================

# Thresholds
DELTA_THRESHOLD = 20  # Minimum new words to count as improvement
MAX_INTERACTIONS = 6  # Total interaction budget per page
INTERACTIVE_MIN_WORDS = 100  # Below this, try interactive fetch
INTERACTION_TIMEOUT_MS = 3000  # Timeout per interaction
SETTLE_DELAY_MS = 500  # Wait for animations after click
INTERACTIVE_TIMEOUT_SEC = 30  # Max total time for all interactions

# =============================================================================
# Selectors
# =============================================================================

# Accordion / Expandable selectors (ordered by reliability)
ACCORDION_SELECTORS = [
    # ARIA (most reliable)
    '[aria-expanded="false"]',
    '[role="button"][aria-controls]',
    'button[aria-expanded="false"]',

    # Semantic HTML
    'details:not([open]) > summary',

    # Common class patterns
    '.accordion:not(.active) > .accordion-header',
    '.accordion-item:not(.active) > .accordion-trigger',
    '.collapse-trigger:not(.active)',
    '.expandable:not(.expanded) > .expandable-header',
    '[class*="accordion"]:not([class*="open"]):not([class*="active"]) > [class*="header"]',
    '[class*="collapsible"]:not([class*="open"]) > [class*="trigger"]',

    # FAQ patterns
    '.faq-question',
    '.faq-item:not(.active) > .faq-header',

    # Bootstrap 5
    '.accordion-button.collapsed',
    '[data-bs-toggle="collapse"]',

    # Trucking/recruiting content sections (often hidden in expandables)
    '[class*="benefits"]:not([class*="open"]) [class*="toggle"]',
    '[class*="requirement"]:not([class*="open"]) [class*="toggle"]',
    '[class*="compensation"]:not([class*="open"]) [class*="toggle"]',
    '[class*="pay"]:not([class*="open"]) [class*="toggle"]',
    '[class*="job"]:not([class*="open"]) [class*="toggle"]',

    # Material UI / MUI
    '[class*="MuiAccordion"]:not([class*="expanded"]) [class*="MuiAccordionSummary"]',
    '[class*="MuiExpansionPanel"]:not([class*="expanded"]) [class*="MuiExpansionPanelSummary"]',

    # Headless UI (React)
    '[data-headlessui-state=""] button',

    # AEM / Adobe Experience Manager (common on trucking sites)
    '.cmp-accordion__button[aria-expanded="false"]',
    '[class*="aem-accordion"] [class*="header"]:not([class*="active"])',
]

# Tab selectors
TAB_SELECTORS = [
    # ARIA (most reliable)
    '[role="tab"][aria-selected="false"]',
    '[role="tablist"] > [role="tab"]:not([aria-selected="true"])',

    # Common class patterns
    '.tab:not(.active)',
    '.tabs > .tab-item:not(.active)',
    '.tab-button:not(.active)',
    '[class*="tab"]:not([class*="active"]):not([class*="content"])',

    # Nav tabs (Bootstrap)
    '.nav-tabs > li:not(.active) > a',
    '.nav-tabs > .nav-item:not(.active) > .nav-link',

    # Bootstrap 5
    '[data-bs-toggle="tab"]:not(.active)',
    '.nav-link[data-bs-toggle="pill"]:not(.active)',

    # Trucking-specific content tabs
    '[class*="driver"]:not([class*="active"]) > [class*="tab"]',
    '[class*="owner-operator"]:not([class*="active"]) > [class*="tab"]',
    '[class*="carrier"]:not([class*="active"]) > [class*="tab"]',

    # Material UI
    '[class*="MuiTab-root"]:not([class*="selected"])',
    'button[class*="MuiTab"]:not([aria-selected="true"])',

    # Tailwind / DaisyUI
    '.tab-lifted:not(.tab-active)',
    'input[type="radio"][name*="tab"]:not(:checked) + label',

    # AEM tabs
    '.cmp-tabs__tab:not(.cmp-tabs__tab--active)',
    '[class*="aem-tabs"] [class*="tab"]:not([class*="active"])',

    # React Tab libraries
    '[class*="react-tabs"] [role="tab"]:not([aria-selected="true"])',
]

# Carousel / Slider selectors
CAROUSEL_SELECTORS = [
    # ARIA
    '[role="tablist"][aria-label*="slide"] [role="tab"]',

    # Next/prev buttons
    '.carousel-next',
    '.carousel-control-next',
    '.slider-next',
    '.swiper-button-next',
    '[class*="carousel"] [class*="next"]',
    '[class*="slider"] [class*="next"]',
    'button[aria-label*="next slide" i]',
    'button[aria-label*="next item" i]',

    # Dots/indicators (click to advance)
    '.carousel-indicators > li:not(.active)',
    '.carousel-dots > button:not(.active)',
    '.swiper-pagination-bullet:not(.swiper-pagination-bullet-active)',

    # Slick slider (very common)
    '.slick-next',
    '.slick-dots li:not(.slick-active) button',

    # Owl Carousel
    '.owl-next',
    '.owl-dot:not(.active)',

    # Splide
    '.splide__arrow--next',
    '.splide__pagination__page:not(.is-active)',

    # Bootstrap carousel
    '[data-bs-slide="next"]',
    '[data-slide="next"]',

    # Trucking testimonials/stories (often in carousels)
    '[class*="testimonial"] [class*="next"]',
    '[class*="story"] [class*="next"]',
    '[class*="driver-spotlight"] [class*="next"]',

    # Glide.js
    '[data-glide-dir=">"]',

    # AEM carousels
    '.cmp-carousel__action--next',
    '[class*="aem-carousel"] [class*="next"]',
]

# Load more / Show more selectors
LOAD_MORE_SELECTORS = [
    # ARIA
    'button[aria-label*="load more" i]',
    'button[aria-label*="show more" i]',

    # Text content (Playwright :has-text)
    'button:has-text("Load more")',
    'button:has-text("Show more")',
    'button:has-text("View more")',
    'button:has-text("See more")',
    'button:has-text("Read more")',
    'a:has-text("Load more")',
    'a:has-text("Show more")',

    # Class patterns
    '.load-more',
    '.show-more',
    '.view-more',
    '[class*="load-more"]',
    '[class*="show-more"]',

    # Job listing specific (trucking/recruiting)
    'button:has-text("View all jobs")',
    'button:has-text("See all positions")',
    'a:has-text("View all jobs")',
    'a:has-text("More opportunities")',
    'button:has-text("Show all locations")',

    # Infinite scroll triggers
    '[data-load-more]',
    '[data-infinite-scroll-trigger]',
    '[class*="infinite"] [class*="trigger"]',

    # React patterns
    '[class*="LoadMore"]',
    '[class*="loadMore"]',

    # Compensation/benefits reveal
    'button:has-text("View full benefits")',
    'button:has-text("See complete package")',
    'a:has-text("Full details")',
]

# Pagination (in-page, not navigation)
PAGINATION_SELECTORS = [
    # Next page buttons
    '.pagination .next:not(.disabled)',
    '.pagination-next:not(.disabled)',
    '[aria-label="Next page"]:not([disabled])',
    'a[rel="next"]',
]


# =============================================================================
# Element Finders
# =============================================================================

@dataclass
class InteractionTarget:
    """A UI element that can be interacted with."""
    locator: Locator
    interaction_type: str  # 'accordion', 'tab', 'carousel', 'load_more', 'pagination'
    selector_used: str


def find_expandables(page: Page, max_results: int = 5) -> list[InteractionTarget]:
    """
    Find accordion/details/collapse elements that are currently closed.

    Returns elements ordered by likelihood of containing useful content.
    """
    results = []

    for selector in ACCORDION_SELECTORS:
        try:
            locator = page.locator(selector)
            count = locator.count()
            for i in range(min(count, max_results - len(results))):
                el = locator.nth(i)
                if el.is_visible():
                    results.append(InteractionTarget(
                        locator=el,
                        interaction_type='accordion',
                        selector_used=selector,
                    ))
                if len(results) >= max_results:
                    return results
        except Exception:
            continue

    return results


def find_tabs(page: Page, max_results: int = 5) -> list[InteractionTarget]:
    """
    Find tab controls that are not currently active.
    """
    results = []

    for selector in TAB_SELECTORS:
        try:
            locator = page.locator(selector)
            count = locator.count()
            for i in range(min(count, max_results - len(results))):
                el = locator.nth(i)
                if el.is_visible():
                    results.append(InteractionTarget(
                        locator=el,
                        interaction_type='tab',
                        selector_used=selector,
                    ))
                if len(results) >= max_results:
                    return results
        except Exception:
            continue

    return results


def find_carousels(page: Page, max_results: int = 3) -> list[InteractionTarget]:
    """
    Find carousel/slider next buttons or indicators.
    """
    results = []

    for selector in CAROUSEL_SELECTORS:
        try:
            locator = page.locator(selector)
            count = locator.count()
            for i in range(min(count, max_results - len(results))):
                el = locator.nth(i)
                if el.is_visible():
                    results.append(InteractionTarget(
                        locator=el,
                        interaction_type='carousel',
                        selector_used=selector,
                    ))
                if len(results) >= max_results:
                    return results
        except Exception:
            continue

    return results


def find_load_more(page: Page, max_results: int = 2) -> list[InteractionTarget]:
    """
    Find 'load more' / 'show more' buttons.
    """
    results = []

    for selector in LOAD_MORE_SELECTORS:
        try:
            locator = page.locator(selector)
            count = locator.count()
            for i in range(min(count, max_results - len(results))):
                el = locator.nth(i)
                if el.is_visible():
                    results.append(InteractionTarget(
                        locator=el,
                        interaction_type='load_more',
                        selector_used=selector,
                    ))
                if len(results) >= max_results:
                    return results
        except Exception:
            continue

    return results


# Keywords that indicate compensation-related content (prioritize these elements)
COMP_KEYWORDS = [
    'pay', 'salary', 'wage', 'compensation', 'bonus', 'benefit',
    'cpm', 'per mile', 'hourly', 'annual', 'weekly',
    'sign-on', 'sign on', 'signing', 'retention',
    'insurance', 'medical', 'dental', 'vision', '401k',
    'home time', 'pto', 'vacation', 'holiday',
    'equipment', 'truck', 'trailer', 'fleet',
    'lease', 'owner operator', 'o/o', 'settlement',
    'fuel', 'surcharge', 'quick pay', 'fast pay',
]


def _is_comp_related(locator: Locator) -> bool:
    """Check if element text suggests compensation content."""
    try:
        text = locator.text_content() or ''
        text_lower = text.lower()
        return any(kw in text_lower for kw in COMP_KEYWORDS)
    except Exception:
        return False


def _sort_by_comp_relevance(targets: list[InteractionTarget]) -> list[InteractionTarget]:
    """Sort targets so comp-related ones come first."""
    comp_targets = []
    other_targets = []
    for t in targets:
        if _is_comp_related(t.locator):
            comp_targets.append(t)
        else:
            other_targets.append(t)
    return comp_targets + other_targets


def find_all_interactables(page: Page, prioritize_comp: bool = True) -> list[InteractionTarget]:
    """
    Find all interactable elements, prioritized by type.

    Priority order:
    1. Accordions (often hide substantial content)
    2. Tabs (reveal alternative content views)
    3. Load more (pagination)
    4. Carousels (usually less critical content)

    If prioritize_comp=True, elements with comp-related text are prioritized
    within each category.

    Returns at most MAX_INTERACTIONS targets.
    """
    targets = []
    remaining = MAX_INTERACTIONS

    # Accordions first (max 3)
    accordions = find_expandables(page, max_results=min(3, remaining))
    if prioritize_comp:
        accordions = _sort_by_comp_relevance(accordions)
    targets.extend(accordions)
    remaining -= len(accordions)

    if remaining <= 0:
        return targets

    # Tabs (max 2)
    tabs = find_tabs(page, max_results=min(2, remaining))
    if prioritize_comp:
        tabs = _sort_by_comp_relevance(tabs)
    targets.extend(tabs)
    remaining -= len(tabs)

    if remaining <= 0:
        return targets

    # Load more (max 1)
    load_more = find_load_more(page, max_results=min(1, remaining))
    targets.extend(load_more)
    remaining -= len(load_more)

    if remaining <= 0:
        return targets

    # Carousels (fill remaining)
    carousels = find_carousels(page, max_results=remaining)
    targets.extend(carousels)

    return targets


# =============================================================================
# Content Delta Detection
# =============================================================================

# Token regex (matches words across languages)
_TOKEN_RE = re.compile(r'\w+', re.UNICODE)


def tokenize(text: str) -> set[str]:
    """Extract word tokens from text."""
    return set(_TOKEN_RE.findall(text.lower())) if text else set()


def content_delta(before: str, after: str) -> int:
    """
    Calculate the number of new words in 'after' compared to 'before'.

    Returns:
        Number of words present in 'after' but not in 'before'.
    """
    before_tokens = tokenize(before)
    after_tokens = tokenize(after)
    new_tokens = after_tokens - before_tokens
    return len(new_tokens)


def content_improved(before: str, after: str, threshold: int = DELTA_THRESHOLD) -> bool:
    """
    Check if content meaningfully improved after an interaction.

    Returns True if at least `threshold` new words were added.
    """
    return content_delta(before, after) >= threshold


def extract_visible_text(page: Page) -> str:
    """
    Extract visible text content from the current page state.

    Uses innerText to get rendered text (excludes hidden elements).
    """
    try:
        return page.evaluate("document.body.innerText") or ""
    except Exception:
        return ""


# =============================================================================
# State Detection
# =============================================================================

def is_expanded(locator: Locator) -> bool:
    """
    Check if an element is already expanded.

    Looks at aria-expanded, open attribute, and common class patterns.
    """
    try:
        # Check aria-expanded
        aria = locator.get_attribute('aria-expanded')
        if aria is not None:
            return aria.lower() == 'true'

        # Check <details open>
        if locator.evaluate("el => el.tagName") == 'DETAILS':
            return locator.get_attribute('open') is not None

        # Check common expanded classes
        class_attr = locator.get_attribute('class') or ''
        expanded_patterns = ['active', 'open', 'expanded', 'show', 'visible']
        return any(p in class_attr.lower() for p in expanded_patterns)

    except Exception:
        return False


def is_tab_selected(locator: Locator) -> bool:
    """Check if a tab is currently selected."""
    try:
        aria = locator.get_attribute('aria-selected')
        if aria is not None:
            return aria.lower() == 'true'

        class_attr = locator.get_attribute('class') or ''
        return 'active' in class_attr.lower() or 'selected' in class_attr.lower()

    except Exception:
        return False


# =============================================================================
# Interaction Helpers
# =============================================================================

def safe_click(locator: Locator, timeout_ms: int = INTERACTION_TIMEOUT_MS) -> bool:
    """
    Safely click an element with timeout handling.

    Returns True if click succeeded, False otherwise.
    """
    try:
        locator.click(timeout=timeout_ms)
        return True
    except Exception:
        return False


def wait_for_settle(page: Page, delay_ms: int = SETTLE_DELAY_MS) -> None:
    """Wait for animations to settle after an interaction."""
    page.wait_for_timeout(delay_ms)
