"""
Tests for fetch/capture.py - Div 4i capture pipeline.
"""

import json
import tempfile
from pathlib import Path

import pytest

from fetch.capture import (
    hash_content,
    url_to_filename,
    parse_image_dimensions,
    inventory_assets,
    write_manifest,
)
from fetch.capture_config import (
    AccessAttempt,
    AccessOutcome,
    AssetRef,
    CaptureConfig,
    CaptureResult,
)


class TestHashContent:
    """Tests for hash_content function."""

    def test_basic_hash(self):
        """Hash should be 16 chars."""
        result = hash_content("Hello, world!")
        assert len(result) == 16
        assert result.isalnum()

    def test_consistent_hash(self):
        """Same input should produce same hash."""
        content = "Test content for hashing"
        assert hash_content(content) == hash_content(content)

    def test_different_content_different_hash(self):
        """Different content should produce different hashes."""
        assert hash_content("Content A") != hash_content("Content B")

    def test_empty_string(self):
        """Empty string should produce valid hash."""
        result = hash_content("")
        assert len(result) == 16


class TestUrlToFilename:
    """Tests for url_to_filename function."""

    def test_homepage(self):
        """Homepage should become index.html."""
        assert url_to_filename("https://example.com/") == "index.html"
        assert url_to_filename("https://example.com") == "index.html"

    def test_simple_path(self):
        """Simple path should convert cleanly."""
        assert url_to_filename("https://example.com/about") == "about.html"
        assert url_to_filename("https://example.com/contact/") == "contact.html"

    def test_nested_path(self):
        """Nested paths should use underscores."""
        result = url_to_filename("https://example.com/services/trucking")
        assert result == "services_trucking.html"

    def test_html_extension_stripped(self):
        """Existing .html extension should be handled."""
        result = url_to_filename("https://example.com/page.html")
        assert result == "page.html"
        assert not result.endswith(".html.html")

    def test_unsafe_chars_removed(self):
        """Unsafe filename chars should be removed."""
        result = url_to_filename("https://example.com/page?query=value")
        assert "?" not in result
        assert "<" not in result
        assert ">" not in result

    def test_long_path_truncated(self):
        """Very long paths should be truncated."""
        long_path = "a" * 300
        result = url_to_filename(f"https://example.com/{long_path}")
        assert len(result) <= 205  # 200 + .html


class TestParseImageDimensions:
    """Tests for parse_image_dimensions function."""

    def test_both_dimensions(self):
        """Should extract both width and height."""
        class MockTag:
            def get(self, attr):
                return {"width": "800", "height": "600"}.get(attr)

        result = parse_image_dimensions(MockTag())
        assert result == (800, 600)

    def test_missing_width(self):
        """Missing width should return None."""
        class MockTag:
            def get(self, attr):
                return {"height": "600"}.get(attr)

        assert parse_image_dimensions(MockTag()) is None

    def test_missing_height(self):
        """Missing height should return None."""
        class MockTag:
            def get(self, attr):
                return {"width": "800"}.get(attr)

        assert parse_image_dimensions(MockTag()) is None

    def test_dimensions_with_px(self):
        """Should handle px suffix."""
        class MockTag:
            def get(self, attr):
                return {"width": "800px", "height": "600px"}.get(attr)

        result = parse_image_dimensions(MockTag())
        assert result == (800, 600)

    def test_invalid_dimensions(self):
        """Invalid dimensions should return None."""
        class MockTag:
            def get(self, attr):
                return {"width": "auto", "height": "auto"}.get(attr)

        assert parse_image_dimensions(MockTag()) is None


