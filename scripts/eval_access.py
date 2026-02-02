#!/usr/bin/env python3
"""
Interactive Access Layer Evaluation.

Test the full adaptive access system with zero configuration.
Auto-selects sites, runs recon, shows strategy decisions, crawls,
and tracks SLO metrics - all with interactive prompts.

Usage:
    python scripts/eval_access.py              # Just run it
    python scripts/eval_access.py --tier 2     # Test tier-2 sites
    python scripts/eval_access.py --domain schneider.com  # Single site
    python scripts/eval_access.py --sample-size 3         # Quick test

The goal: validate the access layer works without needing to remember
any command-line arguments or read documentation.
"""

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

from fetch.recon import recon_site, ReconResult

# Strategy recommendation logic (mirrors crawl.py)
def recommend_strategy(recon: ReconResult | None, cached: str | None) -> tuple[str, str]:
    """Recommend fetch strategy based on recon. Returns (method, source)."""
    if cached:
        return cached, "cache"

    if not recon:
        return "requests", "default"

    # Challenge or aggressive WAF -> stealth
    if recon.challenge_detected or recon.cdn in ("cloudflare", "stackpath"):
        return "stealth", "recon_block"

    # JS required -> js
    if recon.js_required:
        return "js", "recon_js"

    return "requests", "default"
from fetch.strategy_cache import get_cached_strategy
from fetch.cookies import inspect_cookies
from fetch.monkey import (
    add_to_monkey_queue,
    list_queue,
    has_flow,
    get_flow_age_days,
)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
SEEDS_FILE = PROJECT_ROOT / "seeds" / "trucking_carriers.json"
CONFIG_FILE = PROJECT_ROOT / "profiles" / "eval_config.yaml"
SITES_DIR = PROJECT_ROOT / "corpus" / "sites"


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class EvalConfig:
    """Configuration for eval session."""
    default_tier: int = 1
    sample_size: int = 5
    include_known_hard: bool = True
    shuffle: bool = True
    depth: int = 0
    auto_escalate: bool = True
    timeout_sec: int = 60
    confirm_strategy: bool = True
    on_block: str = "prompt"  # prompt | auto_queue | skip
    show_recon_details: bool = True
    pause_between_sites: bool = True
    track_slos: bool = True
    warn_on_slo_breach: bool = True


def load_config() -> tuple[EvalConfig, list[str], list[str]]:
    """Load config from YAML or use defaults."""
    config = EvalConfig()
    known_hard = []
    skip_sites = []

    if CONFIG_FILE.exists():
        try:
            data = yaml.safe_load(CONFIG_FILE.read_text())
            if data:
                ec = data.get("eval_access", {})
                for key, val in ec.items():
                    if hasattr(config, key):
                        setattr(config, key, val)
                known_hard = data.get("known_hard_sites", [])
                skip_sites = data.get("skip_sites", [])
        except Exception:
            pass

    return config, known_hard, skip_sites


# =============================================================================
# SITE SELECTION
# =============================================================================

def load_seeds() -> list[dict]:
    """Load carrier seed list."""
    with open(SEEDS_FILE) as f:
        data = json.load(f)
    return data.get("carriers", [])


def select_sites(
    config: EvalConfig,
    known_hard: list[str],
    skip_sites: list[str],
    tier_override: int | None = None,
    domain_override: str | None = None,
) -> list[dict]:
    """Select sites for evaluation based on config."""
    carriers = load_seeds()

    # Single domain override
    if domain_override:
        matches = [c for c in carriers if c["domain"] == domain_override]
        if not matches:
            # Create ad-hoc entry
            return [{"domain": domain_override, "name": domain_override, "tier": 0, "category": []}]
        return matches

    # Filter by tier
    tier = tier_override or config.default_tier
    tier_carriers = [c for c in carriers if c.get("tier") == tier]

    # Remove skip sites
    skip_set = set(skip_sites)
    tier_carriers = [c for c in tier_carriers if c["domain"] not in skip_set]

    if not tier_carriers:
        # Fall back to all tiers
        tier_carriers = [c for c in carriers if c["domain"] not in skip_set]

    # Shuffle if requested
    if config.shuffle:
        random.shuffle(tier_carriers)

    # Select sample
    selected = tier_carriers[:config.sample_size]

    # Ensure at least one known-hard site if configured
    if config.include_known_hard and known_hard:
        has_hard = any(c["domain"] in known_hard for c in selected)
        if not has_hard:
            # Find a hard site and swap one in
            hard_candidates = [c for c in carriers if c["domain"] in known_hard]
            if hard_candidates:
                hard_site = random.choice(hard_candidates)
                if len(selected) >= config.sample_size:
                    selected[-1] = hard_site
                else:
                    selected.append(hard_site)

    return selected


