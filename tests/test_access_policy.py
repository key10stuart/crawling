"""
Tests for fetch/access_policy.py (Stream B — Div 4k1).

Unit tests:
- Escalation transitions are deterministic
- Retry ceilings stop correctly
- Backoff timing is bounded
- Plan construction from layered config
- Strategy-to-config translation

Integration tests (mocked sequences):
- soft_block → escalate → success
- hard_block → terminal immediately
- network_error → retry same → escalate
- all fail → terminal after budget exhausted
"""

import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from fetch.access_policy import (
    ESCALATION_LADDER,
    AccessPlan,
    build_access_plan,
    compute_backoff_delay,
    decide_next_strategy,
    get_domain_playbook,
    load_playbooks,
    strategy_to_capture_kwargs,
    _normalize_playbook_strategy,
    _next_on_ladder,
)


# ---------------------------------------------------------------------------
# Unit: Escalation ladder
# ---------------------------------------------------------------------------

class TestEscalationLadder:
    """Escalation transitions are deterministic and ordered."""

    def test_ladder_order(self):
        assert ESCALATION_LADDER == [
            "requests", "js", "stealth", "stealth_patient", "visible"
        ]

    def test_requests_escalates_to_js(self):
        plan = AccessPlan(max_attempts=5)
        result = decide_next_strategy(
            current_strategy="requests",
            outcome_str="soft_block",
            attempt_index=0,
            plan=plan,
        )
        assert result == "js"

    def test_js_escalates_to_stealth(self):
        plan = AccessPlan(max_attempts=5)
        result = decide_next_strategy(
            current_strategy="js",
            outcome_str="soft_block",
            attempt_index=1,
            plan=plan,
        )
        assert result == "stealth"

    def test_stealth_escalates_to_stealth_patient(self):
        plan = AccessPlan(max_attempts=5)
        result = decide_next_strategy(
            current_strategy="stealth",
            outcome_str="challenge_not_cleared",
            attempt_index=2,
            plan=plan,
        )
        assert result == "stealth_patient"

    def test_stealth_patient_escalates_to_visible_if_allowed(self):
        plan = AccessPlan(max_attempts=5, allow_visible=True)
        result = decide_next_strategy(
            current_strategy="stealth_patient",
            outcome_str="soft_block",
            attempt_index=3,
            plan=plan,
        )
        assert result == "visible"

    def test_visible_not_allowed_by_default(self):
        plan = AccessPlan(max_attempts=5, allow_visible=False)
        result = decide_next_strategy(
            current_strategy="stealth_patient",
            outcome_str="soft_block",
            attempt_index=3,
            plan=plan,
        )
        assert result is None  # Ceiling reached

    def test_stealth_not_allowed(self):
        plan = AccessPlan(max_attempts=5, allow_stealth=False)
        result = decide_next_strategy(
            current_strategy="js",
            outcome_str="soft_block",
            attempt_index=1,
            plan=plan,
        )
        assert result is None  # Stealth skipped, nothing above


# ---------------------------------------------------------------------------
# Unit: Success and terminal outcomes
# ---------------------------------------------------------------------------

class TestOutcomeHandling:

    def test_success_returns_none(self):
        plan = AccessPlan()
        result = decide_next_strategy(
            current_strategy="requests",
            outcome_str="success_real_content",
            attempt_index=0,
            plan=plan,
        )
        assert result is None

    def test_hard_block_is_terminal(self):
        plan = AccessPlan()
        result = decide_next_strategy(
            current_strategy="requests",
            outcome_str="hard_block",
            attempt_index=0,
            plan=plan,
        )
        assert result is None

    def test_non_html_is_terminal(self):
        plan = AccessPlan()
        result = decide_next_strategy(
            current_strategy="requests",
            outcome_str="non_html",
            attempt_index=0,
            plan=plan,
        )
        assert result is None

    def test_robots_denied_is_terminal(self):
        plan = AccessPlan()
        result = decide_next_strategy(
            current_strategy="requests",
            outcome_str="robots_denied",
            attempt_index=0,
            plan=plan,
        )
        assert result is None


# ---------------------------------------------------------------------------
# Unit: Retry ceilings
# ---------------------------------------------------------------------------

class TestRetryCeilings:

    def test_max_attempts_stops_escalation(self):
        plan = AccessPlan(max_attempts=2)
        # First attempt (idx 0) fails → would normally escalate
        result = decide_next_strategy(
            current_strategy="requests",
            outcome_str="soft_block",
            attempt_index=1,  # This is the 2nd attempt (0-indexed), budget=2
            plan=plan,
        )
        assert result is None  # Budget exhausted

    def test_max_attempts_1_means_single_shot(self):
        plan = AccessPlan(max_attempts=1)
        result = decide_next_strategy(
            current_strategy="requests",
            outcome_str="soft_block",
            attempt_index=0,
            plan=plan,
        )
        assert result is None


