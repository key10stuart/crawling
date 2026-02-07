#!/usr/bin/env python3
"""
Trucking industry web corpus crawler.

Capture-first crawl pipeline:
- Site-level recon + robots + sitemap
- Capture pages with expansion + interactions
- Extract and tag content from archived HTML
- Write site JSON and execution log
"""

import argparse
import json
import os
import random
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    tqdm = None

# Add parent dir to path for fetch module
sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrate.config as oconfig
from orchestrate.config import (
    parse_freshen_interval,
    should_skip_site_freshness,
    load_seeds,
    load_companies_file,
    load_run_config,
    apply_run_config,
    load_fetch_profiles,
)
from orchestrate.fetch_spec import resolve_fetch_spec, extract_access_hints, _normalize_method
from orchestrate.presenter import (
    build_capture_site_data,
    get_page_count,
    get_word_count,
    write_site_json,
)

from fetch.capture import capture_page, write_manifest
from fetch.capture_config import CaptureConfig, CaptureResult, AccessAttempt
from fetch.access_classifier import classify_capture_result, outcome_as_dict
from fetch.extractor import extract_from_capture
from fetch.recon import recon_site
from fetch.robots import RobotsChecker
from fetch.sitemap import discover_sitemap, parse_sitemap
from fetch.access_policy import (
    AccessPlan,
    build_access_plan,
    compute_backoff_delay,
    decide_next_strategy,
    get_domain_playbook,
    load_playbooks,
    strategy_to_capture_kwargs,
)

# Monkey queue for terminal failures
try:
    from fetch.monkey import add_to_monkey_queue
    _MONKEY_AVAILABLE = True
except ImportError:
    _MONKEY_AVAILABLE = False

# Project paths (from orchestrate.config)
PROJECT_ROOT = oconfig.PROJECT_ROOT
CORPUS_DIR = oconfig.CORPUS_DIR
RAW_DIR = oconfig.RAW_DIR
EXTRACTED_DIR = oconfig.EXTRACTED_DIR
SITES_DIR = oconfig.SITES_DIR

# Crawl settings
DEFAULT_DEPTH = 2
REQUEST_DELAY = 3.0  # seconds between requests (polite crawling)


def _build_start_url(domain: str) -> str:
    """Normalize seed domain into a crawlable HTTPS URL.

    Keep explicit subdomains as-is (e.g., cloud.google.com), but default bare
    two-label domains to www.<domain> for compatibility with existing seeds.
    """
    value = domain.strip()
    if value.startswith(("http://", "https://")):
        return value

    if "/" in value:
        host, path = value.split("/", 1)
    else:
        host, path = value, ""

    # Preserve subdomains and existing www hosts; only prefix bare domains.
    if host.startswith("www.") or host.count(".") > 1:
        resolved_host = host
    else:
        resolved_host = f"www.{host}"

    if path:
        return f"https://{resolved_host}/{path}"
    return f"https://{resolved_host}"


def _resolve_capture_config(fetch_spec: dict, args: argparse.Namespace) -> CaptureConfig:
    method = _normalize_method(fetch_spec.get("method"))
    headless = fetch_spec.get("headless", not args.no_headless)
    stealth = False
    js_required = False
    no_js_fallback = False

    if method == "requests":
        js_required = False
        stealth = False
        no_js_fallback = True
    elif method == "visible":
        js_required = True
        headless = False
    elif method == "stealth":
        js_required = True
        stealth = True
    elif method == "js":
        js_required = True
    else:
        js_required = bool(args.js or args.stealth)
        stealth = bool(args.stealth)

    expand_lazy = not no_js_fallback

    return CaptureConfig(
        js_required=js_required,
        stealth=stealth,
        headless=headless,
        timeout_ms=30000,
        expand_lazy_content=expand_lazy,
        scroll_to_bottom=expand_lazy,
        click_accordions=expand_lazy,
        take_screenshot=expand_lazy,
        no_js_fallback=no_js_fallback,
        cookie_ref=fetch_spec.get("cookies") or fetch_spec.get("cookie"),
    )


