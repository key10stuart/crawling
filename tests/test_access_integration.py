#!/usr/bin/env python3
"""
Integration tests for access layer components.

Tests the access layer end-to-end:
- Recon detection and caching
- Strategy selection and escalation
- Cookie persistence
- Playbook loading and overrides
- Access reporting and drift detection

These are integration test skeletons - some tests validate existing functionality,
others are marked as skipped until Agent 1 wires full integration.

Usage:
    pytest tests/test_access_integration.py -v
    pytest tests/test_access_integration.py -v -k "recon"
    pytest tests/test_access_integration.py -v -k "not slow"
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fetch.recon import recon_site, ReconResult, _detect_cdn, _detect_challenge
from fetch.strategy_cache import get_cached_strategy, update_strategy_cache
from fetch.cookies import inspect_cookies, load_cookies, CookieStatus


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_dir():
    """Temporary directory for test files."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def mock_recon_cache(temp_dir):
    """Temporary recon cache file."""
    return temp_dir / "recon_cache.json"


@pytest.fixture
def mock_strategy_cache(temp_dir):
    """Temporary strategy cache file."""
    return temp_dir / "strategy_cache.json"


@pytest.fixture
def mock_cookies_dir(temp_dir):
    """Temporary cookies directory."""
    cookies_dir = temp_dir / "cookies"
    cookies_dir.mkdir()
    return cookies_dir


@pytest.fixture
def sample_cookies(mock_cookies_dir):
    """Create sample cookie files for testing."""
    # Valid unexpired cookies
    future_ts = (datetime.now(timezone.utc) + timedelta(days=30)).timestamp()
    valid_cookies = [
        {"name": "session", "value": "abc123", "domain": "example.com", "expires": future_ts},
        {"name": "auth", "value": "xyz789", "domain": "example.com", "expires": future_ts},
    ]
    valid_path = mock_cookies_dir / "example.com.json"
    valid_path.write_text(json.dumps(valid_cookies))

    # Expired cookies
    past_ts = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    expired_cookies = [
        {"name": "old_session", "value": "expired", "domain": "old.com", "expires": past_ts},
    ]
    expired_path = mock_cookies_dir / "old.com.json"
    expired_path.write_text(json.dumps(expired_cookies))

    # Invalid JSON
    invalid_path = mock_cookies_dir / "invalid.json"
    invalid_path.write_text("not valid json {{{")

    return {
        "valid": valid_path,
        "expired": expired_path,
        "invalid": invalid_path,
    }


@pytest.fixture
def playbooks_content():
    """Sample playbook content."""
    return """
# Test playbooks
knight-swift.com:
  strategy: stealth
  delay: 5.0
  headless: false
  patient: true
  notes: "StackPath sgcaptcha - needs cookies"

example.com:
  strategy: http
  delay: 1.0
  headless: true
  notes: "Simple site"
"""


# =============================================================================
# Recon Module Tests
# =============================================================================

class TestReconDetection:
    """Test recon detection logic."""

    def test_detect_cdn_cloudflare(self):
        """Detect Cloudflare from headers."""
        headers = {"cf-ray": "abc123", "server": "cloudflare"}
        cdn, waf = _detect_cdn(headers)
        assert cdn == "cloudflare"
        assert waf == "cloudflare"

    def test_detect_cdn_akamai(self):
        """Detect Akamai from headers."""
        headers = {"server": "AkamaiGHost", "x-akamai-transformed": "9"}
        cdn, waf = _detect_cdn(headers)
        assert cdn == "akamai"
        assert waf == "akamai"

    def test_detect_cdn_stackpath(self):
        """Detect StackPath from headers."""
        headers = {"sg-captcha": "challenge"}
        cdn, waf = _detect_cdn(headers)
        assert cdn == "stackpath"
        assert waf == "stackpath"

    def test_detect_cdn_fastly(self):
        """Detect Fastly from headers."""
        headers = {"x-fastly-request-id": "abc", "server": "fastly-edge"}
        cdn, waf = _detect_cdn(headers)
        assert cdn == "fastly"
        assert waf == "fastly"

    def test_detect_cdn_none(self):
        """No CDN detected from plain headers."""
        headers = {"server": "Apache/2.4"}
        cdn, waf = _detect_cdn(headers)
        assert cdn is None
        assert waf is None

    def test_detect_challenge_cloudflare(self):
        """Detect Cloudflare challenge from HTML."""
        html = "<title>Just a moment...</title><p>Checking your browser before accessing</p>"
        assert _detect_challenge(html) is True

    def test_detect_challenge_captcha(self):
        """Detect captcha challenge from HTML."""
        html = "<div>Please complete the CAPTCHA to continue</div>"
        assert _detect_challenge(html) is True

    def test_detect_challenge_none(self):
        """No challenge in normal HTML."""
        html = "<html><body><h1>Welcome to our website</h1></body></html>"
        assert _detect_challenge(html) is False

    def test_detect_challenge_empty(self):
        """No challenge in empty HTML."""
        assert _detect_challenge(None) is False
        assert _detect_challenge("") is False


