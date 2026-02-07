"""
Access outcome classification for capture attempts.

This module is intentionally side-effect free so policy/escalation can consume
the same outcome model without changing crawl behavior.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .capture_config import AccessOutcome, CaptureResult


CHALLENGE_MARKERS = [
    "checking your browser",
    "checking the site connection security",
    "just a moment",
    "cf-browser-verification",
    "captcha",
    "sg-captcha",
    "challenge",
]

SOFT_BLOCK_MARKERS = [
    "your request has been blocked",
    "request has been blocked",
    "request blocked",
    "access denied",
    "forbidden",
    "unusual traffic",
    "automated process",
    "security check",
    "bot detected",
]


def _read_html_excerpt(path: Path | None, max_chars: int = 250_000) -> str:
    if not path:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def _status_from_headers(headers: dict | None) -> int | None:
    if not headers:
        return None
    for key in ("status", ":status", "x-http-status", "x-status-code"):
        value = headers.get(key) or headers.get(key.title()) or headers.get(key.upper())
        if value is None:
            continue
        try:
            return int(str(value).split()[0])
        except Exception:
            continue
    return None


def _extract_word_count(extracted_page: dict | None) -> int:
    if not extracted_page:
        return 0
    main = extracted_page.get("main_content")
    if isinstance(main, dict):
        wc = main.get("word_count")
        if isinstance(wc, int):
            return wc
        text = main.get("text") or ""
        return len(text.split())
    if isinstance(main, str):
        return len(main.split())
    return 0


def _marker_hits(html: str, markers: list[str]) -> list[str]:
    lower = html.lower()
    return [m for m in markers if m in lower]


def classify_capture_result(
    capture: CaptureResult,
    extracted_page: dict | None = None,
    recon: object | None = None,
) -> AccessOutcome:
    """Classify a capture result into an explicit access outcome."""
    if capture.error:
        err = capture.error.lower()
        if "timeout" in err:
            return AccessOutcome(outcome="timeout", reason="capture_timeout", final_url=capture.final_url)
        if "not_html" in err:
            return AccessOutcome(outcome="non_html", reason="non_html_response", final_url=capture.final_url)
        if "request_error" in err or "navigation_failed" in err:
            return AccessOutcome(outcome="network_error", reason="network_or_navigation_error", final_url=capture.final_url)
        return AccessOutcome(outcome="unknown_failure", reason="capture_error", final_url=capture.final_url)

    status = _status_from_headers(capture.headers)
    if status in (403, 429, 451):
        return AccessOutcome(
            outcome="hard_block",
            reason="hard_block_status",
            http_status=status,
            final_url=capture.final_url,
        )

    html = _read_html_excerpt(capture.html_path)
    challenge_hits = _marker_hits(html, CHALLENGE_MARKERS)
    soft_block_hits = _marker_hits(html, SOFT_BLOCK_MARKERS)

    waf_hint = None
    if recon is not None:
        waf_hint = getattr(recon, "waf", None) or (recon.get("waf") if isinstance(recon, dict) else None)

    word_count = _extract_word_count(extracted_page)
    if challenge_hits:
        return AccessOutcome(
            outcome="challenge_not_cleared",
            reason="challenge_markers_detected",
            http_status=status,
            detected_markers=challenge_hits,
            waf_hint=waf_hint,
            challenge_detected=True,
            word_count_estimate=word_count,
            final_url=capture.final_url,
        )
    if soft_block_hits:
        return AccessOutcome(
            outcome="soft_block",
            reason="soft_block_markers_detected",
            http_status=status,
            detected_markers=soft_block_hits,
            waf_hint=waf_hint,
            challenge_detected=False,
            word_count_estimate=word_count,
            final_url=capture.final_url,
        )

    if word_count and word_count < 30 and capture.html_size_bytes > 5000:
        return AccessOutcome(
            outcome="thin_content",
            reason="very_low_extracted_words",
            http_status=status,
            waf_hint=waf_hint,
            word_count_estimate=word_count,
            final_url=capture.final_url,
        )

    return AccessOutcome(
        outcome="success_real_content",
        reason="content_captured",
        http_status=status,
        waf_hint=waf_hint,
        word_count_estimate=word_count,
        final_url=capture.final_url,
    )


def summarize_outcomes(captures: list[CaptureResult]) -> dict[str, int]:
    counts = Counter()
    for capture in captures:
        if capture.access_outcome:
            counts[capture.access_outcome.outcome] += 1
        elif capture.error:
            counts["unknown_failure"] += 1
    return dict(counts)


def outcome_as_dict(outcome: AccessOutcome | None) -> dict | None:
    return asdict(outcome) if outcome else None