def _resolve_capture_delay(fetch_spec: dict, default_delay: float) -> float:
    if fetch_spec.get("slow_drip"):
        return random.uniform(120, 900)
    if fetch_spec.get("patient"):
        return random.uniform(8, 20)
    if fetch_spec.get("delay") is not None:
        return float(fetch_spec["delay"])
    return default_delay


def _build_site_profile(
    recon,
    robots: RobotsChecker | None,
    sitemap_url: str | None,
    sitemap_urls: list[str],
    capture_config: CaptureConfig,
    resolved_method: str | None,
) -> dict:
    return {
        "recon": asdict(recon) if recon else None,
        "robots": {
            "found": robots.found if robots else False,
            "url": robots.robots_url if robots else None,
            "crawl_delay": robots.crawl_delay if robots else None,
            "sitemaps": robots.sitemaps if robots else [],
            "disallowed_sample": robots.disallowed_paths if robots else [],
            "error": robots.error if robots else None,
        },
        "sitemap": {
            "url": sitemap_url,
            "url_count": len(sitemap_urls),
            "sample": sitemap_urls[:10],
        },
        "capture_method": resolved_method or "auto",
        "capture_settings": {
            "js_required": capture_config.js_required,
            "stealth": capture_config.stealth,
            "headless": capture_config.headless,
            "expand_lazy_content": capture_config.expand_lazy_content,
            "scroll_to_bottom": capture_config.scroll_to_bottom,
            "click_accordions": capture_config.click_accordions,
            "take_screenshot": capture_config.take_screenshot,
            "no_js_fallback": capture_config.no_js_fallback,
        },
    }


def _make_capture_config_for_strategy(
    strategy: str,
    plan: AccessPlan,
    base_config: CaptureConfig,
) -> CaptureConfig:
    """Build a CaptureConfig for a specific escalation strategy."""
    kwargs = strategy_to_capture_kwargs(strategy, plan)
    is_js = strategy != "requests"

    return CaptureConfig(
        js_required=kwargs.get("js_required", base_config.js_required),
        stealth=kwargs.get("stealth", base_config.stealth),
        headless=kwargs.get("headless", base_config.headless),
        timeout_ms=base_config.timeout_ms,
        expand_lazy_content=base_config.expand_lazy_content if is_js else False,
        scroll_to_bottom=base_config.scroll_to_bottom if is_js else False,
        click_accordions=base_config.click_accordions if is_js else False,
        take_screenshot=base_config.take_screenshot if is_js else False,
        no_js_fallback=True,  # We handle fallback via policy engine now
        cookie_ref=base_config.cookie_ref,
        cookies_dir=base_config.cookies_dir,
    )