class TestReconCaching:
    """Test recon result caching."""

    def test_recon_caches_result(self, mock_recon_cache):
        """Recon results are cached."""
        with patch('fetch.recon.requests.get') as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {"server": "nginx"}
            mock_resp.text = "<html><body>Hello</body></html>"
            mock_get.return_value = mock_resp

            # First call - should hit network
            result1 = recon_site("https://example.com", cache_path=mock_recon_cache)
            assert mock_get.call_count == 1

            # Second call - should use cache
            result2 = recon_site("https://example.com", cache_path=mock_recon_cache)
            assert mock_get.call_count == 1  # No additional call

            assert result1.domain == result2.domain

    def test_recon_cache_expires(self, mock_recon_cache):
        """Expired cache entries are refreshed."""
        # Pre-populate cache with old entry
        old_time = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        cache_data = {
            "example.com": {
                "domain": "example.com",
                "url": "https://example.com",
                "status_code": 200,
                "headers": {},
                "cdn": None,
                "waf": None,
                "challenge_detected": False,
                "js_required": False,
                "js_confidence": None,
                "js_signals": [],
                "framework": None,
                "notes": [],
                "fetched_at": old_time,
            }
        }
        mock_recon_cache.parent.mkdir(parents=True, exist_ok=True)
        mock_recon_cache.write_text(json.dumps(cache_data))

        with patch('fetch.recon.requests.get') as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {"server": "nginx"}
            mock_resp.text = "<html><body>Hello</body></html>"
            mock_get.return_value = mock_resp

            # Cache is expired (>7 days default TTL) - should refresh
            result = recon_site("https://example.com", cache_path=mock_recon_cache, ttl_days=7)
            assert mock_get.call_count == 1


# =============================================================================
# Strategy Cache Tests
# =============================================================================

class TestStrategyCache:
    """Test strategy cache persistence."""

    def test_update_and_retrieve_strategy(self, mock_strategy_cache):
        """Strategy can be stored and retrieved."""
        update_strategy_cache(
            "example.com",
            method="js",
            success=True,
            cache_path=mock_strategy_cache
        )

        cached = get_cached_strategy("example.com", cache_path=mock_strategy_cache)
        assert cached == "js"

    def test_cached_strategy_returns_none_when_missing(self, mock_strategy_cache):
        """Returns None for uncached domains."""
        cached = get_cached_strategy("unknown.com", cache_path=mock_strategy_cache)
        assert cached is None

    def test_cached_strategy_expires(self, mock_strategy_cache):
        """Expired strategies return None."""
        # Pre-populate with old entry
        old_time = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        cache_data = {
            "example.com": {
                "last_success_method": "http",
                "updated_at": old_time,
            }
        }
        mock_strategy_cache.parent.mkdir(parents=True, exist_ok=True)
        mock_strategy_cache.write_text(json.dumps(cache_data))

        cached = get_cached_strategy(
            "example.com",
            cache_path=mock_strategy_cache,
            max_age_days=30
        )
        assert cached is None

    def test_update_tracks_failures(self, mock_strategy_cache):
        """Failed methods are tracked separately."""
        update_strategy_cache(
            "example.com",
            method="http",
            success=False,
            block_signals=["captcha"],
            cache_path=mock_strategy_cache
        )

        # Read raw cache to verify
        cache = json.loads(mock_strategy_cache.read_text())
        assert cache["example.com"]["last_fail_method"] == "http"
        assert "captcha" in cache["example.com"]["last_seen_block"]


# =============================================================================
# Cookie Loading Tests
# =============================================================================

