"""
Lazy content expansion for Div 4i capture.

Handles:
- Scrolling to bottom to trigger lazy-loaded content
- Clicking accordions/expandables to reveal hidden content
- Waiting for dynamic content to load
"""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

from .capture_config import CaptureConfig


def scroll_to_bottom(page: "Page", config: CaptureConfig) -> int:
    """
    Scroll page to bottom to trigger lazy loading.

    Scrolls incrementally, pausing to let content load.
    Returns number of scroll steps taken.

    Args:
        page: Playwright page object
        config: Capture configuration

    Returns:
        Number of scroll steps performed
    """
    if not config.scroll_to_bottom:
        return 0

    steps = 0
    last_height = 0
    stable_count = 0
    max_stable = 3  # Stop after height unchanged 3 times

    while stable_count < max_stable:
        # Get current scroll height
        current_height = page.evaluate("document.body.scrollHeight")

        if current_height == last_height:
            stable_count += 1
        else:
            stable_count = 0
            last_height = current_height

        # Scroll down by viewport height
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        steps += 1

        # Pause for content to load
        time.sleep(config.scroll_pause_ms / 1000)

        # Safety limit
        if steps > 50:
            break

    # Scroll back to top
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.2)

    return steps


def expand_accordions(page: "Page", config: CaptureConfig) -> tuple[int, list[dict]]:
    """
    Click accordion/expandable elements to reveal content.

    Args:
        page: Playwright page object
        config: Capture configuration

    Returns:
        Number of elements expanded
    """
    if not config.click_accordions:
        return 0

    expanded_count = 0
    selector_counts: list[dict] = []

    for selector in config.accordion_selectors:
        selector_count = 0
        try:
            elements = page.query_selector_all(selector)

            for element in elements:
                try:
                    # Check if visible and clickable
                    if not element.is_visible():
                        continue

                    # Special handling for <details> elements
                    tag_name = element.evaluate("el => el.tagName.toLowerCase()")
                    if tag_name == 'summary':
                        # Check if parent details is already open
                        is_open = element.evaluate(
                            "el => el.closest('details')?.hasAttribute('open')"
                        )
                        if is_open:
                            continue

                    # Check aria-expanded if present
                    aria_expanded = element.get_attribute('aria-expanded')
                    if aria_expanded == 'true':
                        continue

                    # Click to expand
                    element.click(timeout=1000)
                    expanded_count += 1
                    selector_count += 1

                    # Brief pause for animation/content
                    time.sleep(0.3)

                except Exception:
                    # Element might have become stale or unclickable
                    continue

        except Exception:
            # Selector might not match anything
            continue

        if selector_count:
            selector_counts.append({
                "action": "accordion",
                "selector": selector,
                "count": selector_count,
            })

    return expanded_count, selector_counts


def expand_tabs(page: "Page") -> tuple[int, list[dict]]:
    """
    Click through tab panels to capture all tab content.

    Args:
        page: Playwright page object

    Returns:
        Number of tabs clicked
    """
    tab_selectors = [
        '[role="tab"]:not([aria-selected="true"])',
        '.nav-tabs .nav-link:not(.active)',
        '.tab-button:not(.active)',
        '[data-toggle="tab"]:not(.active)',
    ]

    clicked = 0
    selector_counts: list[dict] = []

    for selector in tab_selectors:
        try:
            tabs = page.query_selector_all(selector)
            selector_count = 0
            for tab in tabs:
                try:
                    if tab.is_visible():
                        tab.click(timeout=1000)
                        clicked += 1
                        selector_count += 1
                        time.sleep(0.3)
                except Exception:
                    continue
        except Exception:
            continue
        if selector_count:
            selector_counts.append({
                "action": "tab",
                "selector": selector,
                "count": selector_count,
            })

    return clicked, selector_counts


def wait_for_lazy_content(page: "Page", config: CaptureConfig) -> None:
    """
    Wait for lazy content to finish loading.

    Waits for:
    - Network to be idle
    - No pending image loads
    - Custom wait time

    Args:
        page: Playwright page object
        config: Capture configuration
    """
    # Wait for network idle (with timeout)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass  # Timeout is OK, some sites never go idle

    # Wait for images to load
    try:
        page.evaluate("""
            () => {
                return Promise.all(
                    Array.from(document.images)
                        .filter(img => !img.complete)
                        .map(img => new Promise(resolve => {
                            img.onload = img.onerror = resolve;
                        }))
                );
            }
        """)
    except Exception:
        pass

    # Final configurable wait
    if config.wait_after_expansion_ms > 0:
        time.sleep(config.wait_after_expansion_ms / 1000)


def expand_all(page: "Page", config: CaptureConfig) -> dict:
    """
    Perform all expansion operations.

    Args:
        page: Playwright page object
        config: Capture configuration

    Returns:
        Dict with expansion stats
    """
    stats = {
        "scroll_steps": 0,
        "accordions_expanded": 0,
        "tabs_clicked": 0,
    }
    interaction_log: list[dict] = []

    if not config.expand_lazy_content:
        return stats

    # Scroll first to trigger lazy images
    stats["scroll_steps"] = scroll_to_bottom(page, config)
    interaction_log.append({"action": "scroll", "steps": stats["scroll_steps"]})

    # Expand accordions
    accordions_expanded, accordion_log = expand_accordions(page, config)
    stats["accordions_expanded"] = accordions_expanded
    interaction_log.extend(accordion_log)

    # Click through tabs
    tabs_clicked, tab_log = expand_tabs(page)
    stats["tabs_clicked"] = tabs_clicked
    interaction_log.extend(tab_log)

    # Wait for everything to settle
    wait_for_lazy_content(page, config)
    if config.wait_after_expansion_ms:
        interaction_log.append({
            "action": "wait",
            "wait_after_expansion_ms": config.wait_after_expansion_ms,
        })

    return {
        "stats": stats,
        "interaction_log": interaction_log,
    }