def _capture_url_adaptive(
    url: str,
    plan: AccessPlan,
    base_config: CaptureConfig,
    recon,
    domain_playbook: dict | None,
    escalation_mode: str,
) -> tuple[CaptureResult | None, list[AccessAttempt], str]:
    """
    Bounded attempt loop for a single URL with adaptive escalation.

    Returns (final_capture_or_None, attempt_records, final_outcome_str).
    """
    strategy = plan.initial_strategy
    attempt_records: list[AccessAttempt] = []
    same_strategy_retries = 0
    last_strategy = None
    final_capture = None
    final_outcome_str = "unknown_failure"

    for attempt_idx in range(plan.max_attempts):
        attempt_start = datetime.now(timezone.utc)

        config = _make_capture_config_for_strategy(strategy, plan, base_config)
        result = capture_page(url, config, RAW_DIR)
        outcome = classify_capture_result(result, recon=recon)

        attempt_end = datetime.now(timezone.utc)
        duration_ms = int((attempt_end - attempt_start).total_seconds() * 1000)

        attempt = AccessAttempt(
            attempt_index=attempt_idx + 1,
            strategy=strategy,
            started_at=attempt_start.isoformat(),
            duration_ms=duration_ms,
            outcome=outcome,
            capture_error=result.error,
            html_size_bytes=result.html_size_bytes,
        )
        attempt_records.append(attempt)
        final_outcome_str = outcome.outcome

        # Success — done
        if outcome.outcome == "success_real_content":
            result.access_outcome = outcome
            result.attempts = attempt_records
            return result, attempt_records, final_outcome_str

        # Static mode — no escalation
        if escalation_mode == "static":
            break

        # Track same-strategy retries
        if strategy == last_strategy:
            same_strategy_retries += 1
        else:
            same_strategy_retries = 0
        last_strategy = strategy

        # Ask policy engine for next move
        next_strategy = decide_next_strategy(
            current_strategy=strategy,
            outcome_str=outcome.outcome,
            attempt_index=attempt_idx,
            plan=plan,
            same_strategy_retries=same_strategy_retries,
            domain_playbook=domain_playbook,
        )

        if next_strategy is None:
            break

        # Backoff before retry
        delay = compute_backoff_delay(attempt_idx, plan, outcome.outcome)
        time.sleep(delay)
        strategy = next_strategy

    # Terminal: return last result if it at least has HTML
    if result.html_path and not result.error:
        final_capture = result
    if final_capture:
        final_capture.access_outcome = outcome
        final_capture.attempts = attempt_records
    return final_capture, attempt_records, final_outcome_str