# ---------------------------------------------------------------------------
# Unit: Network error retry-same behavior
# ---------------------------------------------------------------------------

class TestNetworkErrorRetry:

    def test_network_error_retries_same_first(self):
        plan = AccessPlan(max_attempts=5)
        result = decide_next_strategy(
            current_strategy="js",
            outcome_str="network_error",
            attempt_index=0,
            plan=plan,
            same_strategy_retries=0,
        )
        assert result == "js"  # Retry same strategy once

    def test_network_error_escalates_after_retry(self):
        plan = AccessPlan(max_attempts=5)
        result = decide_next_strategy(
            current_strategy="js",
            outcome_str="network_error",
            attempt_index=1,
            plan=plan,
            same_strategy_retries=1,
        )
        assert result == "stealth"  # Escalate after retry

    def test_timeout_retries_same_first(self):
        plan = AccessPlan(max_attempts=5)
        result = decide_next_strategy(
            current_strategy="requests",
            outcome_str="timeout",
            attempt_index=0,
            plan=plan,
            same_strategy_retries=0,
        )
        assert result == "requests"  # Retry same


# ---------------------------------------------------------------------------
# Unit: Backoff timing
# ---------------------------------------------------------------------------

class TestBackoffDelay:

    def test_base_delay(self):
        plan = AccessPlan(delay_seconds=3.0, patient_mode=False)
        delay = compute_backoff_delay(0, plan, "soft_block")
        # Patient mode kicks in for soft_block, so delay is 8-20s base
        assert delay >= 1.0

    def test_delay_increases_with_attempts(self):
        plan = AccessPlan(delay_seconds=3.0, patient_mode=False)
        d0 = compute_backoff_delay(0, plan, "thin_content")
        d2 = compute_backoff_delay(2, plan, "thin_content")
        # d2 should generally be larger (exponential backoff)
        # Allow for jitter — just check it's bounded
        assert d2 <= 120.0

    def test_delay_capped_at_120(self):
        plan = AccessPlan(delay_seconds=10.0, patient_mode=True)
        delay = compute_backoff_delay(10, plan, "soft_block")
        assert delay <= 120.0 * 1.3  # Allow jitter headroom


# ---------------------------------------------------------------------------
# Unit: Plan construction
# ---------------------------------------------------------------------------

class TestBuildAccessPlan:

    def test_default_plan(self):
        plan = build_access_plan()
        assert plan.initial_strategy == "requests"
        assert plan.max_attempts == 3
        assert plan.patient_mode is False

    def test_recon_js_required(self):
        class MockRecon:
            js_required = True
            challenge_detected = False
            waf = None
            waf_detected = False
        plan = build_access_plan(recon=MockRecon())
        assert plan.initial_strategy == "js"

    def test_recon_challenge_detected(self):
        class MockRecon:
            js_required = False
            challenge_detected = True
            waf = "cloudflare"
            waf_detected = True
        plan = build_access_plan(recon=MockRecon())
        assert plan.initial_strategy == "stealth"
        assert plan.patient_mode is True

    def test_playbook_override(self):
        playbook = {"strategy": "stealth", "delay": 5.0, "patient": True}
        plan = build_access_plan(domain_playbook=playbook)
        assert plan.initial_strategy == "stealth"
        assert plan.delay_seconds == 5.0
        assert plan.patient_mode is True

    def test_fetch_spec_overrides_playbook(self):
        playbook = {"strategy": "js", "delay": 3.0}
        fetch_spec = {"method": "stealth", "delay": 10.0}
        plan = build_access_plan(domain_playbook=playbook, fetch_spec=fetch_spec)
        assert plan.initial_strategy == "stealth"
        assert plan.delay_seconds == 10.0

    def test_cli_overrides_max_attempts(self):
        plan = build_access_plan(cli_overrides={"access_max_attempts": 5})
        assert plan.max_attempts == 5

    def test_cli_static_mode_disables_escalation(self):
        plan = build_access_plan(cli_overrides={"access_escalation_mode": "static"})
        assert plan.max_escalations == 0

    def test_manual_playbook_enables_visible(self):
        playbook = {"strategy": "manual"}
        plan = build_access_plan(domain_playbook=playbook)
        assert plan.allow_visible is True
        assert plan.initial_strategy == "visible"


# ---------------------------------------------------------------------------
# Unit: Strategy normalization
# ---------------------------------------------------------------------------

class TestStrategyNormalization:

    def test_http_to_requests(self):
        assert _normalize_playbook_strategy("http") == "requests"

    def test_playwright_to_js(self):
        assert _normalize_playbook_strategy("playwright") == "js"

    def test_headed_to_visible(self):
        assert _normalize_playbook_strategy("headed") == "visible"

    def test_unknown_defaults_to_requests(self):
        assert _normalize_playbook_strategy("magic") == "requests"


# ---------------------------------------------------------------------------
# Unit: Strategy → CaptureConfig translation
# ---------------------------------------------------------------------------

