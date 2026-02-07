"""
Access policy engine for closed-loop crawling (Div 4k1).

Responsibilities:
- Deterministic escalation ladder
- Budget enforcement (max attempts, max escalations)
- Backoff timing
- Policy layer merge: global defaults < domain playbook < run-config

This module is purely decisional — no I/O, no retries, no fetching.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Escalation ladder
# ---------------------------------------------------------------------------

ESCALATION_LADDER = ["requests", "js", "stealth", "stealth_patient", "visible"]

_LADDER_INDEX = {method: i for i, method in enumerate(ESCALATION_LADDER)}


# ---------------------------------------------------------------------------
# Default access plan
# ---------------------------------------------------------------------------

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_ESCALATIONS = 3
DEFAULT_DELAY_SECONDS = 3.0


@dataclass
class AccessPlan:
    """Effective access plan for a single page/domain."""
    initial_strategy: str = "requests"
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    max_escalations: int = DEFAULT_MAX_ESCALATIONS
    patient_mode: bool = False
    delay_seconds: float = DEFAULT_DELAY_SECONDS
    allow_stealth: bool = True
    allow_visible: bool = False


# ---------------------------------------------------------------------------
# Outcome constants (kept here for decision logic; canonical definitions
# live in access_outcome.py built by Stream 1)
# ---------------------------------------------------------------------------

SUCCESS = "success_real_content"

RECOVERABLE_OUTCOMES = frozenset({
    "soft_block",
    "challenge_not_cleared",
    "thin_content",
    "network_error",
    "timeout",
})

TERMINAL_OUTCOMES = frozenset({
    "hard_block",
    "non_html",
    "robots_denied",
})

# Network-class outcomes that should retry same strategy before escalating
RETRY_SAME_OUTCOMES = frozenset({
    "network_error",
    "timeout",
})


# ---------------------------------------------------------------------------
# Core decision function
# ---------------------------------------------------------------------------

def decide_next_strategy(
    current_strategy: str,
    outcome_str: str,
    attempt_index: int,
    plan: AccessPlan,
    same_strategy_retries: int = 0,
    domain_playbook: dict | None = None,
) -> str | None:
    """
    Decide the next fetch strategy given the current outcome.

    Returns:
        Next strategy string, or None if terminal (give up / enqueue).
    """
    # Success — no further action
    if outcome_str == SUCCESS:
        return None

    # Terminal outcomes — no point retrying
    if outcome_str in TERMINAL_OUTCOMES:
        return None

    # Budget check: max attempts
    if attempt_index + 1 >= plan.max_attempts:
        return None

    # For transient errors, retry same strategy once before escalating
    if outcome_str in RETRY_SAME_OUTCOMES and same_strategy_retries < 1:
        return current_strategy

    # Escalate up the ladder
    next_strategy = _next_on_ladder(current_strategy, plan, domain_playbook)

    if next_strategy is None:
        # Ceiling reached
        return None

    return next_strategy


def _next_on_ladder(
    current: str,
    plan: AccessPlan,
    playbook: dict | None = None,
) -> str | None:
    """
    Return the next strategy on the escalation ladder, respecting plan
    constraints and playbook overrides.
    """
    # Use actual position on ladder (stealth_patient has its own slot)
    current_idx = _LADDER_INDEX.get(current, 0)

    for candidate in ESCALATION_LADDER[current_idx + 1:]:
        # Respect plan constraints
        if candidate in ("stealth", "stealth_patient") and not plan.allow_stealth:
            continue
        if candidate == "visible" and not plan.allow_visible:
            continue

        # Playbook ceiling
        if playbook:
            ceiling = playbook.get("max_strategy")
            if ceiling and ceiling in _LADDER_INDEX:
                if _LADDER_INDEX.get(candidate, 99) > _LADDER_INDEX[ceiling]:
                    return None

        return candidate

    return None


# ---------------------------------------------------------------------------
# Backoff timing
# ---------------------------------------------------------------------------

def compute_backoff_delay(
    attempt_index: int,
    plan: AccessPlan,
    outcome_str: str,
) -> float:
    """
    Compute delay before next attempt.

    Uses exponential backoff with jitter-friendly base.
    Patient mode uses longer base delays.
    """
    import random

    base = plan.delay_seconds

    if plan.patient_mode or outcome_str in ("soft_block", "challenge_not_cleared"):
        # Patient: 8-20s base, scaling with attempt
        base = random.uniform(8.0, 20.0)

    # Exponential backoff: base * 2^attempt, capped at 120s
    delay = min(base * (2 ** attempt_index), 120.0)

    # Add jitter (±20%)
    jitter = delay * random.uniform(-0.2, 0.2)

    return max(1.0, delay + jitter)


# ---------------------------------------------------------------------------
# Plan construction from layered config
# ---------------------------------------------------------------------------

def build_access_plan(
    recon: object | None = None,
    fetch_spec: dict | None = None,
    domain_playbook: dict | None = None,
    cli_overrides: dict | None = None,
) -> AccessPlan:
    """
    Build an AccessPlan by merging config layers.

    Precedence: cli_overrides > fetch_spec > domain_playbook > defaults.
    Recon hints influence initial_strategy when no explicit override is set.
    """
    plan = AccessPlan()

    # Layer 1: domain playbook
    if domain_playbook:
        strategy = domain_playbook.get("strategy")
        if strategy:
            plan.initial_strategy = _normalize_playbook_strategy(strategy)
        if domain_playbook.get("patient"):
            plan.patient_mode = True
        if "delay" in domain_playbook:
            plan.delay_seconds = float(domain_playbook["delay"])
        if "max_attempts" in domain_playbook:
            plan.max_attempts = int(domain_playbook["max_attempts"])
        if domain_playbook.get("strategy") == "manual":
            plan.allow_visible = True
            plan.initial_strategy = "visible"

    # Layer 2: fetch spec (from orchestrate/fetch_spec.py resolution)
    if fetch_spec:
        method = fetch_spec.get("method")
        if method:
            plan.initial_strategy = _normalize_playbook_strategy(method)
        if fetch_spec.get("patient") or fetch_spec.get("slow_drip"):
            plan.patient_mode = True
        if "delay" in fetch_spec:
            plan.delay_seconds = float(fetch_spec["delay"])
        if "allow_stealth" in fetch_spec:
            plan.allow_stealth = bool(fetch_spec["allow_stealth"])
        if "allow_visible" in fetch_spec:
            plan.allow_visible = bool(fetch_spec["allow_visible"])
        if "patient_on_block" in fetch_spec:
            plan.patient_mode = bool(fetch_spec["patient_on_block"])

    # Layer 3: recon-informed defaults (only if no explicit method was set)
    if recon and plan.initial_strategy == "requests":
        js_required = getattr(recon, "js_required", False)
        challenge = getattr(recon, "challenge_detected", False)
        waf = getattr(recon, "waf", None) or getattr(recon, "waf_detected", False)

        if challenge or waf:
            plan.initial_strategy = "stealth"
            plan.patient_mode = True
        elif js_required:
            plan.initial_strategy = "js"

    # Layer 4: CLI overrides (highest precedence)
    if cli_overrides:
        if "access_max_attempts" in cli_overrides:
            plan.max_attempts = int(cli_overrides["access_max_attempts"])
        if "access_escalation_mode" in cli_overrides:
            if cli_overrides["access_escalation_mode"] == "static":
                plan.max_escalations = 0
        if "initial_strategy" in cli_overrides:
            plan.initial_strategy = cli_overrides["initial_strategy"]

    return plan


def _normalize_playbook_strategy(raw: str) -> str:
    """Map playbook/config strategy names to ladder names."""
    raw = raw.strip().lower()
    mapping = {
        "http": "requests",
        "requests": "requests",
        "request": "requests",
        "js": "js",
        "playwright": "js",
        "stealth": "stealth",
        "playwright_stealth": "stealth",
        "visible": "visible",
        "headed": "visible",
        "no-headless": "visible",
        "manual": "visible",
    }
    return mapping.get(raw, "requests")


# ---------------------------------------------------------------------------
# Playbook loading
# ---------------------------------------------------------------------------

_DEFAULT_PLAYBOOKS_PATH = (
    Path(__file__).resolve().parent.parent / "profiles" / "access_playbooks.yaml"
)


def load_playbooks(path: Path | None = None) -> dict[str, dict]:
    """
    Load domain playbooks from YAML.

    Returns dict mapping domain -> playbook config.
    """
    path = path or _DEFAULT_PLAYBOOKS_PATH
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return {k: v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        return {}


def get_domain_playbook(domain: str, playbooks: dict[str, dict] | None = None) -> dict | None:
    """
    Look up playbook for a domain, trying exact match then bare domain.
    """
    if playbooks is None:
        playbooks = load_playbooks()

    # Exact match
    if domain in playbooks:
        return playbooks[domain]

    # Strip www.
    bare = domain.replace("www.", "")
    if bare in playbooks:
        return playbooks[bare]

    return None


# ---------------------------------------------------------------------------
# Strategy → CaptureConfig translation
# ---------------------------------------------------------------------------

def strategy_to_capture_kwargs(strategy: str, plan: AccessPlan) -> dict:
    """
    Translate a ladder strategy into kwargs suitable for CaptureConfig.

    Returns a dict that can be unpacked to override CaptureConfig fields.
    """
    kwargs: dict = {}

    if strategy == "requests":
        kwargs["js_required"] = False
        kwargs["stealth"] = False
        kwargs["no_js_fallback"] = True
    elif strategy == "js":
        kwargs["js_required"] = True
        kwargs["stealth"] = False
        kwargs["headless"] = True
    elif strategy == "stealth":
        kwargs["js_required"] = True
        kwargs["stealth"] = True
        kwargs["headless"] = True
    elif strategy == "stealth_patient":
        kwargs["js_required"] = True
        kwargs["stealth"] = True
        kwargs["headless"] = True
        # Patient timing handled by backoff, not capture config
    elif strategy == "visible":
        kwargs["js_required"] = True
        kwargs["stealth"] = False
        kwargs["headless"] = False

    return kwargs


__all__ = [
    "ESCALATION_LADDER",
    "AccessPlan",
    "build_access_plan",
    "compute_backoff_delay",
    "decide_next_strategy",
    "get_domain_playbook",
    "load_playbooks",
    "strategy_to_capture_kwargs",
]
