"""
Persistent per-domain access strategy cache.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_PATH = PROJECT_ROOT / "corpus" / "access" / "strategy_cache.json"


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def get_cached_strategy(domain: str, cache_path: Path | None = None, max_age_days: int = 30) -> str | None:
    cache_path = cache_path or DEFAULT_CACHE_PATH
    cache = _load_cache(cache_path)
    entry = cache.get(domain)
    if not entry:
        return None
    updated_at = entry.get("updated_at")
    if updated_at:
        try:
            ts = datetime.fromisoformat(updated_at)
            if datetime.now(timezone.utc) - ts > timedelta(days=max_age_days):
                return None
        except Exception:
            return None
    return entry.get("last_success_method")


def update_strategy_cache(
    domain: str,
    method: str | None,
    success: bool,
    block_signals: list[str] | None = None,
    cache_path: Path | None = None,
) -> None:
    cache_path = cache_path or DEFAULT_CACHE_PATH
    cache = _load_cache(cache_path)
    entry = cache.get(domain, {})
    now = datetime.now(timezone.utc).isoformat()

    if method:
        if success:
            entry["last_success_method"] = method
        else:
            entry["last_fail_method"] = method
    if block_signals:
        entry["last_seen_block"] = list(set(block_signals))

    entry["updated_at"] = now
    cache[domain] = entry
    _save_cache(cache_path, cache)
