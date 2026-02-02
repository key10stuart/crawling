#!/usr/bin/env python3
"""
Render extracted crawl output into a human-readable HTML report.

Usage:
  python scripts/render_extraction.py --site corpus/sites/jbhunt_com.json --index 0
  python scripts/render_extraction.py --site corpus/sites/jbhunt_com.json --url https://www.jbhunt.com
"""

import argparse
import json
from pathlib import Path
from html import escape


def _read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_page(site: dict, url: str | None, index: int | None) -> dict:
    pages = site.get("pages", [])
    if not pages:
        raise ValueError("No pages found in site JSON.")
    if url:
        for p in pages:
            if p.get("url") == url:
                return p
        raise ValueError(f"URL not found in site JSON: {url}")
    if index is None:
        return pages[0]
    if index < 0 or index >= len(pages):
        raise ValueError(f"Index out of range: {index}")
    return pages[index]


def _render_section_tree(tree: dict) -> str:
    if not tree:
        return ""

    def render_node(node: dict) -> str:
        ntype = node.get("type")
        if ntype == "section":
            heading = node.get("heading")
            level = node.get("level", 0)
            tag = f"h{max(2, min(6, level))}" if heading else "div"
            heading_html = f"<{tag}>{escape(heading)}</{tag}>" if heading else ""
            children_html = "".join(render_node(child) for child in node.get("children", []))
            return f"<section class=\"section level-{level}\">{heading_html}{children_html}</section>"
        if ntype == "text":
            text = node.get("text", "")
            return f"<p>{escape(text)}</p>"
        if ntype == "image":
            src = node.get("src_resolved") or node.get("src") or ""
            alt = node.get("alt") or ""
            title = node.get("title") or ""
            meta = []
            if node.get("width") or node.get("height"):
                meta.append(f"{node.get('width')}x{node.get('height')}")
            if node.get("tag"):
                meta.append(node.get("tag"))
            meta_html = f"<div class=\"meta\">{' | '.join(meta)}</div>" if meta else ""
            return (
                "<figure>"
                f"<img src=\"{escape(src)}\" alt=\"{escape(alt)}\" title=\"{escape(title)}\"/>"
                f"<figcaption>{escape(alt)}</figcaption>{meta_html}</figure>"
            )
        if ntype == "code":
            content = node.get("content", "")
            return f"<pre><code>{escape(content)}</code></pre>"
        return ""

    return render_node(tree)


def _render_flat_blocks(page: dict) -> str:
    html = []
    if page.get("main_content"):
        html.append("<h2>Main Content (article-focused)</h2>")
        html.append(f"<pre class=\"full-text\">{escape(page['main_content'])}</pre>")
    if page.get("full_text"):
        html.append("<h2>Full Text (structural)</h2>")
        html.append(f"<pre class=\"full-text\">{escape(page['full_text'])}</pre>")

    images = page.get("images", [])
    if images:
        html.append("<h2>Images</h2>")
        for img in images:
            src = img.get("src_resolved") or img.get("src") or ""
            alt = img.get("alt") or ""
            title = img.get("title") or ""
            html.append(
                "<figure>"
                f"<img src=\"{escape(src)}\" alt=\"{escape(alt)}\" title=\"{escape(title)}\"/>"
                f"<figcaption>{escape(alt)}</figcaption>"
                "</figure>"
            )

    code_blocks = page.get("code_blocks", [])
    if code_blocks:
        html.append("<h2>Code Blocks</h2>")
        for block in code_blocks:
            content = block.get("content", "")
            html.append(f"<pre><code>{escape(content)}</code></pre>")

    features = page.get("detected_features", {})
    if features:
        html.append("<h2>Detected Features</h2>")
        html.append("<dl>")
        portals = features.get("portals", [])
        if portals:
            html.append("<dt>Portals</dt><dd><ul>")
            for p in portals:
                ptype = p.get("type", "unknown")
                purl = p.get("url", "")
                html.append(f"<li><strong>{escape(ptype)}</strong>: <a href=\"{escape(purl)}\">{escape(purl)}</a></li>")
            html.append("</ul></dd>")
        forms = features.get("forms", [])
        if forms:
            html.append("<dt>Forms</dt><dd><ul>")
            for f in forms:
                purpose = f.get("purpose", "unknown")
                fields = f.get("fields", 0)
                html.append(f"<li>{escape(purpose)} ({fields} fields)</li>")
            html.append("</ul></dd>")
        integrations = features.get("integrations", [])
        if integrations:
            html.append(f"<dt>Integrations</dt><dd>{escape(', '.join(integrations))}</dd>")
        api_hints = features.get("api_hints", [])
        if api_hints:
            html.append("<dt>API Hints</dt><dd><ul>")
            for api in api_hints:
                html.append(f"<li><code>{escape(api)}</code></li>")
            html.append("</ul></dd>")
        html.append("</dl>")

    return "".join(html)


def _render_tagged_blocks(page: dict) -> str:
    blocks = page.get("tagged_blocks", [])
    if not blocks:
        return "<p>(no tagged blocks)</p>"

    grouped: dict[str, list[dict]] = {}
    for b in blocks:
        grouped.setdefault(b.get("block_type", "unknown"), []).append(b)

    parts = []
    for block_type, items in grouped.items():
        parts.append(f"<h3>{escape(block_type)}</h3>")
        for item in items:
            content_type = item.get("content_type", "text")
            content = item.get("content", "")
            url = item.get("url")
            meta = item.get("metadata", {})
            if content_type == "image":
                src = url or ""
                parts.append(
                    "<figure>"
                    f"<img src=\"{escape(src)}\" alt=\"{escape(content)}\"/>"
                    f"<figcaption>{escape(content)}</figcaption>"
                    "</figure>"
                )
            else:
                line = escape(content)
                if url:
                    line += f" <span class=\"meta\">({escape(url)})</span>"
                if meta:
                    line += f" <span class=\"meta\">{escape(str(meta))}</span>"
                parts.append(f"<div class=\"tagged\">{line}</div>")
    return "".join(parts)