class TestCookieLoading:
    """Test cookie loading and inspection."""

    def test_inspect_valid_cookies(self, sample_cookies, mock_cookies_dir):
        """Valid cookies are detected as not expired."""
        status = inspect_cookies("example.com", cookies_dir=mock_cookies_dir)
        assert status.exists is True
        assert status.expired is False
        assert status.warning is None

    def test_inspect_expired_cookies(self, sample_cookies, mock_cookies_dir):
        """Expired cookies are flagged."""
        status = inspect_cookies("old.com", cookies_dir=mock_cookies_dir)
        assert status.exists is True
        assert status.expired is True
        assert status.warning == "cookie_expired"

    def test_inspect_missing_cookies(self, mock_cookies_dir):
        """Missing cookie files are detected."""
        status = inspect_cookies("nonexistent.com", cookies_dir=mock_cookies_dir)
        assert status.exists is False
        assert status.warning == "cookie_file_missing"

    def test_inspect_invalid_cookies(self, sample_cookies, mock_cookies_dir):
        """Invalid JSON is flagged."""
        status = inspect_cookies("invalid", cookies_dir=mock_cookies_dir)
        assert status.exists is True
        assert status.warning == "cookie_file_invalid"

    def test_inspect_none_ref(self):
        """None cookie ref returns empty status."""
        status = inspect_cookies(None)
        assert status.path is None
        assert status.exists is False

    def test_load_valid_cookies(self, sample_cookies, mock_cookies_dir):
        """Valid cookies are loaded."""
        cookies = load_cookies("example.com", cookies_dir=mock_cookies_dir)
        assert cookies is not None
        assert len(cookies) == 2
        assert cookies[0]["name"] == "session"

    def test_load_filters_expired(self, sample_cookies, mock_cookies_dir):
        """Expired individual cookies are filtered out."""
        cookies = load_cookies("old.com", cookies_dir=mock_cookies_dir)
        # All cookies expired, so should be empty
        assert cookies is not None
        assert len(cookies) == 0

    def test_load_missing_returns_none(self, mock_cookies_dir):
        """Missing cookie file returns None."""
        cookies = load_cookies("nonexistent.com", cookies_dir=mock_cookies_dir)
        assert cookies is None


# =============================================================================
# Playbook Integration Tests
# =============================================================================

class TestPlaybookLoading:
    """Test playbook loading and overrides."""

    def test_playbook_file_exists(self):
        """Playbook file exists at expected location."""
        playbook_path = Path(__file__).parent.parent / "profiles" / "access_playbooks.yaml"
        assert playbook_path.exists(), f"Playbook file missing: {playbook_path}"

    def test_playbook_has_valid_yaml(self):
        """Playbook contains valid YAML."""
        import yaml
        playbook_path = Path(__file__).parent.parent / "profiles" / "access_playbooks.yaml"
        content = playbook_path.read_text()
        playbooks = yaml.safe_load(content)
        assert isinstance(playbooks, dict)
        assert len(playbooks) > 0

    def test_playbook_entries_have_required_fields(self):
        """Playbook entries have strategy field."""
        import yaml
        playbook_path = Path(__file__).parent.parent / "profiles" / "access_playbooks.yaml"
        playbooks = yaml.safe_load(playbook_path.read_text())

        for domain, config in playbooks.items():
            if domain.startswith("#"):  # Skip comments
                continue
            assert "strategy" in config, f"Missing strategy for {domain}"
            assert config["strategy"] in ("http", "js", "stealth", "manual"), \
                f"Invalid strategy for {domain}: {config['strategy']}"

    @pytest.mark.skip(reason="Needs Agent 1 to wire playbook loading into crawl.py")
    def test_playbook_overrides_default_strategy(self):
        """Playbook strategy overrides default selection."""
        # This test validates that when a domain is in the playbook,
        # its strategy is used instead of recon-based selection
        pass

    @pytest.mark.skip(reason="Needs Agent 1 to wire playbook loading into crawl.py")
    def test_playbook_delay_applied(self):
        """Playbook delay is applied to requests."""
        pass

    @pytest.mark.skip(reason="Needs Agent 1 to wire playbook loading into crawl.py")
    def test_playbook_skip_selectors_honored(self):
        """Skip selectors from playbook prevent clicking those links."""
        pass


# =============================================================================
# Access Report Tests
# =============================================================================

