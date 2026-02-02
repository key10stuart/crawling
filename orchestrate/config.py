"""
Configuration loading and freshness checking for crawl orchestration.

Extracted from scripts/crawl.py (Div 4k Phase 1).
"""

import argparse
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path


# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SEEDS_FILE = PROJECT_ROOT / "seeds" / "trucking_carriers.json"
CORPUS_DIR = PROJECT_ROOT / "corpus"
RAW_DIR = CORPUS_DIR / "raw"
EXTRACTED_DIR = CORPUS_DIR / "extracted"
SITES_DIR = CORPUS_DIR / "sites"


def parse_freshen_interval(s: str) -> timedelta:
    """Parse '7d', '24h', '2h', '30m' into timedelta."""
    match = re.match(r'^(\d+)([dhm])$', s.lower())
    if not match:
        raise ValueError(f"Invalid freshen interval: {s} (use e.g. 7d, 24h, 2h, 30m)")
    value, unit = int(match.group(1)), match.group(2)
    if unit == 'd':
        return timedelta(days=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'm':
        return timedelta(minutes=value)


def should_skip_site_freshness(
    domain: str,
    freshen: timedelta | None,
    requested_depth: int = None,
) -> tuple[bool, str]:
    """Check if site was crawled recently enough to skip.

    Returns (should_skip, age_str) where age_str is human-readable if skipping.

    If requested_depth is provided, only skip if previous crawl depth >= requested.
    """
    if freshen is None:
        return False, ""

    # Check both default and run-specific locations
    base_domain = domain.split('/')[0] if '/' in domain else domain
    site_file = SITES_DIR / f"{base_domain.replace('.', '_')}.json"

    if not site_file.exists():
        return False, ""

    try:
        with open(site_file) as f:
            data = json.load(f)
        crawl_start = data.get('crawl_start')
        if not crawl_start:
            return False, ""

        # Check depth if requested
        if requested_depth is not None:
            prev_depth = data.get('crawl_depth', 0)
            if prev_depth < requested_depth:
                return False, ""  # Previous crawl was shallower, don't skip

        # Parse ISO timestamp
        crawl_time = datetime.fromisoformat(crawl_start.replace('Z', '+00:00'))
        age = datetime.now(timezone.utc) - crawl_time

        if age < freshen:
            hours = age.total_seconds() / 3600
            if hours < 1:
                age_str = f"{int(age.total_seconds() / 60)}m ago"
            elif hours < 24:
                age_str = f"{hours:.1f}h ago"
            else:
                age_str = f"{age.days}d ago"
            prev_depth = data.get('crawl_depth', '?')
            age_str = f"{age_str}, depth {prev_depth}"
            return True, age_str
    except (json.JSONDecodeError, KeyError, ValueError):
        pass

    return False, ""


def load_seeds() -> dict:
    """Load carrier seed list."""
    with open(SEEDS_FILE) as f:
        return json.load(f)


def load_companies_file(path: str) -> list[dict]:
    """Load a custom companies list from JSON or YAML."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Companies file not found: {path}")
    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except Exception as exc:
            raise RuntimeError("PyYAML required for YAML companies file") from exc
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    else:
        data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "carriers" in data:
        data = data["carriers"]
    if not isinstance(data, list):
        raise ValueError("Companies file must be a list or contain 'carriers' list")
    return data


def load_run_config(path: str) -> dict:
    """Load a run configuration from JSON or YAML."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Run config not found: {path}")

    # Handle empty files (e.g., /dev/null) gracefully
    content = p.read_text(encoding="utf-8").strip()
    if not content:
        return {}

    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except Exception as exc:
            raise RuntimeError("PyYAML required for YAML run config") from exc
        result = yaml.safe_load(content)
        return result if result else {}

    result = json.loads(content)
    return result if result else {}


def apply_run_config(
    args: argparse.Namespace,
    cfg: dict,
    provided_flags: set[str],
) -> argparse.Namespace:
    """Apply run config to args, respecting CLI overrides."""
    if not cfg:
        return args

    aliases = {
        "companies_file": "companies",
        "js_min_words": "js_min_words",
        "js_fallback": "js_fallback",
        "js_auto": "js_auto",
        "jobs": "jobs",
        "fetch_method": "fetch_method",
        "fetch_profile": "fetch_profile",
        "depth": "depth",
        "freshen": "freshen",
        "progress": "progress",
        "patient": "patient",
        "slow_drip": "slow_drip",
        "quiet": "quiet",
        "verbose": "verbose",
    }

    applied_keys = getattr(args, "_run_config_keys", set())
    for key, value in cfg.items():
        arg_key = aliases.get(key, key)
        if arg_key not in args.__dict__:
            continue
        if arg_key in provided_flags:
            continue
        setattr(args, arg_key, value)
        applied_keys.add(arg_key)

    setattr(args, "_run_config_keys", applied_keys)
    return args


def load_fetch_profiles() -> dict:
    """Load fetch method profiles from profiles/fetch_profiles.yaml if present."""
    profiles_path = PROJECT_ROOT / "profiles" / "fetch_profiles.yaml"
    if not profiles_path.exists():
        return {}
    try:
        import yaml
    except Exception:
        return {}
    try:
        data = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
