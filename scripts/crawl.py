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
from orchestrate.fetch_spec import resolve_fetch_spec, _normalize_method
from orchestrate.presenter import (
    build_capture_site_data,
    get_page_count,
    get_word_count,
    write_site_json,
)

from fetch.capture import capture_page, write_manifest
from fetch.capture_config import CaptureConfig, CaptureResult
from fetch.extractor import extract_from_capture
from fetch.recon import recon_site
from fetch.robots import RobotsChecker
from fetch.sitemap import discover_sitemap, parse_sitemap

# Project paths (from orchestrate.config)
PROJECT_ROOT = oconfig.PROJECT_ROOT
CORPUS_DIR = oconfig.CORPUS_DIR
RAW_DIR = oconfig.RAW_DIR
EXTRACTED_DIR = oconfig.EXTRACTED_DIR
SITES_DIR = oconfig.SITES_DIR

# Crawl settings
DEFAULT_DEPTH = 2
REQUEST_DELAY = 3.0  # seconds between requests (polite crawling)


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


def capture_site(
    carrier: dict,
    args: argparse.Namespace,
    cfg: dict,
    provided_flags: set[str],
    fetch_profiles: dict,
) -> dict:
    domain = carrier["domain"]
    base_domain = domain.split("/")[0] if "/" in domain else domain

    print(f"\nCapturing {carrier['name']} ({domain})")

    if "/" in domain:
        base, path = domain.split("/", 1)
        start_url = f"https://www.{base}/{path}"
    else:
        start_url = f"https://www.{domain}"

    # Recon FIRST to detect SPA/JS requirements
    recon = recon_site(start_url)

    fetch_spec = resolve_fetch_spec(carrier, args, cfg, provided_flags, fetch_profiles)
    resolved_method = _normalize_method(fetch_spec.get("method"))

    # Upgrade method if recon detected JS requirement (SPA, framework, etc.)
    if recon and recon.js_required and resolved_method in (None, "requests"):
        print(f"  [recon] JS required ({recon.framework or 'SPA signals'}) → upgrading to js")
        resolved_method = "js"

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
    for i, url in enumerate(urls_to_capture):
        print(f"  [{i+1}/{len(urls_to_capture)}] {urlparse(url).path or '/'}", end="", flush=True)
        result = capture_page(url, capture_config, RAW_DIR)

        if result.error:
            print(f" ✗ {result.error}")
        else:
            print(f" ✓ {result.html_size_bytes//1024}KB")
            captures.append(result)

        time.sleep(_resolve_capture_delay(fetch_spec, REQUEST_DELAY))

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
            extracted_pages.append(extraction)
        except Exception as exc:
            extracted_pages.append(
                {
                    "url": capture.url,
                    "error": f"extract_failed:{type(exc).__name__}",
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
    )

    write_site_json(site_data, SITES_DIR)
    print(f"  Done: {len(captures)} pages captured, {site_data['stats']['total_html_kb']}KB")
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
            return capture_site(carrier, args, cfg, provided_flags, fetch_profiles)
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
