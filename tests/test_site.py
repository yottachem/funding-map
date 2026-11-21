"""The browser picker (site/static/picker.js) gives the same roadmap as tracker/picker.py, field for field."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest

from tracker import picker
from tracker.picker import Profile

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
TODAY = date(2026, 11, 20)

EXTRA = [
    Profile(id="all", label="all", entity="small-business", state="MA",
            domains=["life-science-tools", "diagnostics", "materials", "energy-climate", "hardware"]),
    Profile(id="uni", label="uni", entity="academic", domains=["materials", "hardware"], trl=3, prep_days=0),
    Profile(id="p2", label="p2", entity="small-business", state="MA", domains=["diagnostics", "energy-climate"],
            held=["nsf-sbir-2", "doe-sbir-1"], trl=6, runway_months=4, cash_need=1),
]


def js(profile: Profile, start: date, data: dict) -> dict:
    payload = json.dumps({"data": data, "profile": asdict(profile), "start": start.isoformat()})
    out = subprocess.run([NODE, str(ROOT / "tests/picker_parity.js")], input=payload, capture_output=True, text=True,
                         check=True)
    return json.loads(out.stdout)


def py(profile: Profile, start: date) -> dict:
    rm = json.loads(picker.to_json(picker.pick(profile, start)))
    return {"start": rm["start"], "end": rm["end"], "options": rm["options"],
            "excluded": [list(e) for e in rm["excluded"]], "summary": rm["summary"]}


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("prof", picker.load_profiles() + EXTRA, ids=lambda p: p.id)
@pytest.mark.parametrize("start", [TODAY, date(2027, 2, 28)], ids=str)
def test_browser_picker_matches_python(prof, start):
    data = picker.site_data()
    a, b = py(prof, start), js(prof, start, data)
    a["summary"].pop("expected_basis")
    a["summary"]["coverage"] = b["summary"]["coverage"] = None     # display only; rounding differs by design
    assert b == a


def test_site_data_is_json_and_complete():
    data = json.loads(json.dumps(picker.site_data()))
    assert len(data["programs"]) == len(picker.registry.programs())
    assert all(p["odds_basis"] for p in data["programs"]) and len(data["examples"]) == 3


# ---------------------------------------------------------------- built pages

@pytest.fixture(scope="module")
def dist(tmp_path_factory):
    import importlib.util
    spec = importlib.util.spec_from_file_location("site_build", ROOT / "site/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    build.DIST = tmp_path_factory.mktemp("dist")
    build.main(preview=True, today=TODAY)
    return build.DIST


def test_every_program_has_a_page(dist):
    ids = {p["id"] for p in picker.registry.programs()}
    assert {f.stem for f in (dist / "program").glob("*.html")} == ids
    for page in ("index", "roadmap", "programs", "paths", "methods", "status"):
        assert (dist / f"{page}.html").exists(), page


def test_pages_name_no_private_project(dist):
    for f in dist.rglob("*.html"):
        text = f.read_text().lower()
        assert "nonlinear" not in text and "ulva" not in text, f.name


def test_examples_are_labeled_fictional(dist):
    home = (dist / "index.html").read_text()
    assert home.count("chip fict") == 3 and "None describes a real company" in home


def test_unpublished_odds_are_never_filled_in(dist):
    rows = (dist / "programs.html").read_text().count("Not published")
    assert rows == sum(1 for p in picker.registry.programs() if p["success"].get("rate") is None)


def test_methods_explains_low_expected_values(dist):
    m = (dist / "methods.html").read_text()
    assert 'id="ev"' in m and "why it is low" in m


def test_roadmap_page_embeds_the_picker_data(dist):
    import re
    page = (dist / "roadmap.html").read_text()
    blob = re.search(r'<script type="application/json" id="fm-data">(.*?)</script>', page, re.S).group(1)
    assert len(json.loads(blob)["programs"]) == len(picker.registry.programs())
    assert (dist / "picker.js").exists() and (dist / "roadmap.js").exists()