# =============================================================================
# SLO TRACKING
# =============================================================================

@dataclass
class SLOTracker:
    """Track SLO metrics during evaluation."""
    total_attempts: int = 0
    successful: int = 0
    blocked: int = 0
    method_counts: dict = field(default_factory=dict)

    def record(self, success: bool, blocked: bool, method: str):
        self.total_attempts += 1
        if success:
            self.successful += 1
        if blocked:
            self.blocked += 1
        self.method_counts[method] = self.method_counts.get(method, 0) + 1

    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return self.successful / self.total_attempts

    @property
    def block_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return self.blocked / self.total_attempts

    @property
    def http_efficiency(self) -> float:
        """Percentage of successes using HTTP-only (no Playwright)."""
        if self.successful == 0:
            return 0.0
        http_count = self.method_counts.get("requests", 0)
        return http_count / self.successful

    def print_status(self, config: EvalConfig):
        """Print current SLO status."""
        print(f"\n  {'─' * 40}")
        print(f"  SLO STATUS")
        print(f"  {'─' * 40}")

        # Success rate
        sr = self.success_rate * 100
        sr_status = "✓" if sr >= 95 else ("⚠" if sr >= 90 else "✗")
        sr_color = sr_status
        print(f"  Success rate:    {sr:.0f}% {sr_status} (target: ≥95%)")

        # Block rate
        br = self.block_rate * 100
        br_status = "✓" if br < 10 else ("⚠" if br < 20 else "✗")
        print(f"  Block rate:      {br:.0f}% {br_status} (target: <10%)")

        # Method efficiency
        if self.successful > 0:
            eff = self.http_efficiency * 100
            eff_status = "✓" if eff >= 60 else ("⚠" if eff >= 40 else "✗")
            print(f"  HTTP efficiency: {eff:.0f}% {eff_status} (target: ≥60%)")

        # Method breakdown
        if self.method_counts:
            methods = ", ".join(f"{m}={c}" for m, c in sorted(self.method_counts.items()))
            print(f"  Methods used:    {methods}")

        print(f"  {'─' * 40}")


# =============================================================================
# RECON DISPLAY
# =============================================================================

def display_recon(recon: ReconResult | None, cached_strategy: str | None, config: EvalConfig):
    """Display recon results in a friendly format."""
    print(f"\n  RECON RESULTS")
    print(f"  {'─' * 40}")

    if not recon:
        print("  (recon failed or returned nothing)")
        return

    # CDN/WAF
    cdn = recon.cdn or "none detected"
    waf = recon.waf
    if waf and waf != cdn:
        print(f"  CDN/WAF:       {cdn} / {waf}")
    else:
        print(f"  CDN/WAF:       {cdn}")

    # Framework
    if recon.framework:
        print(f"  Framework:     {recon.framework}")

    # Challenge
    if recon.challenge_detected:
        print(f"  Challenge:     ⚠ detected")
    else:
        print(f"  Challenge:     none")

    # JS required
    js_status = "yes" if recon.js_required else "no"
    if recon.js_confidence:
        js_status += f" ({recon.js_confidence})"
    print(f"  JS required:   {js_status}")

    # Signals (if showing details)
    if config.show_recon_details and recon.js_signals:
        signals = ", ".join(recon.js_signals[:5])
        if len(recon.js_signals) > 5:
            signals += f" (+{len(recon.js_signals) - 5} more)"
        print(f"  Signals:       {signals}")

    # Notes from recon
    if config.show_recon_details and recon.notes:
        for note in recon.notes[:3]:
            print(f"  Note:          {note}")

    # Cached strategy
    if cached_strategy:
        print(f"  Cache:         {cached_strategy} (previous success)")

    # Recommended method
    recommended, source = recommend_strategy(recon, cached_strategy)
    print(f"  Recommended:   {recommended} (from {source})")
    print(f"  {'─' * 40}")


# =============================================================================
# CRAWL EXECUTION
# =============================================================================