class TestAccessReport:
    """Test access reporting functionality."""

    def test_access_report_script_exists(self):
        """Access report script exists."""
        script_path = Path(__file__).parent.parent / "scripts" / "access_report.py"
        assert script_path.exists()

    def test_access_report_imports(self):
        """Access report module can be imported."""
        import importlib.util
        script_path = Path(__file__).parent.parent / "scripts" / "access_report.py"
        spec = importlib.util.spec_from_file_location("access_report", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Verify expected functions exist
        assert hasattr(module, 'analyze_access')
        assert hasattr(module, 'compute_metrics')
        assert hasattr(module, 'format_report')

    def test_compute_metrics_handles_empty(self):
        """Metrics computation handles empty analysis."""
        import importlib.util
        script_path = Path(__file__).parent.parent / "scripts" / "access_report.py"
        spec = importlib.util.spec_from_file_location("access_report", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        empty_analysis = {
            "by_tier": {},
            "by_method": {},
            "blocked_domains": [],
            "freshness": {"fresh": 0, "stale": 0, "missing": 0},
            "escalations": {},
            "word_counts": [],
            "page_counts": [],
            "total_carriers": 0,
        }

        metrics = module.compute_metrics(empty_analysis)
        assert isinstance(metrics, dict)


# =============================================================================
# Drift Detection Tests
# =============================================================================

class TestDriftDetection:
    """Test drift detection functionality."""

    def test_drift_report_script_exists(self):
        """Drift report script exists."""
        script_path = Path(__file__).parent.parent / "scripts" / "access_drift_report.py"
        assert script_path.exists()

    def test_drift_report_imports(self):
        """Drift report module can be imported."""
        import importlib.util
        script_path = Path(__file__).parent.parent / "scripts" / "access_drift_report.py"
        spec = importlib.util.spec_from_file_location("access_drift_report", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, 'compare_snapshots')
        assert hasattr(module, 'extract_snapshot')

    def test_compare_snapshots_detects_content_drop(self):
        """Content drop is detected as drift."""
        import importlib.util
        script_path = Path(__file__).parent.parent / "scripts" / "access_drift_report.py"
        spec = importlib.util.spec_from_file_location("access_drift_report", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        old_snapshot = {
            "domain": "example.com",
            "crawl_start": "2024-01-01T00:00:00Z",
            "total_words": 10000,
            "total_pages": 50,
            "page_urls": [f"https://example.com/page{i}" for i in range(50)],
            "page_words": {},
            "strategy": "http",
            "blocked": False,
        }

        new_snapshot = {
            "domain": "example.com",
            "crawl_start": "2024-01-15T00:00:00Z",
            "total_words": 3000,  # 70% drop
            "total_pages": 20,
            "page_urls": [f"https://example.com/page{i}" for i in range(20)],
            "page_words": {},
            "strategy": "http",
            "blocked": False,
        }

        drift = module.compare_snapshots(old_snapshot, new_snapshot, threshold=0.3)

        assert "alerts" in drift
        alert_types = [a["type"] for a in drift["alerts"]]
        assert "content_drop" in alert_types

    def test_compare_snapshots_detects_new_block(self):
        """New block is detected as drift."""
        import importlib.util
        script_path = Path(__file__).parent.parent / "scripts" / "access_drift_report.py"
        spec = importlib.util.spec_from_file_location("access_drift_report", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        old_snapshot = {
            "domain": "example.com",
            "crawl_start": "2024-01-01T00:00:00Z",
            "total_words": 10000,
            "total_pages": 50,
            "page_urls": [],
            "page_words": {},
            "strategy": "http",
            "blocked": False,
        }

        new_snapshot = {
            "domain": "example.com",
            "crawl_start": "2024-01-15T00:00:00Z",
            "total_words": 100,
            "total_pages": 1,
            "page_urls": [],
            "page_words": {},
            "strategy": "js",
            "blocked": True,  # Now blocked
        }

        drift = module.compare_snapshots(old_snapshot, new_snapshot)

        alert_types = [a["type"] for a in drift["alerts"]]
        assert "new_block" in alert_types

    def test_compare_snapshots_handles_missing(self):
        """Missing snapshots return error."""
        import importlib.util
        script_path = Path(__file__).parent.parent / "scripts" / "access_drift_report.py"
        spec = importlib.util.spec_from_file_location("access_drift_report", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        drift = module.compare_snapshots(None, {"domain": "example.com"})
        assert drift.get("error") == "missing_snapshot"


# =============================================================================
# End-to-End Integration Tests (Skipped until wired)
# =============================================================================

@pytest.mark.skip(reason="Needs full integration wiring")
class TestEndToEndAccess:
    """End-to-end access layer tests."""

    def test_recon_to_strategy_selection(self):
        """Recon results inform strategy selection."""
        pass

    def test_escalation_on_block(self):
        """Blocked fetch triggers escalation to next strategy."""
        pass

    def test_strategy_cache_prevents_rework(self):
        """Cached successful strategy is reused."""
        pass

    def test_monkey_fallback_queued_on_failure(self):
        """Multiple failures queue domain for monkey intervention."""
        pass

    def test_perpetual_manual_detection(self):
        """Domains queued 3+ times in 90 days flagged perpetual manual."""
        pass


# =============================================================================
# Run tests directly
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
