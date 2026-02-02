"""
Interactive fetch layer (Playwright agent).

Runs a bounded, ordered interaction plan to reveal JS-hidden content
when baseline extraction quality is low.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from .config import FetchConfig, FetchResult
from .extractor import extract_content
from .fetcher import fetch_html
from .hasher import hash_content, hash_html
from .images import extract_images
from .code import extract_code
from .quality import check_quality, score_confidence
from .interaction_plan import (
    find_all_interactables,
    content_improved,
    extract_visible_text,
    is_expanded,
    is_tab_selected,
    safe_click,
    DELTA_THRESHOLD,
    MAX_INTERACTIONS,
    INTERACTIVE_TIMEOUT_SEC,
    INTERACTION_TIMEOUT_MS,
    SETTLE_DELAY_MS,
)


def _ensure_return_html(config: FetchConfig) -> FetchConfig:
    if config.return_html:
        return config
    return replace(config, return_html=True)


def _best_from_html(html: str, url: str, config: FetchConfig) -> dict[str, Any]:
    extraction = extract_content(html, config)
    confidence = score_confidence(
        extraction.text,
        extraction.method,
        extraction.link_density,
        config,
    )
    return {
        "html": html,
        "text": extraction.text,
        "title": extraction.title,
        "author": extraction.author,
        "date": extraction.date,
        "method": extraction.method,
        "link_density": extraction.link_density,
        "word_count": len(extraction.text.split()) if extraction.text else 0,
        "confidence": confidence,
        "url": url,
    }


def _should_interact(html: str, url: str, config: FetchConfig) -> bool:
    extraction = extract_content(html, config)
    passed, _ = check_quality(extraction.text, extraction.title, extraction.link_density, config)
    return not passed


def _click_targets(page, targets, config: FetchConfig, log: list[dict], max_interactions: int) -> dict[str, Any] | None:
    best = None
    interactions = 0
    for target in targets:
        if interactions >= max_interactions:
            break

        if target.interaction_type == 'accordion' and is_expanded(target.locator):
            continue
        if target.interaction_type == 'tab' and is_tab_selected(target.locator):
            continue

        before_text = extract_visible_text(page)
        ok = safe_click(target.locator, timeout_ms=INTERACTION_TIMEOUT_MS)
        page.wait_for_timeout(SETTLE_DELAY_MS)
        after_text = extract_visible_text(page)

        log.append({
            "action": "click",
            "type": target.interaction_type,
            "selector": target.selector_used,
            "ok": ok,
        })
        interactions += 1

        if not ok:
            continue

        if not content_improved(before_text, after_text, threshold=DELTA_THRESHOLD):
            continue

        candidate = _best_from_html(page.content(), page.url, config)
        if best is None or candidate["word_count"] > best["word_count"]:
            best = candidate
    return best


def interactive_fetch(
    url: str,
    config: FetchConfig | None = None,
    max_interactions: int = MAX_INTERACTIONS,
    delta_threshold: int = DELTA_THRESHOLD,
    timeout_sec: int = INTERACTIVE_TIMEOUT_SEC,
) -> FetchResult | None:
    """
    Fetch a URL with optional Playwright interactions.

    Returns the best extraction seen (baseline or interactive).
    """
    if config is None:
        config = FetchConfig()
    config = _ensure_return_html(config)

    baseline = None
    html, final_url, fetch_method, status_code, response_headers, not_modified = fetch_html(url, config)

    if html:
        baseline = _best_from_html(html, final_url or url, config)
        if not _should_interact(html, final_url or url, config):
            return _result_from_best(baseline, fetch_method, config)

    # If Playwright isn't available, return baseline
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        if baseline:
            return _result_from_best(baseline, fetch_method, config)
        return FetchResult(url=url, final_url=url, content_hash="", fetch_time=time.strftime("%Y-%m-%dT%H:%M:%SZ"), fetch_method=fetch_method, extract_method="none", confidence="low", error="fetch_failed")

    # Interactive session
    start = time.time()
    interaction_log: list[dict] = []
    best = baseline

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=config.user_agent or None)
            page = context.new_page()
            try:
                page.goto(url, wait_until=config.js_wait_until, timeout=config.js_render_timeout_ms)
            except Exception as exc:
                interaction_log.append({
                    "action": "goto",
                    "wait_until": config.js_wait_until,
                    "result": f"error:{type(exc).__name__}",
                })
                page.goto(url, wait_until="domcontentloaded", timeout=config.js_render_timeout_ms)
                page.wait_for_timeout(SETTLE_DELAY_MS)

            # Snapshot after initial render
            rendered_html = page.content()
            candidate = _best_from_html(rendered_html, page.url, config)
            if best is None or candidate["word_count"] > best["word_count"]:
                best = candidate

            # Interaction plan: accordions, tabs, load-more, carousels (ordered)
            if time.time() - start < timeout_sec:
                targets = find_all_interactables(page)
                interaction_log.append({"action": "targets", "count": len(targets)})
                candidate = _click_targets(page, targets, config, interaction_log, max_interactions)
                if candidate and (best is None or candidate["word_count"] > best["word_count"]):
                    if candidate["word_count"] - (best["word_count"] if best else 0) >= delta_threshold:
                        best = candidate

            page.close()
            context.close()
            browser.close()
    except Exception as e:
        import sys
        interaction_log.append({"action": "interactive_error", "result": f"error:{type(e).__name__}"})
        print(f"[interactive] error: {e}", file=sys.stderr)

    if best:
        return _result_from_best(best, fetch_method, config, interaction_log=interaction_log)

    return FetchResult(
        url=url,
        final_url=final_url or url,
        content_hash="",
        fetch_time=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        fetch_method=fetch_method,
        extract_method="none",
        confidence="low",
        error="fetch_failed",
    )


def _result_from_best(best: dict[str, Any], fetch_method: str, config: FetchConfig, interaction_log: list[dict] | None = None) -> FetchResult:
    html = best["html"]
    text = best["text"]

    images = []
    code_blocks = []
    if config.extract_images:
        images = extract_images(html, best["url"], include_decorative=config.include_decorative_images)
    if config.extract_code:
        code_blocks = extract_code(
            html,
            include_inline=config.include_inline_code,
            include_config=config.include_config_code,
            min_block_chars=config.min_code_block_chars,
        )

    return FetchResult(
        url=best["url"],
        final_url=best["url"],
        content_hash=hash_content(text) if text else "",
        fetch_time=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        publish_date=best.get("date"),
        fetch_method=fetch_method,
        extract_method=best.get("method", "none"),
        confidence=best.get("confidence", "low"),
        title=best.get("title", ""),
        author=best.get("author"),
        text=text or "",
        word_count=best.get("word_count", 0),
        images=images,
        code_blocks=code_blocks,
        raw_html_hash=hash_html(html) if html else "",
        raw_html=html if config.return_html else None,
        error=None,
        interaction_log=interaction_log or [],
    )