def _render_html(site: dict, page: dict, show_open_original: bool = True) -> str:
    title = page.get("title") or page.get("url") or "Extraction Report"
    original_url = page.get("url", "")
    stats = {
        "url": original_url,
        "word_count": page.get("word_count", 0),
        "page_type": page.get("page_type", ""),
    }
    section_tree = page.get("section_tree")

    open_original_html = ""
    if show_open_original and original_url:
        open_original_html = f'''
    <div style="margin-top: 12px;">
      <a href="{escape(original_url)}" target="_blank"
         style="display: inline-block; padding: 8px 16px; background: #2a4b8d; color: white;
                text-decoration: none; border-radius: 4px; font-family: sans-serif; font-size: 14px;">
        Open Original Site &rarr;
      </a>
      <span style="margin-left: 12px; color: #666; font-size: 12px;">
        Compare extraction against live site
      </span>
    </div>'''

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 0; line-height: 1.5; color: #222; }}
    header {{ margin: 0; padding: 24px; border-bottom: 1px solid #eee; background: #fafafa; }}
    .meta {{ color: #666; font-size: 12px; }}
    .layout {{ display: grid; grid-template-columns: 260px 1fr; gap: 24px; padding: 24px; }}
    .sidebar {{ position: sticky; top: 16px; align-self: start; }}
    .nav {{ border: 1px solid #ddd; border-radius: 8px; padding: 12px; background: #fff; }}
    .nav a {{ display: block; color: #2a4b8d; text-decoration: none; margin: 6px 0; }}
    .nav a:hover {{ text-decoration: underline; }}
    .grid {{ display: grid; grid-template-columns: 1fr; gap: 24px; }}
    .panel {{ border: 1px solid #ddd; padding: 16px; border-radius: 8px; background: #fff; }}
    figure {{ margin: 12px 0; }}
    img {{ max-width: 100%; height: auto; border: 1px solid #eee; }}
    pre {{ background: #f7f7f7; padding: 12px; overflow-x: auto; }}
    .full-text {{ white-space: pre-wrap; }}
    section.section {{ border-left: 2px solid #eee; padding-left: 12px; margin: 12px 0; }}
    h1, h2, h3, h4, h5, h6 {{ font-family: 'Trebuchet MS', sans-serif; }}
    dl {{ margin: 0; }}
    dt {{ font-weight: bold; margin-top: 8px; color: #444; }}
    dd {{ margin-left: 16px; }}
    dd ul {{ margin: 4px 0; padding-left: 20px; }}
    code {{ background: #f0f0f0; padding: 2px 4px; border-radius: 3px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .summary .card {{ border: 1px solid #eee; border-radius: 6px; padding: 10px; background: #fcfcfc; }}
    @media (max-width: 900px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .sidebar {{ position: static; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(title)}</h1>
    <div class="meta">URL: {escape(stats['url'])}</div>
    <div class="meta">Words: {stats['word_count']} | Type: {escape(stats['page_type'])}</div>
    {open_original_html}
  </header>
  <div class="layout">
    <aside class="sidebar">
      <div class="nav">
        <strong>Jump to</strong>
        <a href="#summary">Summary</a>
        <a href="#section-tree">Section Tree</a>
        <a href="#tagged-blocks">Tagged Blocks</a>
        <a href="#flat-extraction">Flat Extraction</a>
      </div>
    </aside>
    <main class="grid">
      <div class="panel" id="summary">
        <h2>Summary</h2>
        <div class="summary">
          <div class="card"><strong>URL</strong><div class="meta">{escape(stats['url'])}</div></div>
          <div class="card"><strong>Word Count</strong><div class="meta">{stats['word_count']}</div></div>
          <div class="card"><strong>Page Type</strong><div class="meta">{escape(stats['page_type'])}</div></div>
          <div class="card"><strong>Images</strong><div class="meta">{len(page.get("images", []))}</div></div>
          <div class="card"><strong>Code Blocks</strong><div class="meta">{len(page.get("code_blocks", []))}</div></div>
        </div>
      </div>
      <div class="panel" id="section-tree">
        <h2>Section Tree</h2>
        { _render_section_tree(section_tree) if section_tree else "<p>(no section tree)</p>" }
      </div>
      <div class="panel" id="tagged-blocks">
        <h2>Tagged Blocks (nav/hero/ui/footer)</h2>
        {_render_tagged_blocks(page)}
      </div>
      <div class="panel" id="flat-extraction">
        <h2>Flat Extraction</h2>
        {_render_flat_blocks(page)}
      </div>
    </main>
  </div>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render extraction report from crawl output JSON.")
    parser.add_argument("--site", required=True, help="Path to site JSON (corpus/sites/*.json)")
    parser.add_argument("--url", help="Page URL to render")
    parser.add_argument("--index", type=int, help="Page index to render (default 0)")
    parser.add_argument("--out", help="Output HTML path (default corpus/reports/<domain>_<index>.html)")
    args = parser.parse_args()

    site_path = Path(args.site)
    site = _read_json(site_path)
    page = _find_page(site, args.url, args.index)

    domain = site.get("domain", "site").replace(".", "_")
    idx = args.index if args.index is not None else 0
    default_out = Path("corpus/reports") / f"{domain}_{idx}.html"
    out_path = Path(args.out) if args.out else default_out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    html = _render_html(site, page)
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote report: {out_path}")


if __name__ == "__main__":
    main()
