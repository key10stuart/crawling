import json
from pathlib import Path

from scripts import crawl


def test_load_companies_json(tmp_path):
    data = [
        {"name": "A", "domain": "a.com", "category": "x", "tier": 1},
        {"name": "B", "domain": "b.com", "category": "x", "tier": 2},
    ]
    path = tmp_path / "companies.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = crawl.load_companies_file(str(path))
    assert isinstance(loaded, list)
    assert loaded[0]["domain"] == "a.com"


def test_load_companies_json_wrapped(tmp_path):
    data = {"carriers": [{"name": "C", "domain": "c.com", "category": "x", "tier": 1}]}
    path = tmp_path / "companies.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = crawl.load_companies_file(str(path))
    assert loaded[0]["domain"] == "c.com"
