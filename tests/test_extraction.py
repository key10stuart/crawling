from pathlib import Path

from fetch.extractor import extract_from_capture


def test_extract_from_capture_tags_blocks(tmp_path: Path):
    html = """
    <html>
      <head><title>Test Page</title></head>
      <body>
        <header><nav><a href="/about">About</a></nav></header>
        <main>
          <h1>Welcome</h1>
          <p>Main content here.</p>
          <img src="https://example.com/hero.jpg" alt="Hero">
          <a href="https://example.com/file.pdf">Download PDF</a>
        </main>
        <footer>© 2026 Test Co</footer>
      </body>
    </html>
    """
    html_path = tmp_path / "page.html"
    html_path.write_text(html, encoding="utf-8")

    result = extract_from_capture(
        html_path=html_path,
        url="https://example.com/",
    )

    tagged = result.get("tagged_blocks", [])
    assert any(b.get("block_type") == "nav_block" for b in tagged)
    assert any(b.get("block_type") == "footer_block" for b in tagged)

    assets = result.get("assets", [])
    assert any(a.get("asset_type") == "image" for a in assets)
    assert any(a.get("asset_type") == "document" for a in assets)


def test_asset_context_enrichment(tmp_path: Path):
    """Verify assets have block_type, context_text, and classification."""
    html = """
    <html>
      <body>
        <header>
          <nav><img src="/logo.png" alt="Company Logo"></nav>
        </header>
        <section class="hero-banner">
          <img src="/hero.jpg" alt="Hero banner">
        </section>
        <main>
          <p>Some content here.</p>
          <img src="/content.jpg" alt="Content image">
          <img src="/decorative.jpg">
        </main>
        <footer>
          <img src="/footer-icon.png">
        </footer>
      </body>
    </html>
    """
    html_path = tmp_path / "page.html"
    html_path.write_text(html, encoding="utf-8")

    result = extract_from_capture(html_path=html_path, url="https://example.com/")
    assets = result.get("assets", [])

    # Find each asset
    logo = next((a for a in assets if "logo" in a.get("url", "")), None)
    hero = next((a for a in assets if "hero" in a.get("url", "")), None)
    content = next((a for a in assets if "content" in a.get("url", "")), None)
    decorative = next((a for a in assets if "decorative" in a.get("url", "")), None)

    # Check block_type
    assert logo and logo.get("block_type") == "nav"
    assert hero and hero.get("block_type") == "hero"
    assert content and content.get("block_type") == "main"
    assert decorative and decorative.get("block_type") == "main"

    # Check classification
    assert logo.get("classification") == "logo"
    assert hero.get("classification") == "hero_image"
    assert content.get("classification") == "content_image"
    assert decorative.get("classification") == "decorative"


def test_link_categorization(tmp_path: Path):
    """Verify links are categorized as nav/content/external/documents."""
    html = """
    <html>
      <body>
        <header>
          <nav>
            <a href="/">Home</a>
            <a href="/about">About</a>
            <a href="/services">Services</a>
          </nav>
        </header>
        <main>
          <a href="/contact">Contact Us</a>
          <a href="https://external.com/partner">Partner Link</a>
          <a href="/brochure.pdf">Download Brochure</a>
        </main>
        <footer>
          <a href="/privacy">Privacy</a>
        </footer>
      </body>
    </html>
    """
    html_path = tmp_path / "page.html"
    html_path.write_text(html, encoding="utf-8")

    result = extract_from_capture(html_path=html_path, url="https://example.com/")
    links = result.get("links", {})

    # Check nav links
    nav_urls = [l.get("url") for l in links.get("nav", [])]
    assert any("/about" in u for u in nav_urls)
    assert any("/services" in u for u in nav_urls)

    # Check external links
    external_urls = [l.get("url") for l in links.get("external", [])]
    assert any("external.com" in u for u in external_urls)

    # Check document links
    doc_urls = [l.get("url") for l in links.get("documents", [])]
    assert any("brochure.pdf" in u for u in doc_urls)

    # Check content links (not in nav, not external, not document)
    content_urls = [l.get("url") for l in links.get("content", [])]
    # Contact and Privacy should be content links (not in nav)
    assert len(content_urls) >= 1