class TestInventoryAssets:
    """Tests for inventory_assets function."""

    def test_finds_images(self):
        """Should find img tags."""
        html = '''
        <html>
        <body>
            <img src="/images/photo.jpg" alt="A photo">
            <img src="/images/logo.png" alt="Logo">
        </body>
        </html>
        '''
        assets = inventory_assets(html, "https://example.com/page")

        images = [a for a in assets if a.asset_type == 'image']
        assert len(images) == 2
        assert any("photo.jpg" in a.url for a in images)
        assert any("logo.png" in a.url for a in images)

    def test_finds_lazy_loaded_images(self):
        """Should find data-src images when src is missing."""
        html = '''
        <html>
        <body>
            <img data-src="/images/lazy.jpg">
        </body>
        </html>
        '''
        assets = inventory_assets(html, "https://example.com/")

        images = [a for a in assets if a.asset_type == 'image']
        assert any("lazy.jpg" in a.url for a in images)

    def test_finds_pdf_documents(self):
        """Should find PDF links."""
        html = '''
        <html>
        <body>
            <a href="/docs/report.pdf">Download Report</a>
            <a href="/files/contract.docx">Contract</a>
        </body>
        </html>
        '''
        assets = inventory_assets(html, "https://example.com/")

        docs = [a for a in assets if a.asset_type == 'document']
        assert len(docs) == 2
        assert any("report.pdf" in a.url for a in docs)
        assert any("contract.docx" in a.url for a in docs)

    def test_finds_videos(self):
        """Should find video elements."""
        html = '''
        <html>
        <body>
            <video src="/videos/intro.mp4" poster="/images/poster.jpg"></video>
        </body>
        </html>
        '''
        assets = inventory_assets(html, "https://example.com/")

        videos = [a for a in assets if a.asset_type == 'video']
        assert len(videos) == 1
        assert "intro.mp4" in videos[0].url

    def test_resolves_relative_urls(self):
        """Should resolve relative URLs to absolute."""
        html = '<img src="/images/photo.jpg">'
        assets = inventory_assets(html, "https://example.com/page/")

        assert len(assets) == 1
        assert assets[0].url == "https://example.com/images/photo.jpg"

    def test_skips_data_urls(self):
        """Should skip data: URLs."""
        html = '<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">'
        assets = inventory_assets(html, "https://example.com/")

        assert len(assets) == 0

    def test_deduplicates_assets(self):
        """Should not duplicate same URL."""
        html = '''
        <img src="/logo.png">
        <img src="/logo.png">
        '''
        assets = inventory_assets(html, "https://example.com/")

        assert len(assets) == 1

    def test_extracts_alt_text(self):
        """Should capture alt text for images."""
        html = '<img src="/photo.jpg" alt="Beautiful sunset">'
        assets = inventory_assets(html, "https://example.com/")

        assert assets[0].alt_text == "Beautiful sunset"

    def test_extracts_link_text(self):
        """Should capture link text for documents."""
        html = '<a href="/report.pdf">Annual Report 2024</a>'
        assets = inventory_assets(html, "https://example.com/")

        assert assets[0].link_text == "Annual Report 2024"