def run_crawl(
    carrier: dict,
    method: str,
    depth: int,
    timeout: int,
    force_headless: bool = True,
) -> dict:
    """
    Run a crawl and return results.

    Returns dict with: success, pages, words, method_used, blocked, error
    """
    from scripts.crawl import crawl_site, load_profile

    try:
        profile = load_profile("trucking")

        # Build fetch spec based on method
        # Force headless in fetch_spec to override any defaults
        fetch_spec = {
            "method": method,
            "headless": force_headless,  # Explicitly force headless
        }
        if method in ("stealth", "visible") and not force_headless:
            fetch_spec["js_auto"] = True

        result = crawl_site(
            carrier,
            max_depth=depth,
            use_js=(method in ("js", "stealth", "visible")),
            use_stealth=(method == "stealth"),
            headless=force_headless,  # Force headless here too
            profile=profile,
            quiet=True,
            fetch_spec=fetch_spec,
        )

        if result is None:
            # Site was queued for monkey
            return {
                "success": False,
                "pages": 0,
                "words": 0,
                "method_used": method,
                "blocked": True,
                "error": "queued_for_monkey",
            }

        pages = result.get("structure", {}).get("total_pages", 0)
        words = result.get("total_word_count", 0)
        access = result.get("access", {})
        blocked = access.get("blocked", False)

        # Consider success if we got meaningful content
        success = pages > 0 and words >= 100 and not blocked

        return {
            "success": success,
            "pages": pages,
            "words": words,
            "method_used": access.get("strategy", method),
            "blocked": blocked,
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "pages": 0,
            "words": 0,
            "method_used": method,
            "blocked": False,
            "error": str(e),
        }


# =============================================================================
# INTERACTIVE PROMPTS
# =============================================================================

def prompt_yes_no(prompt: str, default: bool = True) -> bool:
    """Prompt for yes/no with default."""
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        response = input(f"  {prompt} {suffix}: ").strip().lower()
        if not response:
            return default
        return response in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        return default


def prompt_choice(prompt: str, choices: list[str], default: str | None = None) -> str:
    """Prompt for choice from list."""
    choices_str = "/".join(choices)
    default_hint = f" (default: {default})" if default else ""
    try:
        response = input(f"  {prompt} [{choices_str}]{default_hint}: ").strip().lower()
        if not response and default:
            return default
        if response in choices:
            return response
        # Partial match
        matches = [c for c in choices if c.startswith(response)]
        if len(matches) == 1:
            return matches[0]
        return default or choices[0]
    except (KeyboardInterrupt, EOFError):
        return default or choices[0]


def prompt_continue() -> bool:
    """Prompt to continue to next site."""
    try:
        input("  Press Enter to continue (Ctrl+C to quit)...")
        return True
    except (KeyboardInterrupt, EOFError):
        return False


# =============================================================================
# MAIN EVALUATION LOOP
# =============================================================================