def capture_site(
    carrier: dict,
    args: argparse.Namespace,
    cfg: dict,
    provided_flags: set[str],
    fetch_profiles: dict,
    playbooks: dict | None = None,
) -> dict:
    domain = carrier["domain"]
    base_domain = domain.split("/")[0] if "/" in domain else domain

    print(f"\nCapturing {carrier['name']} ({domain})")

    start_url = _build_start_url(domain)

    # Recon FIRST to detect SPA/JS requirements
    recon = recon_site(start_url)

    fetch_spec = resolve_fetch_spec(carrier, args, cfg, provided_flags, fetch_profiles)
    resolved_method = _normalize_method(fetch_spec.get("method"))

    # Upgrade method if recon detected JS requirement (SPA, framework, etc.)
    if recon and recon.js_required and resolved_method in (None, "requests"):
        print(f"  [recon] JS required ({recon.framework or 'SPA signals'}) → upgrading to js")
        resolved_method = "js"

    # Div 4k1: build access plan from layered config
    domain_playbook = get_domain_playbook(domain, playbooks)
    access_hints = extract_access_hints(fetch_spec)
    cli_overrides = {}
    if hasattr(args, "access_max_attempts") and args.access_max_attempts:
        cli_overrides["access_max_attempts"] = args.access_max_attempts
    if hasattr(args, "access_escalation_mode") and args.access_escalation_mode:
        cli_overrides["access_escalation_mode"] = args.access_escalation_mode
    access_plan = build_access_plan(
        recon=recon,
        fetch_spec=access_hints,
        domain_playbook=domain_playbook,
        cli_overrides=cli_overrides if cli_overrides else None,
    )
    escalation_mode = getattr(args, "access_escalation_mode", "adaptive")
    print(f"  [access] plan: {access_plan.initial_strategy} "
          f"(max_attempts={access_plan.max_attempts}, mode={escalation_mode})")

    capture_config = _resolve_capture_config(fetch_spec, args)

    urls_to_capture = [start_url]
    robots = RobotsChecker.fetch(start_url)
    sitemap_url = discover_sitemap(start_url, robots.sitemaps if robots else [])
    sitemap_urls: list[str] = []
    if sitemap_url:
        sitemap_result = parse_sitemap(sitemap_url, max_urls=50)
        if sitemap_result and sitemap_result.urls:
            for entry in sitemap_result.urls[:50]:
                if robots and not robots.is_allowed(entry.loc):
                    continue
                urls_to_capture.append(entry.loc)
                sitemap_urls.append(entry.loc)

    urls_to_capture = list(dict.fromkeys(urls_to_capture))
    print(f"  Found {len(urls_to_capture)} URLs to capture")

    captures: list[CaptureResult] = []
    all_attempts_by_url: list[dict] = []
    terminal_failures: list[dict] = []

    for i, url in enumerate(urls_to_capture):
        url_path = urlparse(url).path or '/'
        print(f"  [{i+1}/{len(urls_to_capture)}] {url_path}", end="", flush=True)

        final_capture, attempt_records, final_outcome = _capture_url_adaptive(
            url=url,
            plan=access_plan,
            base_config=capture_config,
            recon=recon,
            domain_playbook=domain_playbook,
            escalation_mode=escalation_mode,
        )

        strategies_used = list(dict.fromkeys(a.strategy for a in attempt_records))
        num_attempts = len(attempt_records)

        if final_outcome == "success_real_content" and final_capture:
            kb = final_capture.html_size_bytes // 1024
            suffix = f" ({num_attempts} attempts)" if num_attempts > 1 else ""
            print(f" ✓ {kb}KB{suffix}")
            captures.append(final_capture)
        else:
            print(f" ✗ {final_outcome} ({num_attempts} attempts, tried: {','.join(strategies_used)})")
            terminal_failures.append({
                "url": url,
                "final_outcome": final_outcome,
                "strategies_tried": strategies_used,
            })

        all_attempts_by_url.append({
            "url": url,
            "final_outcome": final_outcome,
            "attempts": [asdict(a) for a in attempt_records],
            "escalations_used": strategies_used,
        })

        # Delay between URLs (base delay, not escalation backoff)
        if i < len(urls_to_capture) - 1:
            time.sleep(_resolve_capture_delay(fetch_spec, REQUEST_DELAY))

    # Monkey auto-enqueue for terminal failures
    if terminal_failures and _MONKEY_AVAILABLE:
        failure_rate = len(terminal_failures) / len(urls_to_capture) if urls_to_capture else 0
        if failure_rate > 0.5 or len(terminal_failures) >= 3:
            try:
                all_strategies = []
                for tf in terminal_failures:
                    all_strategies.extend(tf.get("strategies_tried", []))
                all_strategies = list(set(all_strategies))
                add_to_monkey_queue(
                    domain=base_domain,
                    reason=f"adaptive_access_terminal: {len(terminal_failures)}/{len(urls_to_capture)} failed",
                    tier=carrier.get("tier"),
                    attempts_auto=all_strategies,
                )
                print(f"  [monkey] Queued {base_domain} for manual attention "
                      f"({len(terminal_failures)} terminal failures)")
            except Exception as exc:
                print(f"  [monkey] Failed to enqueue: {exc}")

    site_profile = _build_site_profile(
        recon,
        robots,
        sitemap_url,
        sitemap_urls,
        capture_config,
        resolved_method,
    )

    if captures:
        manifest_path = write_manifest(base_domain, RAW_DIR, captures, site_profile=site_profile)
        print(f"  Manifest: {manifest_path}")

    extracted_pages = []
    for capture in captures:
        try:
            extraction = extract_from_capture(
                html_path=capture.html_path,
                url=capture.url,
                asset_inventory=[asdict(a) for a in capture.asset_inventory],
                screenshot_path=str(capture.screenshot_path) if capture.screenshot_path else None,
                interaction_log=capture.interaction_log,
                expansion_stats=capture.expansion_stats,
            )
            # Re-classify with extraction context for final accuracy
            outcome = classify_capture_result(capture, extracted_page=extraction, recon=recon)
            capture.access_outcome = outcome
            if capture.attempts:
                capture.attempts[-1].outcome = outcome
            extraction["final_access_outcome"] = outcome_as_dict(outcome)
            extraction["attempts"] = [asdict(a) for a in capture.attempts]
            extracted_pages.append(extraction)
        except Exception as exc:
            extracted_pages.append(
                {
                    "url": capture.url,
                    "error": f"extract_failed:{type(exc).__name__}",
                    "final_access_outcome": outcome_as_dict(getattr(capture, "access_outcome", None)),
                    "attempts": [asdict(a) for a in getattr(capture, "attempts", [])],
                    "archive": {
                        "html_path": str(capture.html_path) if capture.html_path else None,
                        "screenshot_path": str(capture.screenshot_path) if capture.screenshot_path else None,
                    },
                }
            )

    site_data = build_capture_site_data(
        carrier=carrier,
        captures=captures,
        extracted_pages=extracted_pages,
        attempted_count=len(urls_to_capture),
        site_profile=site_profile,
        access_telemetry=all_attempts_by_url,
    )

    write_site_json(site_data, SITES_DIR)
    success_count = sum(1 for t in all_attempts_by_url if t["final_outcome"] == "success_real_content")
    print(f"  Done: {success_count}/{len(urls_to_capture)} URLs succeeded, "
          f"{len(captures)} pages captured, {site_data['stats']['total_html_kb']}KB")
    return site_data


