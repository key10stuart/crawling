#!/usr/bin/env python3
"""Render extraction and open side-by-side with original site."""

import subprocess
import sys
import json
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def main():
    if len(sys.argv) < 2:
        print("Usage: ./test_render.sh <site_json> [page_index]")
        print("  e.g. ./test_render.sh corpus/sites/schneider_com.json 0")
        sys.exit(1)

    site_path = Path(sys.argv[1])
    index = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    if not site_path.exists():
        print(f"Not found: {site_path}")
        sys.exit(1)

    # Load site JSON
    with open(site_path) as f:
        site = json.load(f)

    pages = site.get("pages", [])
    if not pages:
        print("No pages in site JSON")
        sys.exit(1)

    if index >= len(pages):
        print(f"Index {index} out of range (0-{len(pages)-1})")
        sys.exit(1)

    page = pages[index]
    url = page.get("url", "")

    # Render extraction
    domain = site.get("domain", "site").replace(".", "_")
    out_path = Path("corpus/reports") / f"{domain}_{index}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run([
        sys.executable, "scripts/render_extraction.py",
        "--site", str(site_path),
        "--index", str(index),
        "--out", str(out_path),
    ], check=True)

    # Open both in browser
    print(f"Opening: {out_path}")
    print(f"Opening: {url}")

    webbrowser.open(f"file://{out_path.absolute()}")
    webbrowser.open(url)

if __name__ == "__main__":
    main()
