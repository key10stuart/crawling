"""
Cookie loading utilities for Playwright sessions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class CookieStatus:
    path: str | None
    exists: bool
    expired: bool
    expires_at: str | None
    warning: str | None


def _resolve_cookie_path(cookie_ref: str, cookies_dir: Path | None = None) -> Path:
    ref_path = Path(cookie_ref)
    if ref_path.suffix.lower() == ".json" or ref_path.is_absolute() or len(ref_path.parts) > 1:
        return ref_path
    base_dir = cookies_dir or (Path.home() / ".crawl" / "cookies")
    return base_dir / f"{cookie_ref}.json"


def inspect_cookies(cookie_ref: str | None, cookies_dir: Path | None = None) -> CookieStatus:
    if not cookie_ref:
        return CookieStatus(path=None, exists=False, expired=False, expires_at=None, warning=None)

    path = _resolve_cookie_path(cookie_ref, cookies_dir=cookies_dir)
    if not path.exists():
        return CookieStatus(path=str(path), exists=False, expired=False, expires_at=None, warning="cookie_file_missing")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return CookieStatus(path=str(path), exists=True, expired=False, expires_at=None, warning="cookie_file_invalid")

    expires = []
    for cookie in raw if isinstance(raw, list) else []:
        exp = cookie.get("expires")
        if isinstance(exp, (int, float)) and exp > 0:
            expires.append(exp)

    if not expires:
        return CookieStatus(path=str(path), exists=True, expired=False, expires_at=None, warning=None)

    earliest = min(expires)
    expires_at = datetime.fromtimestamp(earliest, tz=timezone.utc).isoformat()
    expired = earliest < datetime.now(timezone.utc).timestamp()
    warning = "cookie_expired" if expired else None
    return CookieStatus(path=str(path), exists=True, expired=expired, expires_at=expires_at, warning=warning)


def load_cookies(cookie_ref: str | None, cookies_dir: Path | None = None) -> list[dict[str, Any]] | None:
    if not cookie_ref:
        return None

    path = _resolve_cookie_path(cookie_ref, cookies_dir=cookies_dir)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(data, list):
        return None

    now_ts = datetime.now(timezone.utc).timestamp()
    filtered = []
    for cookie in data:
        exp = cookie.get("expires")
        if isinstance(exp, (int, float)) and exp > 0 and exp < now_ts:
            continue
        filtered.append(cookie)

    return filtered
