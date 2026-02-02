#!/usr/bin/env python3
"""
Test the improved crawl and generate an HTML report.

Runs a short crawl on a test domain and produces an HTML report showing:
- Crawl stats and timing
- Nav coverage (profile-based)
- Block tagging results
- Feature detection / crawl hints
- Sample page extractions

Usage:
  python scripts/test_crawl_report.py --domain schneider.com --profile trucking
  python scripts/test_crawl_report.py --domain nvidia.com --profile nvidia --depth 1
"""

import argparse
import sys
import time
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.crawl import crawl_site, SITES_DIR
from fetch.profile import load_profile


REPORT_DIR = Path(__file__).parent.parent / "corpus" / "reports"


def _render_page_types_rows(page_types: dict) -> str:
    """Render page types table rows."""
    rows = []
    for k, v in sorted(page_types.items(), key=lambda x: -x[1]):
        rows.append(f"<tr><td>{escape(k)}</td><td>{v}</td></tr>")
    return "".join(rows)


def _render_block_counts_rows(block_counts: dict) -> str:
    """Render block counts table rows."""
    rows = []
    for k, v in sorted(block_counts.items()):
        rows.append(f"<tr><td>{escape(k)}</td><td>{v}</td></tr>")
    return "".join(rows)


def _render_crawl_hints_rows(crawl_hints: list) -> str:
    """Render crawl hints table rows."""
    if not crawl_hints:
        return ""
    rows = []
    for h in crawl_hints:
        feature = escape(h.get("feature", ""))
        subtree = escape(h.get("subtree", ""))
        priority = escape(h.get("priority", ""))
        rows.append(
            f'<tr><td>{feature}</td><td><code>{subtree}</code></td>'
            f'<td><span class="tag tag-hint">{priority}</span></td></tr>'
        )
    return "".join(rows)


def _render_product_rows(prod_details: dict) -> str:
    """Render product coverage table rows."""
    rows = []
    for name, details in prod_details.items():
        covered = details.get("covered", False)
        pages_count = len(details.get("pages_found", []))
        terms = ", ".join(escape(t) for t in details.get("terms_found", [])[:5])
        status = '<span class="tag tag-found">Yes</span>' if covered else '<span class="tag tag-missing">No</span>'
        rows.append(
            f"<tr><td>{escape(name)}</td><td>{status}</td>"
            f"<td>{pages_count}</td><td>{terms}</td></tr>"
        )
    return "".join(rows)


def _render_pages_rows(pages: list) -> str:
    """Render pages summary table rows."""
    rows = []
    for p in pages[:50]:
        url = escape(p.get("url", ""))
        path = escape(p.get("path", "/")[:40])
        page_type = escape(p.get("page_type", ""))
        word_count = p.get("word_count", 0)
        img_count = len(p.get("images", []))
        product = escape(p.get("product", "") or "-")
        is_dup = "Yes" if p.get("is_duplicate") else ""
        rows.append(
            f'<tr><td><a href="{url}" title="{url}">{path}</a></td>'
            f"<td>{page_type}</td><td>{word_count}</td><td>{img_count}</td>"
            f"<td>{product}</td><td>{is_dup}</td></tr>"
        )
    if len(pages) > 50:
        rows.append(f'<tr><td colspan="6"><em>... and {len(pages) - 50} more pages</em></td></tr>')
    return "".join(rows)


def _render_tagged_blocks(tagged_blocks: list) -> str:
    """Render tagged blocks sample."""
    items = []
    for b in tagged_blocks[:20]:
        block_type = escape(b.get("block_type", ""))
        content_type = escape(b.get("content_type", ""))
        content = b.get("content", "")
        content_preview = escape(content[:100]) + ("..." if len(content) > 100 else "")
        items.append(
            f'<div class="block-item">'
            f'<span class="block-type">[{block_type}]</span> '
            f'<span class="tag" style="background:#eee;">{content_type}</span> '
            f'{content_preview}</div>'
        )
    return "".join(items)