def main():
    parser = argparse.ArgumentParser(description="Crawl trucking carrier websites")
    parser.add_argument("--domain", help="Crawl single domain")
    parser.add_argument("--tier", type=int, help="Only crawl carriers of this tier")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH, help="Max crawl depth")
    parser.add_argument("--limit", type=int, help="Max number of sites to crawl")
    parser.add_argument("--js", action="store_true", help="Render pages with Playwright (headless browser)")
    parser.add_argument("--stealth", action="store_true", help="Use playwright-stealth for anti-bot evasion")
    parser.add_argument("--no-headless", action="store_true", help="Run browser visibly (bypasses some bot detection)")
    parser.add_argument("--fetch-method", choices=["requests", "js", "stealth", "visible"],
                        help="Force fetch method for all sites (overrides per-site settings)")
    parser.add_argument("--fetch-profile", help="Fetch profile name from profiles/fetch_profiles.yaml")
    parser.add_argument("--delay", type=float, help="Base delay between requests in seconds (default: 3)")
    parser.add_argument("--patient", action="store_true", help="Patient mode: longer delays (8-20s)")
    parser.add_argument("--slow-drip", action="store_true", help="Ultra-patient mode for stubborn sites: random 2-15 min delays")
    parser.add_argument("--companies", help="Path to JSON/YAML company list (overrides seeds)")
    parser.add_argument("--run-config", help="Path to JSON/YAML run config (overrides defaults)")
    parser.add_argument("--run-id", help="Run identifier to namespace outputs (e.g., trucking_2026q1)")
    parser.add_argument("--freshen", type=str, metavar="INTERVAL",
                        help="Skip sites crawled within interval (e.g., 7d, 24h, 2h, 30m)")
    parser.add_argument("--jobs", "-j", type=int, default=1,
                        help="Number of sites to crawl in parallel (default: 1)")
    parser.add_argument("--progress", action="store_true",
                        help="Show clean progress bars instead of verbose output")
    parser.add_argument("--docker", action="store_true",
                        help="Run in Docker container with Xvfb (invisible browser windows)")
    parser.add_argument("--docker-rebuild", action="store_true",
                        help="Force rebuild Docker image before running")
    # Div 4k1: adaptive access flags
    parser.add_argument("--access-max-attempts", type=int, default=3,
                        help="Max capture attempts per URL before giving up (default: 3)")
    parser.add_argument("--access-escalation-mode", choices=["adaptive", "static"],
                        default="adaptive",
                        help="Access escalation mode: adaptive (closed-loop) or static (single attempt)")
    args = parser.parse_args()

    # Handle --docker flag: re-invoke via docker_crawl.sh
    if args.docker and not os.environ.get("CRAWL_IN_DOCKER"):
        import subprocess
        docker_script = PROJECT_ROOT / "scripts" / "docker_crawl.sh"
        if not docker_script.exists():
            print(f"Error: {docker_script} not found")
            sys.exit(1)
        docker_args = [str(docker_script)]
        if args.docker_rebuild:
            docker_args.append("--rebuild")
        for arg in sys.argv[1:]:
            if arg not in ("--docker", "--docker-rebuild"):
                docker_args.append(arg)
        print(f"Re-invoking in Docker: {' '.join(docker_args)}")
        sys.exit(subprocess.call(docker_args))

    # Apply run config (unless overridden via CLI)
    provided_flags = {a.lstrip("-").replace("-", "_") for a in sys.argv[1:] if a.startswith("--")}
    default_config = PROJECT_ROOT / "configs" / "defaults.yaml"
    cfg = {}
    if default_config.exists():
        cfg = load_run_config(str(default_config))
    if args.run_config:
        cfg.update(load_run_config(args.run_config))
    args = apply_run_config(args, cfg, provided_flags)

    fetch_profiles = load_fetch_profiles()
    playbooks = load_playbooks()

    # Configure output directories per run if requested
    global RAW_DIR, EXTRACTED_DIR, SITES_DIR
    run_id = args.run_id or (cfg.get("run_id") if isinstance(cfg, dict) else None)
    if run_id:
        RAW_DIR = CORPUS_DIR / "runs" / run_id / "raw"
        EXTRACTED_DIR = CORPUS_DIR / "runs" / run_id / "extracted"
        SITES_DIR = CORPUS_DIR / "runs" / run_id / "sites"
        oconfig.RAW_DIR = RAW_DIR
        oconfig.EXTRACTED_DIR = EXTRACTED_DIR
        oconfig.SITES_DIR = SITES_DIR

    if args.companies:
        carriers = load_companies_file(args.companies)
    else:
        seeds = load_seeds()
        carriers = seeds["carriers"]
        if cfg and isinstance(cfg, dict) and isinstance(cfg.get("carriers"), list):
            carriers = cfg["carriers"]

    if args.domain:
        domains = [d.strip() for d in args.domain.split(",")]
        carriers = [c for c in carriers if c["domain"] in domains]
    if args.tier:
        carriers = [c for c in carriers if c["tier"] == args.tier]
    if args.limit:
        carriers = carriers[:args.limit]

    if not carriers:
        print("No carriers matched filters")
        return

    if args.freshen:
        freshen_interval = parse_freshen_interval(args.freshen)
        fresh_skipped = []
        carriers_to_crawl = []
        for c in carriers:
            skip, age_str = should_skip_site_freshness(c["domain"], freshen_interval, args.depth)
            if skip:
                fresh_skipped.append((c["domain"], age_str))
            else:
                carriers_to_crawl.append(c)
        carriers = carriers_to_crawl
        if fresh_skipped:
            print(f"Skipping {len(fresh_skipped)} recently-crawled sites (--freshen {args.freshen}):")
            for domain, age in fresh_skipped:
                print(f"  [fresh] {domain} ({age})")
        if not carriers:
            print("All carriers are fresh, nothing to crawl")
            return

    crawl_start = datetime.now(timezone.utc)
    actual_jobs = min(args.jobs, len(carriers))

    if not (args.progress and TQDM_AVAILABLE):
        print(f"Crawling {len(carriers)} carriers (jobs={actual_jobs})...")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    SITES_DIR.mkdir(parents=True, exist_ok=True)

    def site_executor(carrier):
        try:
            return capture_site(carrier, args, cfg, provided_flags, fetch_profiles, playbooks=playbooks)
        except Exception as exc:
            if not (args.progress and actual_jobs > 1):
                print(f"  FAILED {carrier['domain']}: {exc}")
            return None

    results = []
    use_progress = args.progress and TQDM_AVAILABLE
    status_file = CORPUS_DIR / "crawl_status.json"

    def update_status(current_domain=None, completed=None, failed=None, running=None):
        try:
            status = {
                "started": datetime.now(timezone.utc).isoformat(),
                "total_sites": len(carriers),
                "completed": completed or len(results),
                "failed": failed or [],
                "running": running or [],
                "current": current_domain,
            }
            status_file.write_text(json.dumps(status, indent=2))
        except Exception:
            pass

    if use_progress:
        failed = []
        update_status()
        if actual_jobs > 1:
            running = []
            with tqdm(total=len(carriers), desc="Sites", unit="site", position=0) as pbar:
                with ThreadPoolExecutor(max_workers=actual_jobs) as executor:
                    futures = {executor.submit(site_executor, c): c for c in carriers}
                    for future in as_completed(futures):
                        carrier = futures[future]
                        result = future.result()
                        if result:
                            results.append(result)
                            pages = get_page_count(result)
                            pbar.set_postfix_str(f"{carrier['domain']}: {pages} pages")
                        else:
                            failed.append(carrier["domain"])
                        pbar.update(1)
                        update_status(failed=failed)
        else:
            with tqdm(carriers, desc="Sites", unit="site") as pbar:
                for carrier in pbar:
                    pbar.set_description(f"{carrier['domain'][:20]}")
                    update_status(current_domain=carrier["domain"], failed=failed)
                    result = site_executor(carrier)
                    if result:
                        results.append(result)
                        pages = get_page_count(result)
                        pbar.set_postfix_str(f"{pages} pages")
                    else:
                        failed.append(carrier["domain"])

        if failed:
            print(f"\nFailed sites: {', '.join(failed)}")
    else:
        update_status()
        if actual_jobs > 1:
            with ThreadPoolExecutor(max_workers=actual_jobs) as executor:
                futures = {executor.submit(site_executor, c): c for c in carriers}
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        results.append(result)
                    update_status()
        else:
            for carrier in carriers:
                update_status(current_domain=carrier["domain"])
                result = site_executor(carrier)
                if result:
                    results.append(result)

    total_pages = sum(get_page_count(s) for s in results)
    total_words = sum(get_word_count(s) for s in results)
    crawl_end = datetime.now(timezone.utc)
    duration_sec = (crawl_end - crawl_start).total_seconds() if "crawl_start" in dir() else 0

    print(f"\n{'='*60}")
    print(f"Completed: {len(results)}/{len(carriers)} sites")
    print(f"Total pages: {total_pages}")
    print(f"Total words: {total_words:,}")

    try:
        log_dir = CORPUS_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "executions.jsonl"

        methods_used = {}
        for r in results:
            method = r.get("fetch_method", "unknown")
            methods_used[method] = methods_used.get(method, 0) + 1

        log_entry = {
            "timestamp": crawl_end.isoformat(),
            "duration_sec": round(duration_sec, 1),
            "command": " ".join(sys.argv),
            "config": {
                "tier": args.tier,
                "domain": args.domain,
                "depth": args.depth,
                "jobs_requested": args.jobs,
                "jobs_actual": actual_jobs,
                "freshen": args.freshen,
                "docker": os.environ.get("CRAWL_IN_DOCKER") == "1",
            },
            "results": {
                "sites_attempted": len(carriers),
                "sites_completed": len(results),
                "sites_failed": len(carriers) - len(results),
                "total_pages": total_pages,
                "total_words": total_words,
                "methods_used": methods_used,
            },
            "sites": [
                {
                    "domain": r["domain"],
                    "pages": get_page_count(r),
                    "words": get_word_count(r),
                    "method": r.get("fetch_method", "unknown"),
                }
                for r in results
            ],
        }

        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

        print(f"Execution logged to: {log_file}")
    except Exception as exc:
        print(f"Warning: Could not write execution log: {exc}")


if __name__ == "__main__":
    main()
