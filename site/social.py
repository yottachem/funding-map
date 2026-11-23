"""Render the social preview card (site/static/social.png, 1200x630) from the registry.

Run locally after a registry change that moves the size vs odds chart; CI has no Chrome, so the PNG is committed.
Run: uv run python site/social.py
"""
import datetime as dt
import subprocess
import sys
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402
import charts  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def main():
    recs = build.program_records(dt.date.today())
    pts, _ = build.chart_points(recs)
    for p in pts:
        p["label"] = ""  # the card is too small for program labels
    svg = charts.size_odds(pts, width=700, height=500, desc="Programs by typical award size and published success rate")
    n_fed = sum(not r["p"].get("state") for r in recs.values())
    html = Environment(loader=FileSystemLoader(HERE / "templates")).get_template("social.html.j2").render(
        chart=svg, site_url=build.SITE_URL, n_programs=len(recs), n_federal=n_fed, n_state=len(recs) - n_fed,
        n_rated=len(pts))
    out = HERE / "static" / "social.png"
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "social.html"
        page.write_text(html)
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--window-size=1200,630", "--virtual-time-budget=4000", f"--screenshot={out}", page.as_uri()],
                       check=True, capture_output=True)
    print(out)


if __name__ == "__main__":
    main()
