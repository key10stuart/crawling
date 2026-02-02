#!/usr/bin/env python3
"""
Access Report - Analytics for crawl access layer.

Produces metrics for SLO monitoring:
- Success rate by tier
- Block rate
- Method distribution (http/js/stealth/monkey_do)
- Top blocked domains
- Crawl freshness

Usage:
    python scripts/access_report.py
    python scripts/access_report.py --tier 1
    python scripts/access_report.py --metric success_rate
    python scripts/access_report.py --json
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SEEDS_FILE = PROJECT_ROOT / "seeds" / "trucking_carriers.json"
SITES_DIR = PROJECT_ROOT / "corpus" / "sites"


def load_seeds() -> dict:
    """Load carrier seeds file."""
    if not SEEDS_FILE.exists():
        return {"carriers": []}
    return json.loads(SEEDS_FILE.read_text())


def load_site_data(domain: str) -> dict | None:
    """Load crawl data for a domain."""
    # Normalize domain to filename
    filename = domain.replace(".", "_").replace("/", "_") + ".json"
    filepath = SITES_DIR / filename

    if not filepath.exists():
        # Try alternate patterns
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


def get_crawl_age_days(site_data: dict) -> float | None:
    """Get age of crawl in days."""
    crawl_start = site_data.get("crawl_start")
    if not crawl_start:
        # Fall back to snapshot_date
        snapshot = site_data.get("snapshot_date")
        if snapshot:
            try:
                dt = datetime.strptime(snapshot, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
            except ValueError:
                pass
        return None

    try:
        dt = datetime.fromisoformat(crawl_start.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except ValueError:
        return None


def analyze_access() -> dict:
    """
    Analyze access metrics across all crawled sites.

    Returns dict with:
    - by_tier: {tier: {success, failed, blocked, total}}
    - by_method: {method: count}
    - blocked_domains: [(domain, reason)]
    - freshness: {fresh, stale, missing}
    - escalations: Counter of escalation patterns
    """
    seeds = load_seeds()
    carriers = seeds.get("carriers", [])

    # Track metrics
    by_tier = defaultdict(lambda: {"success": 0, "failed": 0, "blocked": 0, "total": 0})
    by_method = Counter()
    blocked_domains = []
    freshness = {"fresh": 0, "stale": 0, "missing": 0}
    escalations = Counter()
    word_counts = []
    page_counts = []

    for carrier in carriers:
        domain = carrier.get("domain", "")
        tier = carrier.get("tier", 3)
        name = carrier.get("name", domain)

        # Skip URLs with paths (they're not root domains)
        if "/" in domain:
            base_domain = domain.split("/")[0]
        else:
            base_domain = domain

        by_tier[tier]["total"] += 1

        # Load crawl data
        site_data = load_site_data(base_domain)

        if site_data is None:
            by_tier[tier]["failed"] += 1
            freshness["missing"] += 1
            blocked_domains.append((base_domain, "no_crawl_data", tier, name))
            continue

        # Check success (has pages with content)
        pages = site_data.get("pages", [])
        total_words = site_data.get("total_word_count", 0)

        if len(pages) == 0 or total_words < 100:
            by_tier[tier]["failed"] += 1
            blocked_domains.append((base_domain, "low_content", tier, name))
        else:
            by_tier[tier]["success"] += 1
            word_counts.append(total_words)
            page_counts.append(len(pages))

        # Check blocked status
        access = site_data.get("access", {})
        if access.get("blocked"):
            by_tier[tier]["blocked"] += 1
            reason = access.get("notes", "unknown")
            blocked_domains.append((base_domain, reason, tier, name))

        # Track method used
        method = access.get("strategy", "unknown")
        by_method[method] += 1

        # Track escalations
        site_escalations = access.get("escalations", [])
        for esc in site_escalations:
            escalations[esc] += 1

        # Check freshness (stale if >30 days old)
        age = get_crawl_age_days(site_data)
        if age is None:
            freshness["missing"] += 1
        elif age > 30:
            freshness["stale"] += 1
        else:
            freshness["fresh"] += 1

    return {
        "by_tier": dict(by_tier),
        "by_method": dict(by_method),
        "blocked_domains": blocked_domains,
        "freshness": freshness,
        "escalations": dict(escalations),
        "word_counts": word_counts,
        "page_counts": page_counts,
        "total_carriers": len(carriers),
    }


def compute_metrics(analysis: dict) -> dict:
    """Compute SLO metrics from analysis."""
    metrics = {}

    # Success rate by tier
    for tier, stats in analysis["by_tier"].items():
        total = stats["total"]
        if total > 0:
            metrics[f"tier{tier}_success_rate"] = stats["success"] / total
            metrics[f"tier{tier}_block_rate"] = stats["blocked"] / total

    # Overall success rate
    total_success = sum(s["success"] for s in analysis["by_tier"].values())
    total_all = sum(s["total"] for s in analysis["by_tier"].values())
    if total_all > 0:
        metrics["overall_success_rate"] = total_success / total_all

    # Block rate
    total_blocked = sum(s["blocked"] for s in analysis["by_tier"].values())
    if total_all > 0:
        metrics["overall_block_rate"] = total_blocked / total_all

    # Method efficiency (% using http only)
    method_counts = analysis["by_method"]
    total_methods = sum(method_counts.values())
    if total_methods > 0:
        http_count = method_counts.get("http", 0) + method_counts.get("requests", 0)
        metrics["http_efficiency"] = http_count / total_methods

    # Freshness
    fresh = analysis["freshness"]
    total_fresh = fresh["fresh"] + fresh["stale"]
    if total_fresh > 0:
        metrics["freshness_rate"] = fresh["fresh"] / total_fresh

    # Average content
    if analysis["word_counts"]:
        metrics["avg_words"] = sum(analysis["word_counts"]) / len(analysis["word_counts"])
    if analysis["page_counts"]:
        metrics["avg_pages"] = sum(analysis["page_counts"]) / len(analysis["page_counts"])

    return metrics


def format_report(analysis: dict, metrics: dict, tier_filter: int | None = None) -> str:
    """Format human-readable report."""
    lines = []
    lines.append("=" * 60)
    lines.append("ACCESS LAYER REPORT")
    lines.append("=" * 60)
    lines.append("")

    # Summary
    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"Total carriers in seeds: {analysis['total_carriers']}")
    lines.append(f"Overall success rate: {metrics.get('overall_success_rate', 0):.1%}")
    lines.append(f"Overall block rate: {metrics.get('overall_block_rate', 0):.1%}")
    lines.append(f"HTTP efficiency: {metrics.get('http_efficiency', 0):.1%}")
    lines.append("")

    # By tier
    lines.append("BY TIER")
    lines.append("-" * 40)
    for tier in sorted(analysis["by_tier"].keys()):
        if tier_filter is not None and tier != tier_filter:
            continue
        stats = analysis["by_tier"][tier]
        rate = stats["success"] / stats["total"] if stats["total"] > 0 else 0
        lines.append(f"Tier {tier}: {stats['success']}/{stats['total']} ({rate:.1%}) success")
        lines.append(f"         {stats['blocked']} blocked, {stats['failed']} failed")
    lines.append("")

    # Method distribution
    lines.append("METHOD DISTRIBUTION")
    lines.append("-" * 40)
    for method, count in sorted(analysis["by_method"].items(), key=lambda x: -x[1]):
        pct = count / sum(analysis["by_method"].values()) if analysis["by_method"] else 0
        lines.append(f"  {method:20} {count:4} ({pct:.1%})")
    lines.append("")

    # Escalations
    if analysis["escalations"]:
        lines.append("ESCALATION PATTERNS")
        lines.append("-" * 40)
        for pattern, count in sorted(analysis["escalations"].items(), key=lambda x: -x[1])[:10]:
            lines.append(f"  {pattern:30} {count}")
        lines.append("")

    # Blocked domains
    blocked = analysis["blocked_domains"]
    if blocked:
        lines.append(f"BLOCKED/FAILED DOMAINS ({len(blocked)})")
        lines.append("-" * 40)
        # Sort by tier then domain
        for domain, reason, tier, name in sorted(blocked, key=lambda x: (x[2], x[0])):
            if tier_filter is not None and tier != tier_filter:
                continue
            lines.append(f"  T{tier} {domain:30} {reason[:40]}")
        lines.append("")

    # Freshness
    fresh = analysis["freshness"]
    lines.append("FRESHNESS")
    lines.append("-" * 40)
    lines.append(f"  Fresh (<30d):  {fresh['fresh']}")
    lines.append(f"  Stale (>30d):  {fresh['stale']}")
    lines.append(f"  Missing:       {fresh['missing']}")
    lines.append("")

    # SLO status
    lines.append("SLO STATUS")
    lines.append("-" * 40)

    def slo_status(value: float, green: float, yellow: float, higher_is_better: bool = True) -> str:
        if higher_is_better:
            if value >= green:
                return "GREEN"
            elif value >= yellow:
                return "YELLOW"
            else:
                return "RED"
        else:
            if value <= green:
                return "GREEN"
            elif value <= yellow:
                return "YELLOW"
            else:
                return "RED"

    t1_success = metrics.get("tier1_success_rate", 0)
    lines.append(f"  Tier-1 Success Rate: {t1_success:.1%} [{slo_status(t1_success, 0.95, 0.90)}]")

    block_rate = metrics.get("overall_block_rate", 0)
    lines.append(f"  Block Rate: {block_rate:.1%} [{slo_status(block_rate, 0.10, 0.20, False)}]")

    http_eff = metrics.get("http_efficiency", 0)
    lines.append(f"  HTTP Efficiency: {http_eff:.1%} [{slo_status(http_eff, 0.60, 0.40)}]")

    fresh_rate = metrics.get("freshness_rate", 0)
    lines.append(f"  Freshness Rate: {fresh_rate:.1%} [{slo_status(fresh_rate, 1.0, 0.90)}]")

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Access Report - Crawl access layer analytics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("--tier", type=int, help="Filter to specific tier")
    parser.add_argument("--metric", help="Output single metric value")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    # Run analysis
    analysis = analyze_access()
    metrics = compute_metrics(analysis)

    # Output
    if args.metric:
        value = metrics.get(args.metric)
        if value is not None:
            print(f"{value:.4f}")
        else:
            print(f"Unknown metric: {args.metric}")
            print(f"Available: {', '.join(metrics.keys())}")
            sys.exit(1)
    elif args.json:
        output = {
            "analysis": {
                "by_tier": analysis["by_tier"],
                "by_method": analysis["by_method"],
                "freshness": analysis["freshness"],
                "escalations": analysis["escalations"],
                "blocked_count": len(analysis["blocked_domains"]),
            },
            "metrics": metrics,
            "generated": datetime.now(timezone.utc).isoformat(),
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_report(analysis, metrics, tier_filter=args.tier))


if __name__ == "__main__":
    main()