def run_eval_session(
    sites: list[dict],
    config: EvalConfig,
) -> list[dict]:
    """Run interactive evaluation session."""
    slo = SLOTracker()
    results = []
    total = len(sites)

    print("\n" + "=" * 60)
    print("ACCESS LAYER EVALUATION")
    print("=" * 60)
    print(f"\nSites to test: {total}")
    print(f"Depth: {config.depth} (0=homepage only)")
    print("\nFor each site:")
    print("  1. Run recon (detect CDN, challenge, JS requirement)")
    print("  2. Show recommended strategy")
    print("  3. Crawl with that strategy")
    print("  4. Report result and update SLO metrics")
    print("\nPress Enter to start, Ctrl+C to quit...")

    try:
        input()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        return results

    for i, carrier in enumerate(sites, 1):
        domain = carrier["domain"]
        name = carrier.get("name", domain)
        tier = carrier.get("tier", "?")

        print(f"\n{'═' * 60}")
        print(f"SITE {i}/{total}: {name}")
        print(f"Domain: {domain} | Tier: {tier}")
        print("═" * 60)

        # Check for existing flow
        if has_flow(domain):
            flow_age = get_flow_age_days(domain)
            age_str = f"{flow_age:.0f} days old" if flow_age else "unknown age"
            print(f"\n  Note: Has saved flow ({age_str})")

        # Check monkey queue status
        queue = list_queue()
        in_queue = any(e.domain == domain for e in queue)
        if in_queue:
            print(f"\n  Note: Currently in monkey queue")

        # Check cached strategy
        cached_strategy = get_cached_strategy(domain)

        # Run recon
        print(f"\n  Running recon...")
        start_url = f"https://www.{domain}"
        recon = recon_site(start_url)

        display_recon(recon, cached_strategy, config)

        # Determine strategy
        recommended, source = recommend_strategy(recon, cached_strategy)

        print(f"\n  Strategy: {recommended} (from {source})")

        # Confirm or override strategy
        if config.confirm_strategy:
            override = prompt_choice(
                "Use this strategy?",
                ["yes", "requests", "js", "stealth", "visible", "skip"],
                "yes"
            )
            if override == "skip":
                print("  Skipped.")
                continue
            elif override != "yes":
                recommended = override
                print(f"  Using: {recommended}")

        # Run crawl
        print(f"\n  Crawling with {recommended}...")
        crawl_result = run_crawl(
            carrier,
            method=recommended,
            depth=config.depth,
            timeout=config.timeout_sec,
        )

        # Display result
        if crawl_result["success"]:
            print(f"\n  ✓ SUCCESS")
            print(f"    Pages: {crawl_result['pages']}")
            print(f"    Words: {crawl_result['words']:,}")
            print(f"    Method: {crawl_result['method_used']}")
        else:
            print(f"\n  ✗ FAILED")
            if crawl_result["blocked"]:
                print(f"    Reason: blocked")
            elif crawl_result["error"]:
                print(f"    Error: {crawl_result['error']}")
            else:
                print(f"    Reason: insufficient content")

            # Handle failure
            if config.on_block == "prompt":
                if crawl_result["error"] != "queued_for_monkey":
                    add_queue = prompt_yes_no("Add to monkey queue?", default=True)
                    if add_queue:
                        add_to_monkey_queue(
                            domain,
                            reason="eval_access_failed",
                            tier=tier if isinstance(tier, int) else None,
                            attempts_auto=[recommended],
                        )
                        print("  Added to queue.")
            elif config.on_block == "auto_queue":
                if crawl_result["error"] != "queued_for_monkey":
                    add_to_monkey_queue(
                        domain,
                        reason="eval_access_failed",
                        tier=tier if isinstance(tier, int) else None,
                        attempts_auto=[recommended],
                    )
                    print("  Auto-added to queue.")

        # Record SLO metrics
        slo.record(
            success=crawl_result["success"],
            blocked=crawl_result["blocked"],
            method=crawl_result["method_used"],
        )

        # Store result
        results.append({
            "domain": domain,
            "name": name,
            "tier": tier,
            **crawl_result,
        })

        # Show SLO status
        if config.track_slos:
            slo.print_status(config)

        # Pause between sites
        if config.pause_between_sites and i < total:
            if not prompt_continue():
                break

    return results


def run_batch_eval(
    sites: list[dict],
    config: EvalConfig,
    jobs: int = 4,
) -> list[dict]:
    """
    Run evaluation in parallel batch mode (non-interactive).

    No prompts, no pauses, just runs everything headless in parallel.
    """
    results = []
    total = len(sites)

    print("\n" + "=" * 60)
    print("ACCESS LAYER BATCH EVALUATION")
    print("=" * 60)
    print(f"\nSites to test: {total}")
    print(f"Parallel jobs: {jobs}")
    print(f"Depth: {config.depth}")
    print(f"Mode: headless, non-interactive")
    print("\nStarting...\n")

    def eval_one_site(carrier: dict) -> dict:
        """Evaluate a single site (for parallel execution)."""
        domain = carrier["domain"]
        tier = carrier.get("tier", "?")

        # Run recon
        start_url = f"https://www.{domain}"
        try:
            recon = recon_site(start_url)
        except Exception:
            recon = None

        # Get cached strategy
        cached_strategy = get_cached_strategy(domain)

        # Determine strategy
        recommended, source = recommend_strategy(recon, cached_strategy)

        # Run crawl (always headless in batch mode)
        crawl_result = run_crawl(
            carrier,
            method=recommended,
            depth=config.depth,
            timeout=config.timeout_sec,
            force_headless=True,
        )

        return {
            "domain": domain,
            "name": carrier.get("name", domain),
            "tier": tier,
            "strategy": recommended,
            "strategy_source": source,
            "recon_cdn": recon.cdn if recon else None,
            "recon_challenge": recon.challenge_detected if recon else None,
            **crawl_result,
        }

    # Run in parallel
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {executor.submit(eval_one_site, site): site for site in sites}

        completed = 0
        for future in as_completed(futures):
            site = futures[future]
            try:
                result = future.result()
                results.append(result)
                completed += 1

                # Progress update
                status = "✓" if result["success"] else "✗"
                domain = result["domain"]
                pages = result["pages"]
                words = result["words"]
                method = result.get("method_used", "?")
                print(f"  [{completed}/{total}] {status} {domain}: {pages} pages, {words:,} words ({method})")

            except Exception as e:
                completed += 1
                domain = site["domain"]
                print(f"  [{completed}/{total}] ✗ {domain}: error - {e}")
                results.append({
                    "domain": domain,
                    "name": site.get("name", domain),
                    "tier": site.get("tier", "?"),
                    "success": False,
                    "error": str(e),
                    "pages": 0,
                    "words": 0,
                    "blocked": False,
                    "method_used": "unknown",
                })

    return results


