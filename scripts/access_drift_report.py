#!/usr/bin/env python3
"""
Access Drift Report - Detect content and access method drift between runs.

Tracks:
- Content drift: word count changes, missing pages
- Access drift: method changes, new blocks
- Quality drift: extraction quality changes

Usage:
    python scripts/access_drift_report.py
    python scripts/access_drift_report.py --domain schneider.com
    python scripts/access_drift_report.py --threshold 0.3  # 30% change threshold
    python scripts/access_drift_report.py --json
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SEEDS_FILE = PROJECT_ROOT / "seeds" / "trucking_carriers.json"
SITES_DIR = PROJECT_ROOT / "corpus" / "sites"
DRIFT_HISTORY_FILE = PROJECT_ROOT / "corpus" / "drift_history.json"


def load_seeds() -> list[dict]:
    """Load carrier seeds."""
    if not SEEDS_FILE.exists():
        return []
    data = json.loads(SEEDS_FILE.read_text())
    return data.get("carriers", [])


def load_site_data(domain: str) -> dict | None:
    """Load current crawl data for a domain."""
    filename = domain.replace(".", "_").replace("/", "_") + ".json"
    filepath = SITES_DIR / filename

    if not filepath.exists():
        for f in SITES_DIR.glob(f"{domain.split('.')[0]}*.json"):
            if not f.name.endswith("_summary.json"):
                filepath = f
                break

    if not filepath.exists():
        return None

    try:
        return json.loads(filepath.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def load_drift_history() -> dict:
    """Load drift history from file."""
    if not DRIFT_HISTORY_FILE.exists():
        return {"snapshots": {}}
    try:
        return json.loads(DRIFT_HISTORY_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"snapshots": {}}


def save_drift_history(history: dict):
    """Save drift history to file."""
    DRIFT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    DRIFT_HISTORY_FILE.write_text(json.dumps(history, indent=2))


def extract_snapshot(site_data: dict) -> dict:
    """Extract key metrics from site data for comparison."""
    if not site_data:
        return None

    access = site_data.get("access", {})
    pages = site_data.get("pages", [])

    # Page-level metrics
    page_words = {p.get("url", ""): p.get("word_count", 0) for p in pages}
    page_urls = set(page_words.keys())

    return {
        "domain": site_data.get("domain", ""),
        "crawl_start": site_data.get("crawl_start", site_data.get("snapshot_date", "")),
        "total_words": site_data.get("total_word_count", 0),
        "total_pages": len(pages),
        "page_urls": list(page_urls),
        "page_words": page_words,
        "strategy": access.get("strategy", "unknown"),
        "blocked": access.get("blocked", False),
        "recon_cdn": access.get("recon", {}).get("cdn", ""),
        "escalations": access.get("escalations", []),
    }


def compare_snapshots(old: dict, new: dict, threshold: float = 0.3) -> dict:
    """
    Compare two snapshots and detect drift.

    Args:
        old: Previous snapshot
        new: Current snapshot
        threshold: Percentage change threshold for alerts

    Returns:
        Dict with drift metrics and alerts
    """
    if old is None or new is None:
        return {"error": "missing_snapshot"}

    drift = {
        "domain": new["domain"],
        "old_date": old.get("crawl_start", ""),
        "new_date": new.get("crawl_start", ""),
        "alerts": [],
        "metrics": {},
    }

    # Content drift: word count change
    old_words = old.get("total_words", 0)
    new_words = new.get("total_words", 0)

    if old_words > 0:
        word_change = (new_words - old_words) / old_words
        drift["metrics"]["word_change_pct"] = word_change

        if word_change < -threshold:
            drift["alerts"].append({
                "type": "content_drop",
                "severity": "high" if word_change < -0.5 else "medium",
                "detail": f"Word count dropped {abs(word_change):.1%} ({old_words} -> {new_words})",
            })
        elif word_change > threshold:
            drift["alerts"].append({
                "type": "content_increase",
                "severity": "low",
                "detail": f"Word count increased {word_change:.1%}",
            })

    # Page drift: missing/new pages
    old_urls = set(old.get("page_urls", []))
    new_urls = set(new.get("page_urls", []))

    missing_pages = old_urls - new_urls
    new_pages = new_urls - old_urls

    drift["metrics"]["pages_missing"] = len(missing_pages)
    drift["metrics"]["pages_new"] = len(new_pages)
    drift["metrics"]["old_page_count"] = len(old_urls)
    drift["metrics"]["new_page_count"] = len(new_urls)

    if len(missing_pages) > 0 and len(old_urls) > 0:
        missing_pct = len(missing_pages) / len(old_urls)
        if missing_pct > threshold:
            drift["alerts"].append({
                "type": "pages_missing",
                "severity": "high" if missing_pct > 0.5 else "medium",
                "detail": f"{len(missing_pages)} pages missing ({missing_pct:.1%})",
                "pages": list(missing_pages)[:10],
            })

    # Access drift: method change
    old_strategy = old.get("strategy", "unknown")
    new_strategy = new.get("strategy", "unknown")

    if old_strategy != new_strategy:
        drift["metrics"]["strategy_changed"] = True
        drift["metrics"]["old_strategy"] = old_strategy
        drift["metrics"]["new_strategy"] = new_strategy

        # Check if change correlates with quality drop
        if word_change < -threshold:
            drift["alerts"].append({
                "type": "access_degradation",
                "severity": "high",
                "detail": f"Strategy changed ({old_strategy} -> {new_strategy}) with content drop",
            })
        else:
            drift["alerts"].append({
                "type": "strategy_change",
                "severity": "low",
                "detail": f"Strategy changed: {old_strategy} -> {new_strategy}",
            })

    # Block status change
    old_blocked = old.get("blocked", False)
    new_blocked = new.get("blocked", False)

    if not old_blocked and new_blocked:
        drift["alerts"].append({
            "type": "new_block",
            "severity": "high",
            "detail": "Site became blocked",
        })
    elif old_blocked and not new_blocked:
        drift["alerts"].append({
            "type": "block_resolved",
            "severity": "low",
            "detail": "Block resolved",
        })

    return drift


def analyze_all_drift(threshold: float = 0.3, domain_filter: str = None) -> list[dict]:
    """
    Analyze drift for all domains or a specific domain.

    Args:
        threshold: Change threshold for alerts
        domain_filter: Optional domain to filter to

    Returns:
        List of drift reports
    """
    history = load_drift_history()
    carriers = load_seeds()
    results = []

    for carrier in carriers:
        domain = carrier.get("domain", "")
        if "/" in domain:
            domain = domain.split("/")[0]

        if domain_filter and domain != domain_filter:
            continue

        # Load current data
        site_data = load_site_data(domain)
        if site_data is None:
            continue

        # Extract current snapshot
        current = extract_snapshot(site_data)
        if current is None:
            continue

        # Get previous snapshot from history
        previous = history.get("snapshots", {}).get(domain)

        if previous:
            # Compare
            drift = compare_snapshots(previous, current, threshold)
            drift["tier"] = carrier.get("tier", 3)
            drift["name"] = carrier.get("name", domain)
            results.append(drift)

        # Update history with current snapshot
        if "snapshots" not in history:
            history["snapshots"] = {}
        history["snapshots"][domain] = current

    # Save updated history
    save_drift_history(history)

    return results


def format_report(drifts: list[dict]) -> str:
    """Format human-readable drift report."""
    lines = []
    lines.append("=" * 60)
    lines.append("ACCESS DRIFT REPORT")
    lines.append("=" * 60)
    lines.append("")

    # Summary
    total = len(drifts)
    with_alerts = sum(1 for d in drifts if d.get("alerts"))
    high_severity = sum(1 for d in drifts for a in d.get("alerts", []) if a.get("severity") == "high")

    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"Domains compared: {total}")
    lines.append(f"With drift alerts: {with_alerts}")
    lines.append(f"High severity alerts: {high_severity}")
    lines.append("")

    # High severity alerts
    high_alerts = [(d, a) for d in drifts for a in d.get("alerts", []) if a.get("severity") == "high"]
    if high_alerts:
        lines.append("HIGH SEVERITY ALERTS")
        lines.append("-" * 40)
        for drift, alert in high_alerts:
            tier = drift.get("tier", "?")
            domain = drift.get("domain", "unknown")
            lines.append(f"  T{tier} {domain}")
            lines.append(f"      {alert['type']}: {alert['detail']}")
        lines.append("")

    # Medium severity alerts
    med_alerts = [(d, a) for d in drifts for a in d.get("alerts", []) if a.get("severity") == "medium"]
    if med_alerts:
        lines.append("MEDIUM SEVERITY ALERTS")
        lines.append("-" * 40)
        for drift, alert in med_alerts:
            domain = drift.get("domain", "unknown")
            lines.append(f"  {domain}: {alert['type']} - {alert['detail']}")
        lines.append("")

    # Content changes summary
    content_changes = [(d["domain"], d["metrics"].get("word_change_pct", 0))
                       for d in drifts if "word_change_pct" in d.get("metrics", {})]
    if content_changes:
        lines.append("CONTENT CHANGES")
        lines.append("-" * 40)
        # Sort by absolute change
        content_changes.sort(key=lambda x: abs(x[1]), reverse=True)
        for domain, change in content_changes[:15]:
            arrow = "+" if change > 0 else ""
            lines.append(f"  {domain:35} {arrow}{change:.1%}")
        lines.append("")

    # Strategy changes
    strategy_changes = [d for d in drifts if d.get("metrics", {}).get("strategy_changed")]
    if strategy_changes:
        lines.append("STRATEGY CHANGES")
        lines.append("-" * 40)
        for d in strategy_changes:
            m = d["metrics"]
            lines.append(f"  {d['domain']}: {m['old_strategy']} -> {m['new_strategy']}")
        lines.append("")

    if not with_alerts:
        lines.append("No significant drift detected.")
        lines.append("")

    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("=" * 60)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Access Drift Report - Detect changes between crawl runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("--domain", "-d", help="Filter to specific domain")
    parser.add_argument("--threshold", "-t", type=float, default=0.3,
                        help="Change threshold for alerts (default: 0.3 = 30%%)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--reset", action="store_true", help="Reset drift history")

    args = parser.parse_args()

    if args.reset:
        if DRIFT_HISTORY_FILE.exists():
            DRIFT_HISTORY_FILE.unlink()
            print("Drift history reset.")
        else:
            print("No drift history to reset.")
        return

    # Run analysis
    drifts = analyze_all_drift(threshold=args.threshold, domain_filter=args.domain)

    # Output
    if args.json:
        print(json.dumps(drifts, indent=2))
    else:
        print(format_report(drifts))


if __name__ == "__main__":
    main()