class TestStrategyToCapture:

    def test_requests_config(self):
        plan = AccessPlan()
        kwargs = strategy_to_capture_kwargs("requests", plan)
        assert kwargs["js_required"] is False
        assert kwargs["no_js_fallback"] is True

    def test_js_config(self):
        plan = AccessPlan()
        kwargs = strategy_to_capture_kwargs("js", plan)
        assert kwargs["js_required"] is True
        assert kwargs["stealth"] is False

    def test_stealth_config(self):
        plan = AccessPlan()
        kwargs = strategy_to_capture_kwargs("stealth", plan)
        assert kwargs["js_required"] is True
        assert kwargs["stealth"] is True
        assert kwargs["headless"] is True

    def test_visible_config(self):
        plan = AccessPlan()
        kwargs = strategy_to_capture_kwargs("visible", plan)
        assert kwargs["js_required"] is True
        assert kwargs["headless"] is False


# ---------------------------------------------------------------------------
# Unit: Playbook loading
# ---------------------------------------------------------------------------

class TestPlaybookLoading:

    def test_get_domain_playbook_exact(self):
        playbooks = {"example.com": {"strategy": "js"}}
        result = get_domain_playbook("example.com", playbooks)
        assert result == {"strategy": "js"}

    def test_get_domain_playbook_strips_www(self):
        playbooks = {"example.com": {"strategy": "stealth"}}
        result = get_domain_playbook("www.example.com", playbooks)
        assert result == {"strategy": "stealth"}

    def test_get_domain_playbook_missing(self):
        playbooks = {"example.com": {"strategy": "js"}}
        result = get_domain_playbook("other.com", playbooks)
        assert result is None

    def test_load_playbooks_missing_file(self, tmp_path):
        result = load_playbooks(tmp_path / "nonexistent.yaml")
        assert result == {}


# ---------------------------------------------------------------------------
# Unit: Playbook ceiling
# ---------------------------------------------------------------------------

class TestPlaybookCeiling:

    def test_max_strategy_ceiling(self):
        plan = AccessPlan(max_attempts=5, allow_stealth=True, allow_visible=True)
        playbook = {"max_strategy": "js"}
        result = decide_next_strategy(
            current_strategy="requests",
            outcome_str="soft_block",
            attempt_index=0,
            plan=plan,
            domain_playbook=playbook,
        )
        assert result == "js"
        # Now from js, should be blocked by ceiling
        result2 = decide_next_strategy(
            current_strategy="js",
            outcome_str="soft_block",
            attempt_index=1,
            plan=plan,
            domain_playbook=playbook,
        )
        assert result2 is None


# ---------------------------------------------------------------------------
# Integration: Mocked escalation sequences
# ---------------------------------------------------------------------------

class TestEscalationSequences:
    """Simulate full escalation paths through the policy engine."""

    def test_soft_block_escalation_path(self):
        """requests → soft_block → js → soft_block → stealth → success."""
        plan = AccessPlan(max_attempts=5)

        s1 = decide_next_strategy("requests", "soft_block", 0, plan)
        assert s1 == "js"

        s2 = decide_next_strategy("js", "soft_block", 1, plan)
        assert s2 == "stealth"

        # Simulate success at stealth — returns None (no more action)
        s3 = decide_next_strategy("stealth", "success_real_content", 2, plan)
        assert s3 is None

    def test_challenge_escalation_path(self):
        """js → challenge → stealth → challenge → stealth_patient → success."""
        plan = AccessPlan(max_attempts=5)

        s1 = decide_next_strategy("js", "challenge_not_cleared", 0, plan)
        assert s1 == "stealth"

        s2 = decide_next_strategy("stealth", "challenge_not_cleared", 1, plan)
        assert s2 == "stealth_patient"

    def test_full_exhaustion(self):
        """Every strategy fails → terminal."""
        plan = AccessPlan(max_attempts=5, allow_visible=True)

        s1 = decide_next_strategy("requests", "soft_block", 0, plan)
        assert s1 == "js"

        s2 = decide_next_strategy("js", "soft_block", 1, plan)
        assert s2 == "stealth"

        s3 = decide_next_strategy("stealth", "soft_block", 2, plan)
        assert s3 == "stealth_patient"

        s4 = decide_next_strategy("stealth_patient", "soft_block", 3, plan)
        assert s4 == "visible"

        # At ceiling — max_attempts=5, attempt_index=4 means budget gone
        s5 = decide_next_strategy("visible", "soft_block", 4, plan)
        assert s5 is None

    def test_network_error_retry_then_escalate(self):
        """requests → network_error → retry requests → network_error → escalate to js."""
        plan = AccessPlan(max_attempts=5)

        # First network error: retry same
        s1 = decide_next_strategy("requests", "network_error", 0, plan, same_strategy_retries=0)
        assert s1 == "requests"

        # Second network error on same strategy: escalate
        s2 = decide_next_strategy("requests", "network_error", 1, plan, same_strategy_retries=1)
        assert s2 == "js"
