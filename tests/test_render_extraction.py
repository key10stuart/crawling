import json

from scripts import render_extraction


def test_render_extraction(tmp_path):
    site = {
        "domain": "example.com",
        "pages": [
            {
                "url": "https://example.com/",
                "title": "Example",
                "page_type": "home",
                "word_count": 123,
                "images": [],
                "code_blocks": [],
                "section_tree": {"type": "section", "heading": None, "level": 0, "children": []},
            }
        ],
    }
    site_path = tmp_path / "site.json"
    site_path.write_text(json.dumps(site), encoding="utf-8")

    out_path = tmp_path / "report.html"
    html = render_extraction._render_html(site, site["pages"][0])
    out_path.write_text(html, encoding="utf-8")
    assert out_path.exists()
    assert "Section Tree" in html
