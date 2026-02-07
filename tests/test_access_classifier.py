"""
Tests for fetch/access_classifier.py (Div 4k1 Stream A).
"""

from datetime import datetime, timezone
from pathlib import Path

from fetch.access_classifier import classify_capture_result
from fetch.capture_config import CaptureResult


def _capture(tmp_path: Path, html: str | None = None, error: str | None = None) -> CaptureResult:
    html_path = None
    if html is not None:
        html_path = tmp_path / "page.html"
        html_path.write_text(html, encoding="utf-8")

    return CaptureResult(
        url="https://example.com/",
        final_url="https://example.com/",
        html_path=html_path,
        screenshot_path=None,
        asset_inventory=[],
        manifest_path=None,
        content_hash="abc123",
        captured_at=datetime.now(timezone.utc).isoformat(),
        fetch_method="requests",
        timing=None,
        headers={},
        cookies=[],
        html_size_bytes=len(html.encode("utf-8")) if html else 0,
        error=error,
    )


def test_classifies_soft_block_markers(tmp_path: Path):
    capture = _capture(
        tmp_path,
        html="<html><title>Your request has been blocked</title><body>Automated process detected</body></html>",
    )
    outcome = classify_capture_result(capture)
    assert outcome.outcome == "soft_block"
    assert outcome.reason == "soft_block_markers_detected"


def test_classifies_network_error(tmp_path: Path):
    capture = _capture(tmp_path, html=None, error="request_error: ConnectionError")
    outcome = classify_capture_result(capture)
    assert outcome.outcome == "network_error"


def test_classifies_success_with_extracted_words(tmp_path: Path):
    capture = _capture(tmp_path, html="<html><body><p>Hello world</p></body></html>")
    extraction = {"main_content": {"text": "hello " * 80, "word_count": 80, "method": "density"}}
    outcome = classify_capture_result(capture, extracted_page=extraction)
    assert outcome.outcome == "success_real_content"
    assert outcome.word_count_estimate == 80