def print_summary(results: list[dict], slo: SLOTracker | None = None):
    """Print evaluation summary."""
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)

    total = len(results)
    successes = sum(1 for r in results if r["success"])
    blocks = sum(1 for r in results if r["blocked"])
    total_pages = sum(r["pages"] for r in results)
    total_words = sum(r["words"] for r in results)

    print(f"\nSites tested:  {total}")
    print(f"Successful:    {successes} ({100*successes/total:.0f}%)" if total else "Successful:    0")
    print(f"Blocked:       {blocks}")
    print(f"Total pages:   {total_pages}")
    print(f"Total words:   {total_words:,}")

    # Method breakdown
    methods = {}
    for r in results:
        m = r.get("method_used", "unknown")
        methods[m] = methods.get(m, 0) + 1
    if methods:
        print(f"\nMethods used:")
        for m, c in sorted(methods.items(), key=lambda x: -x[1]):
            print(f"  {m}: {c}")

    # Per-site results
    print(f"\n{'─' * 60}")
    print("Per-site results:")
    print(f"{'─' * 60}")
    for r in results:
        status = "✓" if r["success"] else "✗"
        pages = r["pages"]
        words = r["words"]
        method = r.get("method_used", "?")
        print(f"  {status} {r['domain']}: {pages} pages, {words:,} words ({method})")

    # SLO summary
    if total > 0:
        print(f"\n{'─' * 60}")
        print("SLO CHECK:")
        print(f"{'─' * 60}")

        success_rate = successes / total * 100
        block_rate = blocks / total * 100

        sr_pass = success_rate >= 95
        br_pass = block_rate < 10

        print(f"  Tier-1 success rate: {success_rate:.0f}% {'✓ PASS' if sr_pass else '✗ FAIL'} (target: ≥95%)")
        print(f"  Block rate: {block_rate:.0f}% {'✓ PASS' if br_pass else '✗ FAIL'} (target: <10%)")

    print("=" * 60 + "\n")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Interactive access layer evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/eval_access.py                    # Just run it (interactive)
  python scripts/eval_access.py -j 4               # Parallel batch mode (4 jobs)
  python scripts/eval_access.py --tier 2           # Test tier-2 sites
  python scripts/eval_access.py --domain jbhunt.com  # Single site
  python scripts/eval_access.py --sample-size 3    # Quick 3-site test
  python scripts/eval_access.py --depth 1          # Crawl one level deep
  python scripts/eval_access.py --no-confirm       # Skip strategy confirmation
  python scripts/eval_access.py -j 4 -n 10         # 10 sites, 4 parallel
"""
    )
    parser.add_argument("--domain", "-d", help="Test single domain")
    parser.add_argument("--tier", "-t", type=int, help="Test specific tier (default: 1)")
    parser.add_argument("--sample-size", "-n", type=int, help="Number of sites to test")
    parser.add_argument("--depth", type=int, help="Crawl depth (default: 0 = homepage only)")
    parser.add_argument("--jobs", "-j", type=int, default=1,
                        help="Parallel jobs (>1 = batch mode, no prompts, headless)")
    parser.add_argument("--no-confirm", action="store_true", help="Skip strategy confirmation prompts")
    parser.add_argument("--no-pause", action="store_true", help="Don't pause between sites")
    parser.add_argument("--auto-queue", action="store_true", help="Auto-add failures to monkey queue")
    args = parser.parse_args()

    # Load config
    config, known_hard, skip_sites = load_config()

    # Apply CLI overrides
    if args.sample_size:
        config.sample_size = args.sample_size
    if args.depth is not None:
        config.depth = args.depth
    if args.no_confirm:
        config.confirm_strategy = False
    if args.no_pause:
        config.pause_between_sites = False
    if args.auto_queue:
        config.on_block = "auto_queue"

    # Select sites
    sites = select_sites(
        config,
        known_hard,
        skip_sites,
        tier_override=args.tier,
        domain_override=args.domain,
    )

    if not sites:
        print("No sites to evaluate.")
        sys.exit(1)

    # Run evaluation (batch mode if jobs > 1)
    if args.jobs > 1:
        results = run_batch_eval(sites, config, jobs=args.jobs)
    else:
        results = run_eval_session(sites, config)

    # Print summary
    if results:
        print_summary(results)


if __name__ == "__main__":
    main()
