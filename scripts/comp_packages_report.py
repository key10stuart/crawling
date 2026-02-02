#!/usr/bin/env python3
"""
Generate a human-readable report of driver/owner-operator/carrier inducements.

Usage:
  python scripts/comp_packages_report.py --site corpus/sites/jbhunt_com.json
  python scripts/comp_packages_report.py --sites corpus/sites/*.json
  python scripts/comp_packages_report.py --sites corpus/sites/*.json --out corpus/reports/comp_packages.md
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).parent.parent))

from fetch import nlp as nlp_utils


BUCKETS = {
    "drivers": [
        "driver", "drivers", "cdl", "cpm", "cents per mile", "pay", "compensation",
        "sign-on", "sign on", "bonus", "bonuses", "benefits", "per diem", "home time",
        "tuition", "training", "detention", "layover", "accessorial", "guaranteed pay",
    ],
    "owner_operators": [
        "owner operator", "owner-operator", "lease", "lease to own", "lease-to-own",
        "truck payment", "settlement", "fuel surcharge", "fuel card", "escrow",
        "maintenance", "deduction", "deductions", "plate program",
    ],
    "carriers": [
        "carrier", "carriers", "partner carrier", "broker", "brokerage",
        "load board", "quick pay", "fast pay", "fuel card", "factoring",
        "onboarding", "authority", "insurance", "edi", "tms",
    ],
}


def _read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _collect_hits(text: str, keywords: list[str]) -> list[str]:
    hits = []
    lower = text.lower()
    if not any(k in lower for k in keywords):
        return hits
    for s in _sentences(text):
        s_lower = s.lower()
        if any(k in s_lower for k in keywords):
            hits.append(s)
    return hits[:5]


def _classify_page(page: dict) -> dict[str, list[str]]:
    text = " ".join([
        page.get("title") or "",
        page.get("h1") or "",
        page.get("full_text") or "",
    ])
    results: dict[str, list[str]] = {}

    try:
        nlp_data = nlp_utils.extract_all_lightweight(text)
        audience = nlp_data.get("audience")
        money_scored = nlp_data.get("money_all_scored", [])
        comp_keywords = nlp_data.get("comp_keywords", {})

        # Map audience to a bucket if strong signal
        if audience in results or audience is None:
            pass
        elif audience in ("drivers", "owner_operators", "carriers"):
            results[audience] = []

        # Use high-confidence money mentions as snippets
        for m in money_scored:
            conf = m.get("comp_confidence", 0.0)
            if conf < 0.4:
                continue
            snippet = m.get("context") or m.get("raw") or ""
            if not snippet:
                continue
            if audience in ("drivers", "owner_operators", "carriers"):
                results.setdefault(audience, []).append(snippet)
            else:
                # If audience unknown, attach to drivers as default comp bucket
                results.setdefault("drivers", []).append(snippet)

        # Add keyword-based sentences for all buckets
        for bucket, keywords in BUCKETS.items():
            hits = _collect_hits(text, keywords)
            if hits:
                results.setdefault(bucket, []).extend(hits)

        # Add comp keyword category matches as hints
        if comp_keywords:
            for bucket in ("drivers", "owner_operators", "carriers"):
                if bucket in results:
                    results[bucket].extend([f"Keywords: {', '.join(sorted(comp_keywords.keys()))}"])

        # De-dupe and trim
        for bucket in list(results.keys()):
            deduped = []
            seen = set()
            for h in results[bucket]:
                if h not in seen:
                    seen.add(h)
                    deduped.append(h)
            results[bucket] = deduped[:6]

    except Exception:
        # Fallback to simple keyword matching
        for bucket, keywords in BUCKETS.items():
            hits = _collect_hits(text, keywords)
            if hits:
                results[bucket] = hits

    return results


def _collect_page_hits(page: dict) -> list[dict]:
    """Collect snippets with URLs for diffing."""
    items = []
    classified = _classify_page(page)
    url = page.get("url", "")
    changed = page.get("changed_since_last")
    for bucket, hits in classified.items():
        for h in hits:
            items.append({
                "bucket": bucket,
                "url": url,
                "snippet": h,
                "changed_since_last": changed,
            })
    return items


def _render_site(site: dict) -> str:
    lines = []
    domain = site.get("domain", "unknown")
    company = site.get("company_name", domain)
    lines.append(f"## {company} ({domain})")

    pages = site.get("pages", [])
    bucket_hits = {k: [] for k in BUCKETS.keys()}

    for p in pages:
        classified = _classify_page(p)
        if not classified:
            continue
        url = p.get("url", "")
        changed = p.get("changed_since_last")
        changed_tag = ""
        if changed is True:
            changed_tag = " **(changed)**"
        elif changed is False:
            changed_tag = " _(unchanged)_"
        for bucket, hits in classified.items():
            bucket_hits[bucket].append((url, hits, changed_tag))

    for bucket, items in bucket_hits.items():
        title = bucket.replace("_", " ").title()
        lines.append(f"### {title}")
        if not items:
            lines.append("- No clear signals found.")
            continue
        for url, hits, changed_tag in items:
            lines.append(f"- {url}{changed_tag}")
            for h in hits:
                lines.append(f"  - “{h}”")

    lines.append("")
    return "\n".join(lines)


def _expand_sites(values: Iterable[str]) -> list[Path]:
    paths = []
    for v in values:
        if "*" in v:
            paths.extend(Path(".").glob(v))
        else:
            paths.append(Path(v))
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate comp package report from crawl JSON.")
    parser.add_argument("--site", action="append", help="Single site JSON (repeatable)")
    parser.add_argument("--sites", nargs="*", help="Glob(s) for site JSON files")
    parser.add_argument("--out", help="Output markdown path")
    parser.add_argument("--out-json", action="store_true", help="Also write JSON output")
    parser.add_argument("--diff", nargs=2, metavar=("OLD", "NEW"),
                        help="Generate diff report between two JSON reports")
    args = parser.parse_args()

    if args.diff:
        old_path, new_path = args.diff
        old = json.loads(Path(old_path).read_text(encoding="utf-8"))
        new = json.loads(Path(new_path).read_text(encoding="utf-8"))
        _write_diff_report(old, new)
        return

    site_paths = []
    if args.site:
        site_paths.extend([Path(p) for p in args.site])
    if args.sites:
        site_paths.extend(_expand_sites(args.sites))
    if not site_paths:
        raise SystemExit("No sites provided. Use --site or --sites.")

    site_paths = sorted({p for p in site_paths if p.exists()})
    if not site_paths:
        raise SystemExit("No valid site files found.")

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = Path(args.out) if args.out else Path("corpus/reports") / f"comp_packages_{date_str}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append(f"# Compensation & Inducements Report ({date_str})")
    lines.append("")
    lines.append("Buckets: Drivers, Owner Operators, Carriers")
    lines.append("")

    json_out = {
        "date": date_str,
        "buckets": list(BUCKETS.keys()),
        "sites": [],
    }

    for p in site_paths:
        site = _read_json(p)
        lines.append(_render_site(site))
        # Build JSON structure
        site_entry = {
            "domain": site.get("domain"),
            "company_name": site.get("company_name"),
            "buckets": {k: [] for k in BUCKETS.keys()},
            "hits": [],
        }
        for page in site.get("pages", []):
            classified = _classify_page(page)
            if not classified:
                continue
            url = page.get("url", "")
            changed = page.get("changed_since_last")
            for bucket, hits in classified.items():
                site_entry["buckets"][bucket].append({
                    "url": url,
                    "changed_since_last": changed,
                    "snippets": hits,
                })
            site_entry["hits"].extend(_collect_page_hits(page))
        json_out["sites"].append(site_entry)

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote report: {out_path}")
    if args.out_json:
        json_path = out_path.with_suffix(".json")
        json_path.write_text(json.dumps(json_out, indent=2), encoding="utf-8")
        print(f"Wrote report: {json_path}")


def _write_diff_report(old: dict, new: dict) -> None:
    """Write a diff markdown report between two JSON outputs."""
    def key(h):
        return (h.get("bucket"), h.get("url"), h.get("snippet"))

    old_sites = {s.get("domain"): s for s in old.get("sites", [])}
    new_sites = {s.get("domain"): s for s in new.get("sites", [])}

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = Path("corpus/reports") / f"comp_packages_diff_{date_str}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append(f"# Compensation Diff Report ({date_str})")
    lines.append("")

    for domain, new_site in new_sites.items():
        old_site = old_sites.get(domain, {})
        old_hits = {key(h) for h in old_site.get("hits", [])}
        new_hits = {key(h) for h in new_site.get("hits", [])}

        added = new_hits - old_hits
        removed = old_hits - new_hits

        if not added and not removed:
            continue

        company = new_site.get("company_name", domain)
        lines.append(f"## {company} ({domain})")

        if added:
            lines.append("### Added")
            for bucket, url, snippet in sorted(added):
                lines.append(f"- [{bucket}] {url}")
                lines.append(f"  - “{snippet}”")
        if removed:
            lines.append("### Removed")
            for bucket, url, snippet in sorted(removed):
                lines.append(f"- [{bucket}] {url}")
                lines.append(f"  - “{snippet}”")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote report: {out_path}")


if __name__ == "__main__":
    main()