def _render_nav_links(nav_links: list) -> str:
    """Render nav links as tags."""
    tags = []
    for link in nav_links[:30]:
        url = escape(link.get("url", ""))
        text = escape(link.get("text", ""))
        tags.append(f'<a href="{url}" class="tag" style="background:#e7f1ff;">{text}</a>')
    if len(nav_links) > 30:
        tags.append(f'<span class="tag">+{len(nav_links) - 30} more</span>')
    return "".join(tags)


def render_site_report(site: dict, profile_name: str) -> str:
    """Render a full site crawl report as HTML."""
    domain = site.get("domain", "unknown")
    company = site.get("company_name", domain)
    pages = site.get("pages", [])

    # Stats
    total_pages = site.get("structure", {}).get("total_pages", len(pages))
    total_words = site.get("total_word_count", 0)
    duration = site.get("crawl_duration_sec", 0)
    duplicates = site.get("duplicate_pages", 0)
    image_count = site.get("image_count", 0)

    # Nav coverage
    nav_cov = site.get("nav_coverage") or {}
    nav_found = nav_cov.get("found", [])
    nav_missing = nav_cov.get("missing", [])
    nav_pct = nav_cov.get("coverage", 0) * 100

    # Product coverage
    prod_cov = site.get("product_coverage") or {}
    prod_overall = prod_cov.get("overall_coverage", 0) * 100
    prod_details = prod_cov.get("coverage", {})

    # Features
    features = site.get("detected_features", {})
    portals = features.get("portals", {})
    integrations = features.get("integrations", [])
    api_hints = features.get("api_hints", [])

    # Page type breakdown
    page_types = site.get("structure", {}).get("page_types", {})

    # Homepage data
    homepage = pages[0] if pages else {}
    nav_links = homepage.get("nav_links", [])
    hero_text = homepage.get("hero_text", "")
    tagged_blocks = homepage.get("tagged_blocks", [])
    crawl_hints = homepage.get("crawl_hints", [])

    # Block type counts
    block_counts = {}
    for b in tagged_blocks:
        bt = b.get("block_type", "unknown")
        block_counts[bt] = block_counts.get(bt, 0) + 1

    # Pre-render dynamic sections
    page_types_rows = _render_page_types_rows(page_types)
    block_counts_rows = _render_block_counts_rows(block_counts)
    crawl_hints_rows = _render_crawl_hints_rows(crawl_hints)
    product_rows = _render_product_rows(prod_details)
    pages_rows = _render_pages_rows(pages)
    tagged_blocks_html = _render_tagged_blocks(tagged_blocks)
    nav_links_html = _render_nav_links(nav_links)

    # Nav coverage tags
    found_tags = "".join(f'<span class="tag tag-found">{escape(s)}</span>' for s in nav_found) or "<em>none</em>"
    missing_tags = "".join(f'<span class="tag tag-missing">{escape(s)}</span>' for s in nav_missing) or "<em>none</em>"

    # Portals
    portal_links = ", ".join(f'<a href="{escape(url)}">{escape(ptype)}</a>' for ptype, url in portals.items()) if portals else "<em>none</em>"
    integrations_str = ", ".join(escape(i) for i in integrations) if integrations else "<em>none</em>"
    api_hints_str = ", ".join(f"<code>{escape(a)}</code>" for a in api_hints) if api_hints else "<em>none</em>"

    # Progress bar class
    nav_bar_class = ""
    if nav_pct < 50:
        nav_bar_class = " danger"
    elif nav_pct < 80:
        nav_bar_class = " warning"

    prod_bar_class = " warning" if prod_overall < 80 else ""

    # Hero text preview
    hero_preview = escape(hero_text[:500]) + ("..." if len(hero_text) > 500 else "") if hero_text else "(none)"

    # Crawl hints section
    if crawl_hints:
        crawl_hints_section = f"""<table>
          <tr><th>Feature</th><th>Subtree</th><th>Priority</th></tr>
          {crawl_hints_rows}
        </table>"""
    else:
        crawl_hints_section = "<em>No crawl hints detected</em>"

    # Product coverage section
    if prod_details:
        product_section = f"""<div class="card section-full">
        <h2>Product Coverage</h2>
        <div class="progress" style="margin-bottom: 12px;">
          <div class="progress-bar{prod_bar_class}" style="width: {prod_overall}%;"></div>
        </div>
        <div style="font-size: 18px; margin-bottom: 12px;">{prod_overall:.0f}% overall</div>
        <table>
          <tr><th>Product</th><th>Covered</th><th>Pages</th><th>Terms Found</th></tr>
          {product_rows}
        </table>
      </div>"""
    else:
        product_section = ""

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Crawl Report: {escape(company)}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      margin: 0; padding: 24px; background: #f5f5f5; color: #333;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    header {{ background: #1a1a2e; color: #fff; padding: 24px; border-radius: 8px; margin-bottom: 24px; }}
    header h1 {{ margin: 0 0 8px 0; }}
    header .meta {{ opacity: 0.8; font-size: 14px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }}
    .card {{ background: #fff; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    .card h2 {{ margin: 0 0 16px 0; font-size: 16px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
    .stat {{ font-size: 32px; font-weight: bold; color: #1a1a2e; }}
    .stat-label {{ font-size: 12px; color: #888; }}
    .stat-row {{ display: flex; gap: 24px; flex-wrap: wrap; }}
    .stat-item {{ text-align: center; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid #eee; }}
    th {{ color: #666; font-weight: 500; }}
    .tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin: 2px; }}
    .tag-found {{ background: #d4edda; color: #155724; }}
    .tag-missing {{ background: #f8d7da; color: #721c24; }}
    .tag-hint {{ background: #fff3cd; color: #856404; }}
    .progress {{ background: #e9ecef; border-radius: 4px; height: 8px; overflow: hidden; }}
    .progress-bar {{ height: 100%; background: #28a745; }}
    .progress-bar.warning {{ background: #ffc107; }}
    .progress-bar.danger {{ background: #dc3545; }}
    pre {{ background: #f7f7f7; padding: 12px; border-radius: 4px; overflow-x: auto; font-size: 12px; }}
    .block-list {{ max-height: 300px; overflow-y: auto; }}
    .block-item {{ padding: 8px; border-bottom: 1px solid #eee; font-size: 13px; }}
    .block-type {{ font-weight: bold; color: #666; }}
    a {{ color: #007bff; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .section-full {{ grid-column: 1 / -1; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>{escape(company)}</h1>
      <div class="meta">
        Domain: {escape(domain)} | Profile: {escape(profile_name)} |
        Crawled: {escape(site.get('snapshot_date', 'unknown'))} |
        Duration: {duration:.1f}s
      </div>
    </header>

    <div class="grid">
      <!-- Stats Card -->
      <div class="card">
        <h2>Crawl Stats</h2>
        <div class="stat-row">
          <div class="stat-item">
            <div class="stat">{total_pages}</div>
            <div class="stat-label">Pages</div>
          </div>
          <div class="stat-item">
            <div class="stat">{total_words:,}</div>
            <div class="stat-label">Words</div>
          </div>
          <div class="stat-item">
            <div class="stat">{image_count}</div>
            <div class="stat-label">Images</div>
          </div>
          <div class="stat-item">
            <div class="stat">{duplicates}</div>
            <div class="stat-label">Duplicates</div>
          </div>
        </div>
      </div>

      <!-- Nav Coverage Card -->
      <div class="card">
        <h2>Nav Coverage</h2>
        <div class="progress" style="margin-bottom: 12px;">
          <div class="progress-bar{nav_bar_class}" style="width: {nav_pct}%;"></div>
        </div>
        <div style="font-size: 24px; font-weight: bold; margin-bottom: 8px;">{nav_pct:.0f}%</div>
        <div style="margin-bottom: 8px;">
          <strong>Found:</strong> {found_tags}
        </div>
        <div>
          <strong>Missing:</strong> {missing_tags}
        </div>
      </div>

      <!-- Page Types Card -->
      <div class="card">
        <h2>Page Types</h2>
        <table>
          <tr><th>Type</th><th>Count</th></tr>
          {page_types_rows}
        </table>
      </div>

      <!-- Block Tagging Card -->
      <div class="card">
        <h2>Block Tagging (Homepage)</h2>
        <table>
          <tr><th>Block Type</th><th>Count</th></tr>
          {block_counts_rows}
        </table>
        <div style="margin-top: 12px; font-size: 12px; color: #666;">
          Total tagged blocks: {len(tagged_blocks)}
        </div>
      </div>

      <!-- Features Card -->
      <div class="card">
        <h2>Detected Features</h2>
        <div style="margin-bottom: 12px;">
          <strong>Portals:</strong> {portal_links}
        </div>
        <div style="margin-bottom: 12px;">
          <strong>Integrations:</strong> {integrations_str}
        </div>
        <div>
          <strong>API Hints:</strong> {api_hints_str}
        </div>
      </div>

      <!-- Crawl Hints Card -->
      <div class="card">
        <h2>Crawl Hints (Homepage)</h2>
        {crawl_hints_section}
      </div>

      <!-- Hero Text Card -->
      <div class="card section-full">
        <h2>Hero Text (Homepage)</h2>
        <pre>{hero_preview}</pre>
      </div>

      <!-- Nav Links Card -->
      <div class="card section-full">
        <h2>Nav Links (Homepage)</h2>
        <div style="display: flex; flex-wrap: wrap; gap: 8px;">
          {nav_links_html}
        </div>
      </div>

      <!-- Tagged Blocks Sample -->
      <div class="card section-full">
        <h2>Tagged Blocks Sample (First 20)</h2>
        <div class="block-list">
          {tagged_blocks_html}
        </div>
      </div>

      <!-- Product Coverage (if applicable) -->
      {product_section}

      <!-- Pages Summary -->
      <div class="card section-full">
        <h2>Pages Summary</h2>
        <table>
          <tr><th>Path</th><th>Type</th><th>Words</th><th>Images</th><th>Product</th><th>Dup?</th></tr>
          {pages_rows}
        </table>
      </div>

    </div>
  </div>
</body>
</html>"""

    return html


def main():
    parser = argparse.ArgumentParser(description="Test crawl and generate HTML report")
    parser.add_argument("--domain", required=True, help="Domain to crawl")
    parser.add_argument("--profile", default="trucking", help="Crawl profile")
    parser.add_argument("--depth", type=int, default=2, help="Max crawl depth")
    parser.add_argument("--max-pages", type=int, default=20, help="Max pages to crawl (for testing)")
    parser.add_argument("--js", action="store_true", help="Use JS rendering")
    parser.add_argument("--out", help="Output HTML path")
    args = parser.parse_args()

    # Load profile
    profile = load_profile(args.profile)
    # Override max_pages for testing
    profile.max_pages = args.max_pages
    profile.max_depth = args.depth

    print(f"=== Crawl Test: {args.domain} ===")
    print(f"Profile: {profile.name}")
    print(f"Max depth: {profile.max_depth}, Max pages: {profile.max_pages}")
    print()

    # Create carrier dict for crawl_site
    carrier = {
        "domain": args.domain,
        "name": args.domain.split(".")[0].title(),
        "category": "test",
        "tier": 0,
    }

    # Run crawl
    start = time.time()
    site_data = crawl_site(
        carrier,
        max_depth=args.depth,
        use_js=args.js,
        profile=profile,
    )
    elapsed = time.time() - start

    print()
    print(f"=== Crawl Complete: {elapsed:.1f}s ===")
    print(f"Pages: {len(site_data.get('pages', []))}")
    print(f"Words: {site_data.get('total_word_count', 0):,}")

    # Generate report
    html = render_site_report(site_data, args.profile)

    # Write report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    domain_slug = args.domain.replace(".", "_")
    out_path = Path(args.out) if args.out else REPORT_DIR / f"test_{domain_slug}.html"
    out_path.write_text(html, encoding="utf-8")

    print()
    print(f"=== Report Written ===")
    print(f"  {out_path}")
    print(f"  Open in browser: file://{out_path.absolute()}")


if __name__ == "__main__":
    main()
