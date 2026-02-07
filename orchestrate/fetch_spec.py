"""
Fetch spec resolution and fetch config construction.

Extracted from scripts/crawl.py (Div 4k Phase 2).
"""

from __future__ import annotations

import argparse
from typing import Iterable

from fetch.config import FetchConfig


def _merge_specs(*layers: dict) -> dict:
    merged = {}
    for layer in layers:
        if isinstance(layer, dict):
            merged.update({k: v for k, v in layer.items() if v is not None})
    return merged


def _build_cli_fetch_spec(args: argparse.Namespace, provided_flags: set[str]) -> dict:
    spec = {}
    if "fetch_method" in provided_flags and args.fetch_method:
        spec["method"] = args.fetch_method
    else:
        if "stealth" in provided_flags and args.stealth:
            spec["method"] = "stealth"
        elif "js" in provided_flags and args.js:
            spec["method"] = "js"
    if "no_headless" in provided_flags:
        spec["headless"] = not args.no_headless
    if "delay" in provided_flags:
        spec["delay"] = args.delay
    if "patient" in provided_flags:
        spec["patient"] = args.patient
    if "slow_drip" in provided_flags:
        spec["slow_drip"] = args.slow_drip
    if "js_fallback" in provided_flags:
        spec["js_fallback"] = args.js_fallback
    if "js_auto" in provided_flags:
        spec["js_auto"] = args.js_auto
    # Div 4k1: access policy hints
    if "allow_stealth" in provided_flags:
        spec["allow_stealth"] = getattr(args, "allow_stealth", True)
    if "allow_visible" in provided_flags:
        spec["allow_visible"] = getattr(args, "allow_visible", False)
    if "patient_on_block" in provided_flags:
        spec["patient_on_block"] = getattr(args, "patient_on_block", False)
    return spec


def _build_run_fetch_spec(args: argparse.Namespace) -> dict:
    spec = {}
    run_keys = getattr(args, "_run_config_keys", set())
    if "fetch_method" in run_keys and args.fetch_method:
        spec["method"] = args.fetch_method
    else:
        if "stealth" in run_keys and args.stealth:
            spec["method"] = "stealth"
        elif "js" in run_keys and args.js:
            spec["method"] = "js"
    if "no_headless" in run_keys:
        spec["headless"] = not args.no_headless
    if "delay" in run_keys:
        spec["delay"] = args.delay
    if "patient" in run_keys:
        spec["patient"] = args.patient
    if "slow_drip" in run_keys:
        spec["slow_drip"] = args.slow_drip
    if "js_fallback" in run_keys:
        spec["js_fallback"] = args.js_fallback
    if "js_auto" in run_keys:
        spec["js_auto"] = args.js_auto
    return spec


def resolve_fetch_spec(
    carrier: dict,
    args: argparse.Namespace,
    cfg: dict,
    provided_flags: set[str],
    fetch_profiles: dict,
) -> dict:
    """Resolve per-site fetch spec with precedence: CLI > run-config > seed > defaults."""
    seed_fetch = carrier.get("fetch", {}) if isinstance(carrier.get("fetch"), dict) else {}
    run_fetch = cfg.get("fetch", {}) if isinstance(cfg, dict) and isinstance(cfg.get("fetch"), dict) else {}

    run_profile_spec = {}
    run_profile_name = cfg.get("fetch_profile") if isinstance(cfg, dict) else None
    if run_profile_name:
        run_profile_spec = fetch_profiles.get(run_profile_name, {})
        if not run_profile_spec:
            print(f"  [fetch-profile] Missing profile: {run_profile_name}")

    cli_profile_spec = {}
    if args.fetch_profile:
        cli_profile_spec = fetch_profiles.get(args.fetch_profile, {})
        if not cli_profile_spec:
            print(f"  [fetch-profile] Missing profile: {args.fetch_profile}")

    run_flag_spec = _build_run_fetch_spec(args)
    cli_spec = _build_cli_fetch_spec(args, provided_flags)
    return _merge_specs(seed_fetch, run_fetch, run_profile_spec, run_flag_spec, cli_profile_spec, cli_spec)


FETCH_METHOD_LADDER = ["requests", "js", "stealth", "visible"]


def _normalize_method(method: str | None) -> str | None:
    if not method:
        return None
    method = method.strip().lower()
    if method in ("request", "requests", "http"):
        return "requests"
    if method in ("js", "playwright"):
        return "js"
    if method in ("stealth", "playwright_stealth"):
        return "stealth"
    if method in ("visible", "headed", "no-headless"):
        return "visible"
    if method == "auto":
        return None
    return None


def _build_fetch_config(method: str, base_config: dict) -> FetchConfig:
    js_always = False
    stealth = False
    headless = base_config.get("headless", True)
    js_fallback = base_config.get("js_fallback", False)

    if method == "requests":
        js_always = False
    elif method == "js":
        js_always = True
        js_fallback = False
    elif method == "stealth":
        js_always = True
        stealth = True
        js_fallback = False
    elif method == "visible":
        js_always = True
        headless = False
        js_fallback = False

    return FetchConfig(
        js_fallback=js_fallback,
        js_always=js_always,
        stealth_fallback=stealth,
        headless=headless,
        js_render_timeout_ms=base_config.get("js_render_timeout_ms"),
        js_wait_until=base_config.get("js_wait_until"),
        min_words=base_config.get("min_words"),
        archive_html=True,
        archive_dir=base_config.get("archive_dir"),
        extract_images=True,
        extract_code=True,
        return_html=True,
        cookie_ref=base_config.get("cookie_ref"),
        cookies_dir=base_config.get("cookies_dir"),
    )


def extract_access_hints(fetch_spec: dict) -> dict:
    """
    Extract access-policy-relevant hints from a resolved fetch spec.

    Returns a dict suitable for passing as fetch_spec to
    fetch.access_policy.build_access_plan().
    """
    hints = {}
    if "method" in fetch_spec:
        hints["method"] = fetch_spec["method"]
    for key in (
        "patient", "slow_drip", "delay",
        "allow_stealth", "allow_visible", "patient_on_block",
    ):
        if key in fetch_spec:
            hints[key] = fetch_spec[key]
    return hints


__all__ = [
    "_merge_specs",
    "_build_cli_fetch_spec",
    "_build_run_fetch_spec",
    "resolve_fetch_spec",
    "extract_access_hints",
    "FETCH_METHOD_LADDER",
    "_normalize_method",
    "_build_fetch_config",
]
