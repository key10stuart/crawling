"""
Presentation helpers for crawl output.

Keeps crawl.py focused on orchestration while this module builds and saves
site JSON outputs.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import json


def resolve_fetch_method(captures: list) -> str:
    methods = [c.fetch_method for c in captures if getattr(c, "fetch_method", None)]
    if not methods:
        return "unknown"
    counts = Counter(methods)
    if len(counts) == 1:
        return next(iter(counts))
    return "mixed"


def _build_access_summary(access_telemetry: list[dict]) -> dict:
    """
    Build site-level access summary from per-URL attempt telemetry.

    Args:
        access_telemetry: list of per-URL dicts with keys:
            - url: str
            - final_outcome: str (outcome class)
            - attempts: list[dict] (per-attempt records)
            - escalations_used: list[str] (strategies attempted)

    Returns:
        Dict with outcome_counts and escalations_used summaries.
    """
    if not access_telemetry:
        return {}

    outcome_counts: dict[str, int] = {}
    strategies_used: dict[str, int] = {}
    total_attempts = 0

    for entry in access_telemetry:
        outcome = entry.get("final_outcome", "unknown")
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

        attempts = entry.get("attempts", [])
        total_attempts += len(attempts)

        for strategy in entry.get("escalations_used", []):
            strategies_used[strategy] = strategies_used.get(strategy, 0) + 1

    successes = outcome_counts.get("success_real_content", 0)
    total_urls = len(access_telemetry)

    return {
        "outcome_counts": outcome_counts,
        "escalations_used": strategies_used,
        "total_urls_attempted": total_urls,
        "total_attempts": total_attempts,
        "effective_success_rate": round(successes / total_urls, 3) if total_urls else 0,
        "average_attempts_per_url": round(total_attempts / total_urls, 2) if total_urls else 0,
    }


def build_capture_site_data(
    carrier: dict,
    captures: list,
    extracted_pages: list[dict],
    attempted_count: int,
    site_profile: dict | None = None,
    snapshot_date: str | None = None,
    access_telemetry: list[dict] | None = None,
) -> dict:
    domain = carrier["domain"]
    base_domain = domain.split("/")[0] if "/" in domain else domain
    snapshot_date = snapshot_date or datetime.now().strftime("%Y-%m-%d")

    total_html_kb = sum(c.html_size_bytes for c in captures) // 1024
    total_assets = sum(len(c.asset_inventory) for c in captures)
    total_word_count = sum(p.get("main_content", {}).get("word_count", 0) for p in extracted_pages)

    fetch_method = resolve_fetch_method(captures)

    site_data = {
        "domain": domain,
        "company_name": carrier["name"],
        "category": carrier.get("category", []),
        "tier": carrier.get("tier"),
        "snapshot_date": snapshot_date,
        "capture_mode": True,
        "corpus_version": 2,
        "fetch_method": fetch_method,
        "captures": [
            {
                "url": c.url,
                "final_url": c.final_url,
                "html_path": str(c.html_path) if c.html_path else None,
                "screenshot_path": str(c.screenshot_path) if c.screenshot_path else None,
                "content_hash": c.content_hash,
                "fetch_method": c.fetch_method,
                "asset_count": len(c.asset_inventory),
                "interaction_log": c.interaction_log,
                "expansion_stats": c.expansion_stats,
            }
            for c in captures
        ],
        "pages": extracted_pages,
        "stats": {
            "pages_captured": len(captures),
            "pages_failed": max(0, attempted_count - len(captures)),
            "total_html_kb": total_html_kb,
            "total_assets": total_assets,
        },
        "site_profile": site_profile,
        "structure": {
            "total_pages": len(captures),
            "total_word_count": total_word_count,
        },
        "total_word_count": total_word_count,
        "base_domain": base_domain,
    }

    # Div 4k1: access telemetry
    if access_telemetry:
        site_data["access_telemetry"] = access_telemetry
        site_data["access_summary"] = _build_access_summary(access_telemetry)

    return site_data


def write_site_json(site_data: dict, sites_dir: Path) -> Path:
    base_domain = site_data.get("base_domain") or site_data["domain"].split("/")[0]
    site_file = sites_dir / f"{base_domain.replace('.', '_')}.json"
    site_file.parent.mkdir(parents=True, exist_ok=True)
    with open(site_file, "w") as f:
        json.dump(site_data, f, indent=2)
    return site_file


def get_page_count(site_data: dict) -> int:
    if site_data.get("capture_mode"):
        return site_data.get("stats", {}).get("pages_captured", len(site_data.get("pages", [])))
    return site_data.get("structure", {}).get("total_pages", 0)


def get_word_count(site_data: dict) -> int:
    if site_data.get("capture_mode"):
        return site_data.get("total_word_count", 0)
    return site_data.get("total_word_count", 0)


__all__ = [
    "_build_access_summary",
    "build_capture_site_data",
    "get_page_count",
    "get_word_count",
    "resolve_fetch_method",
    "write_site_json",
]
