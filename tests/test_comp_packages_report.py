import json
from pathlib import Path

from scripts import comp_packages_report as cpr


def _sample_site():
    return {
        "domain": "example.com",
        "company_name": "Example Carrier",
        "pages": [
            {
                "url": "https://example.com/drivers/pay",
                "title": "Driver Pay",
                "h1": "Driver Pay",
                "full_text": "Earn $1,500 per week with home time and benefits. CPM up to 70 cents per mile.",
                "changed_since_last": True,
            },
            {
                "url": "https://example.com/owner-operator",
                "title": "Owner Operator",
                "h1": "Owner Operator Program",
                "full_text": "Owner operator lease-to-own program. Fuel surcharge and settlement support.",
                "changed_since_last": False,
            },
        ],
    }


def test_comp_packages_report_json(tmp_path, monkeypatch):
    site_path = tmp_path / "site.json"
    site_path.write_text(json.dumps(_sample_site()), encoding="utf-8")

    out_path = tmp_path / "report.md"

    monkeypatch.setattr(
        "sys.argv",
        ["comp_packages_report.py", "--site", str(site_path), "--out", str(out_path), "--out-json"],
    )
    cpr.main()

    assert out_path.exists()
    json_path = out_path.with_suffix(".json")
    assert json_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["sites"][0]["domain"] == "example.com"
    assert "drivers" in data["sites"][0]["buckets"]
    assert data["sites"][0]["buckets"]["drivers"]


def test_comp_packages_diff(tmp_path, monkeypatch):
    base = _sample_site()
    newer = _sample_site()
    newer["pages"][0]["full_text"] += " Sign-on bonus available."

    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"

    old_report = tmp_path / "old_report.md"
    new_report = tmp_path / "new_report.md"

    old_path.write_text(json.dumps(base), encoding="utf-8")
    new_path.write_text(json.dumps(newer), encoding="utf-8")

    # Build JSON reports
    monkeypatch.setattr(
        "sys.argv",
        ["comp_packages_report.py", "--site", str(old_path), "--out", str(old_report), "--out-json"],
    )
    cpr.main()
    monkeypatch.setattr(
        "sys.argv",
        ["comp_packages_report.py", "--site", str(new_path), "--out", str(new_report), "--out-json"],
    )
    cpr.main()

    # Diff
    old_json = old_report.with_suffix(".json")
    new_json = new_report.with_suffix(".json")
    monkeypatch.setattr(
        "sys.argv",
        ["comp_packages_report.py", "--diff", str(old_json), str(new_json)],
    )
    cpr.main()

    diff_path = Path("corpus/reports")
    assert any(p.name.startswith("comp_packages_diff_") for p in diff_path.glob("comp_packages_diff_*.md"))