class TestWriteManifest:
    """Tests for write_manifest function."""

    def test_writes_manifest_file(self):
        """Should create manifest.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            domain = "example.com"

            # Create mock captures
            pages_dir = archive_dir / domain / "pages"
            pages_dir.mkdir(parents=True)
            html_path = pages_dir / "index.html"
            html_path.write_text("<html></html>")

            captures = [
                CaptureResult(
                    url="https://example.com/",
                    final_url="https://example.com/",
                    html_path=html_path,
                    screenshot_path=None,
                    asset_inventory=[
                        AssetRef(url="https://example.com/logo.png", asset_type="image"),
                    ],
                    manifest_path=archive_dir / domain / "manifest.json",
                    content_hash="abc123",
                    captured_at="2024-01-01T00:00:00Z",
                    fetch_method="requests",
                    timing=None,
                    headers={},
                    cookies=[],
                    html_size_bytes=100,
                    error=None,
                ),
            ]

            manifest_path = write_manifest(domain, archive_dir, captures)

            assert manifest_path.exists()
            with open(manifest_path) as f:
                data = json.load(f)

            assert data["domain"] == domain
            assert data["corpus_version"] == 2
            assert len(data["pages"]) == 1
            assert len(data["assets"]) == 1

    def test_aggregates_assets_across_pages(self):
        """Should aggregate assets from multiple pages."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            domain = "example.com"

            pages_dir = archive_dir / domain / "pages"
            pages_dir.mkdir(parents=True)

            captures = []
            for i, page_name in enumerate(["index", "about"]):
                html_path = pages_dir / f"{page_name}.html"
                html_path.write_text("<html></html>")

                captures.append(
                    CaptureResult(
                        url=f"https://example.com/{page_name}",
                        final_url=f"https://example.com/{page_name}",
                        html_path=html_path,
                        screenshot_path=None,
                        asset_inventory=[
                            AssetRef(url="https://example.com/shared.png", asset_type="image"),
                            AssetRef(url=f"https://example.com/{page_name}.png", asset_type="image"),
                        ],
                        manifest_path=archive_dir / domain / "manifest.json",
                        content_hash=f"hash{i}",
                        captured_at="2024-01-01T00:00:00Z",
                        fetch_method="requests",
                        timing=None,
                        headers={},
                        cookies=[],
                        html_size_bytes=100,
                        error=None,
                    )
                )

            manifest_path = write_manifest(domain, archive_dir, captures)

            with open(manifest_path) as f:
                data = json.load(f)

            # shared.png appears on both pages, should be deduplicated
            # but track found_on for both
            assert len(data["assets"]) == 3  # shared + index + about

    def test_stats_calculation(self):
        """Should calculate correct stats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            domain = "example.com"

            pages_dir = archive_dir / domain / "pages"
            pages_dir.mkdir(parents=True)
            html_path = pages_dir / "index.html"
            html_path.write_text("<html></html>")

            captures = [
                CaptureResult(
                    url="https://example.com/",
                    final_url="https://example.com/",
                    html_path=html_path,
                    screenshot_path=None,
                    asset_inventory=[
                        AssetRef(url="https://example.com/img1.png", asset_type="image"),
                        AssetRef(url="https://example.com/img2.png", asset_type="image"),
                        AssetRef(url="https://example.com/doc.pdf", asset_type="document"),
                    ],
                    manifest_path=archive_dir / domain / "manifest.json",
                    content_hash="abc123",
                    captured_at="2024-01-01T00:00:00Z",
                    fetch_method="requests",
                    timing=None,
                    headers={},
                    cookies=[],
                    html_size_bytes=2048,
                    error=None,
                ),
            ]

            manifest_path = write_manifest(domain, archive_dir, captures)

            with open(manifest_path) as f:
                data = json.load(f)

            assert data["stats"]["pages"] == 1
            assert data["stats"]["images"] == 2
            assert data["stats"]["documents"] == 1
            assert data["stats"]["total_html_kb"] == 2  # 2048 bytes = 2 KB

    def test_handles_redirected_subdomain_paths(self):
        """Should not crash when capture files land under a different host folder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            domain = "cloud.google.com"

            # Simulate redirect from cloud.google.com -> docs.cloud.google.com
            pages_dir = archive_dir / "docs.cloud.google.com" / "pages"
            pages_dir.mkdir(parents=True)
            html_path = pages_dir / "overview.html"
            html_path.write_text("<html></html>")

            captures = [
                CaptureResult(
                    url="https://cloud.google.com/",
                    final_url="https://docs.cloud.google.com/",
                    html_path=html_path,
                    screenshot_path=None,
                    asset_inventory=[
                        AssetRef(url="https://docs.cloud.google.com/logo.png", asset_type="image"),
                    ],
                    manifest_path=archive_dir / domain / "manifest.json",
                    content_hash="abc123",
                    captured_at="2024-01-01T00:00:00Z",
                    fetch_method="requests",
                    timing=None,
                    headers={},
                    cookies=[],
                    html_size_bytes=100,
                    error=None,
                ),
            ]

            manifest_path = write_manifest(domain, archive_dir, captures)
            with open(manifest_path) as f:
                data = json.load(f)

            assert len(data["pages"]) == 1
            assert data["pages"][0]["html_path"] == "docs.cloud.google.com/pages/overview.html"
            assert data["assets"][0]["found_on"] == ["docs.cloud.google.com/pages/overview.html"]

    def test_manifest_includes_access_outcomes_and_attempts(self):
        """Should persist per-page access outcome and attempt telemetry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            domain = "example.com"

            pages_dir = archive_dir / domain / "pages"
            pages_dir.mkdir(parents=True)
            html_path = pages_dir / "index.html"
            html_path.write_text("<html></html>")

            outcome = AccessOutcome(
                outcome="success_real_content",
                reason="content_captured",
                http_status=200,
                word_count_estimate=12,
                final_url="https://example.com/",
            )
            attempt = AccessAttempt(
                attempt_index=1,
                strategy="requests",
                started_at="2024-01-01T00:00:00Z",
                duration_ms=100,
                outcome=outcome,
                capture_error=None,
                html_size_bytes=100,
            )

            captures = [
                CaptureResult(
                    url="https://example.com/",
                    final_url="https://example.com/",
                    html_path=html_path,
                    screenshot_path=None,
                    asset_inventory=[],
                    manifest_path=archive_dir / domain / "manifest.json",
                    content_hash="abc123",
                    captured_at="2024-01-01T00:00:00Z",
                    fetch_method="requests",
                    timing=None,
                    headers={},
                    cookies=[],
                    html_size_bytes=100,
                    error=None,
                    access_outcome=outcome,
                    attempts=[attempt],
                ),
            ]

            manifest_path = write_manifest(domain, archive_dir, captures)
            data = json.loads(manifest_path.read_text())
            page = data["pages"][0]

            assert page["final_access_outcome"]["outcome"] == "success_real_content"
            assert page["attempts"][0]["strategy"] == "requests"


class TestCaptureConfig:
    """Tests for CaptureConfig defaults."""

    def test_defaults(self):
        """Should have sensible defaults."""
        config = CaptureConfig()

        assert config.js_required is False
        assert config.stealth is False
        assert config.headless is True
        assert config.expand_lazy_content is True
        assert config.take_screenshot is True

    def test_accordion_selectors(self):
        """Should have default accordion selectors."""
        config = CaptureConfig()

        assert len(config.accordion_selectors) > 0
        assert '[aria-expanded="false"]' in config.accordion_selectors


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
