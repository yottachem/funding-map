"""Build the site into site/dist from the registry, the award files and the opportunity feed.

Pages: home (picker form, examples, closing soon, size vs odds chart), roadmap (the picker in the browser:
site/static/picker.js, held to tracker/picker.py by tests/test_site.py), programs (filterable table), one page per
program (grade block first), stacking paths, methods, status. Every page but the roadmap reads without JavaScript.

Rules the pages follow:
  figures   every size, rate, timing and date links the source key it came from in programs.yaml
  odds      published rates only; "Not published" is shown as such and never filled in
  dates     registry deadlines and DoD topic close dates only, each marked "verify on the funder's page"
  examples  the three fictional profiles in reference/example_profiles.yaml, labeled fictional wherever they appear

Usage: uv run python site/build.py [--preview] [--today YYYY-MM-DD]
--preview marks every page as an internal preview (noindex, banner).
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import charts  # noqa: E402  (site/charts.py)
from ingest import common  # noqa: E402
from tracker import picker, registry  # noqa: E402

DIST = HERE / "dist"
REPO = "https://github.com/yottachem/funding-map"
SITE_URL = "https://yottachem.github.io/funding-map/"
ANALYTICS_TOKEN = "ee99837aed054d67b79a567044baec28"  # Cloudflare Web Analytics (shared yottachem.github.io token)

DOMAIN = {"life-science-tools": "Life science tools", "diagnostics": "Diagnostics", "materials": "Materials",
          "energy-climate": "Energy and climate", "hardware": "Hardware and robotics"}
STAGE = {"entry": "Entry", "follow-on": "Follow-on", "scale": "Scale", "training": "Training", "cost-share": "Cost share"}
STAGE_NOTE = {"entry": "First non-dilutive money; no prior award needed", "follow-on": "Needs an earlier award",
              "scale": "Larger awards for later-stage work", "training": "Customer discovery and training",
              "cost-share": "Needs matching funds or an earlier award"}
VEHICLE = {"grant": "Grant", "contract": "Contract", "cooperative-agreement": "Cooperative agreement",
           "other-transaction": "Other transaction", "grant-or-contract": "Grant or contract",
           "milestone-award": "Milestone award", "via-intermediary": "Through an intermediary"}
STATUS = {"open": "Open", "between-rounds": "Between rounds", "upcoming": "Upcoming", "paused": "Paused",
          "closed": "Closed", "unknown": "Unknown"}
ENTITY = {"small-business": "Small business", "academic": "University", "either": "Small business or university"}
JURIS = {"federal": "Federal", "massachusetts": "Massachusetts"}
NAV = [("index", "Home"), ("roadmap", "Roadmap"), ("programs", "Programs"), ("paths", "Stacking paths"),
       ("methods", "Methods"), ("status", "Status")]
CURATED = [("reference/programs.yaml", "Program registry: rules, caps, published success rates, deadlines, stacking, sources"),
           ("reference/signals.yaml", "What each feed searches for, per program"),
           ("reference/example_profiles.yaml", "The three fictional example profiles")]
SOON_DAYS = 30


def host(url: str) -> str:
    h = urlparse(url).netloc
    return h[4:] if h.startswith("www.") else h


def short(name: str) -> str:
    return name.replace("SBIR/STTR ", "").replace(" SBIR Phase", " Phase")


def months(days) -> str:
    if not days:
        return ""
    a, b = (round(d / 30.4) for d in days)
    return f"{a} months" if a == b else f"{a}-{b} months"


def last_changed(path: str) -> str | None:
    r = subprocess.run(["git", "log", "-1", "--format=%cs", "--", path], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() or None


# ---------------------------------------------------------------- records

def program_records(today: dt.date) -> dict[str, dict]:
    progs = registry.programs()
    srcs = registry.sources()
    stats, recent = registry.sbir_stats(), registry.recent_stats()
    opps = picker.read_opps()
    by_id = {p["id"]: p for p in progs}
    led_by = defaultdict(list)
    for p in progs:
        for r in (p.get("requires") or {}).get("any", []):
            led_by[r].append(p["id"])

    def src(key):
        s = srcs.get(key)
        return {"key": key, "url": s["url"], "host": host(s["url"]), "tier": s["tier"], "note": s.get("note", "")} if s else None

    recs = {}
    for p in progs:
        size, size_basis = picker.typical_size(p, stats, recent)
        days, cash_basis = picker.cash_days(p, stats)
        rate = p["success"].get("rate")
        keys = []
        for k in p.get("sources", []) + [p["award"].get("source"), p["success"].get("source"), p["success"].get("also"),
                                         (p.get("timing") or {}).get("source"), p["deadlines"].get("source"),
                                         (p.get("lead") or {}).get("source")]:
            if k and k not in keys:
                keys.append(k)
        if p.get("award_data"):
            keys.append("sbir-awards")
        dates = []
        for d in p["deadlines"].get("next") or []:
            if d >= today:
                dates.append({"date": d, "what": "Deadline", "src": src(p["deadlines"].get("source"))})
        sol = []
        for o in opps.get(p["id"], []):
            if o["status"] not in ("posted", "forecasted"):
                continue
            sol.append(o)
            if o["source"] == "dsip" and o["close_date"] and dt.date.fromisoformat(o["close_date"]) >= today:
                dates.append({"date": dt.date.fromisoformat(o["close_date"]),
                              "what": f"DoD topics close: {o['title']} ({o['status']})", "src": src("dsip-topics")})
        dates.sort(key=lambda d: d["date"])
        rec = p.get("award_recent")
        hist = []
        for r in sorted(recent.get((rec["dataset"], rec["group"]), []) if rec else [], key=lambda r: r["fiscal_year"]):
            n = lambda v: float(v) if v not in ("", None) else None  # noqa: E731
            hist.append({"year": r["fiscal_year"], "awards": int(r["awards"]), "p10": n(r["amount_p10"]),
                         "median": n(r["amount_median"]), "p90": n(r["amount_p90"]), "pulled": r.get("pulled", "")})
        sbir = registry.award_row(p, stats)
        req = p.get("requires") or {}
        recs[p["id"]] = {
            "p": p, "id": p["id"], "name": p["name"], "short": short(p["name"]),
            "size": size, "size_basis": size_basis, "cap": p["award"].get("max"),
            "rate": rate, "odds_basis": p["success"].get("basis") or p["success"].get("note") or "",
            "cash_days": days, "cash_basis": cash_basis, "cash_months": months(days),
            "timing_basis": (p.get("timing") or {}).get("basis", ""),
            "dates": dates, "next_date": dates[0]["date"] if dates else None, "solicitations": sol,
            "history": hist, "sbir": sbir,
            "history_svg": Markup(charts.history(hist, desc=f"{p['name']} award sizes by fiscal year"))
            if hist and any(h["median"] for h in hist) else "",
            "requires": [by_id[r] for r in req.get("any", [])], "after_months": req.get("after_months"),
            "leads_to": [by_id[q] for q in led_by[p["id"]]],
            "sources": [s for s in (src(k) for k in keys) if s],
            "src": {f: src(k) for f, k in (("award", p["award"].get("source")), ("success", p["success"].get("source")),
                                           ("timing", (p.get("timing") or {}).get("source")),
                                           ("deadlines", p["deadlines"].get("source")),
                                           ("lead", (p.get("lead") or {}).get("source"))) if k},
        }
    return recs


def chart_points(recs) -> tuple[list[dict], list[dict]]:
    pts, missing = [], []
    for r in recs.values():
        if r["rate"] is None or r["size"] is None:
            missing.append(r)
            continue
        pts.append({"label": r["short"], "href": f"program/{r['id']}.html", "size": r["size"], "rate": r["rate"],
                    "kind": "entry" if r["p"]["stage"] == "entry" else "follow-on",
                    "tip": f"{r['name']}: {charts.fmt(r['size'])} typical ({r['size_basis']}); "
                           f"{r['rate']:.0%} published success rate ({r['p']['success']['year']})"})
    return pts, missing


def closing_soon(recs, today):
    hi = today + dt.timedelta(days=SOON_DAYS)
    soon = [(d["date"], r, d) for r in recs.values() for d in r["dates"] if d["date"] <= hi]
    later = sorted(((d["date"], r, d) for r in recs.values() for d in r["dates"] if d["date"] > hi), key=lambda t: t[0])
    return sorted(soon, key=lambda t: t[0]), later[:5]


def paths(recs):
    """Stacking trees from `requires`: roots are programs that gate something and need nothing themselves."""
    def node(pid, depth, odds, seen):
        r = recs[pid]
        chained = odds * r["rate"] if odds is not None and r["rate"] is not None else None
        kids = [node(q["id"], depth + 1, chained, seen | {q["id"]}) for q in r["leads_to"]
                if q["id"] not in seen and depth < picker.MAX_DEPTH]
        return {"r": r, "odds": chained, "kids": kids}

    roots = [r for r in recs.values() if r["leads_to"] and not r["requires"]]
    return [node(r["id"], 1, 1.0, {r["id"]}) for r in roots]


def status_context(recs, today):
    opps = common.read_opps()
    last = lambda src: max((o["last_seen"] for o in opps if o["source"] == src), default=None)  # noqa: E731
    recent = registry.recent_stats()
    pulled = defaultdict(str)
    for (ds, _), rows in recent.items():
        for r in rows:
            pulled[ds] = max(pulled[ds], r.get("pulled", ""))
    lm = ROOT / "data/raw/sbir_award_data.last_modified"
    queue = common.read_queue()
    derived = {r["program"]: r for r in common_csv(ROOT / "data/program_status.csv")}
    feeds = [
        {"name": "Grants.gov", "what": "Open and forecast solicitations for grant programs (NIH, NSF, NOAA, USDA)",
         "cadence": "Weekly", "last": last("grants.gov")},
        {"name": "DoD SBIR/STTR Innovation Portal", "what": "DoD topic releases and close dates", "cadence": "Weekly",
         "last": last("dsip")},
        {"name": "SBIR.gov award data", "what": "Award sizes and days to award, 2022-2024", "cadence": "Quarterly",
         "last": parsedate_to_datetime(lm.read_text().strip()).date().isoformat() if lm.exists() else None},
        {"name": "NIH RePORTER", "what": "Recent NIH SBIR/STTR award sizes", "cadence": "Quarterly",
         "last": pulled["nih-reporter"] or None},
        {"name": "NSF Awards API", "what": "Recent NSF SBIR/STTR award sizes", "cadence": "Quarterly",
         "last": pulled["nsf-awards"] or None},
        {"name": "USAspending", "what": "ARPA-E OPEN award sizes", "cadence": "Quarterly", "last": pulled["arpa-e"] or None},
    ]
    mismatch = [(recs[pid], d) for pid, d in derived.items()
                if pid in recs and d.get("derived") and d["derived"] != d["yaml_status"]]
    by_status = defaultdict(list)
    for r in recs.values():
        by_status[r["p"]["status"]].append(r)
    return {"feeds": feeds, "open": sum(q["status"] == "open" for q in queue), "decided": sum(q["status"] != "open" for q in queue),
            "curated": [{"path": p, "what": w, "changed": last_changed(p)} for p, w in CURATED],
            "mismatch": mismatch, "by_status": [(s, STATUS[s], by_status[s]) for s in STATUS if by_status[s]]}


def common_csv(path):
    import csv
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- build

def main(preview=False, today=None):
    today = today or dt.date.today()
    recs = program_records(today)
    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["usd"] = charts.fmt
    env.filters["pct"] = lambda v: "–" if v is None else f"{v:.0%}"
    env.filters["day"] = lambda d: f"{d:%b} {d.day}, {d.year}" if d else "–"
    paused = [r for r in recs.values() if r["p"]["status"] == "paused"]
    examples = picker.load_profiles()
    data = picker.site_data()
    common_ctx = {"repo": REPO, "preview": preview, "site_url": SITE_URL, "built": today.isoformat(), "nav": NAV,
                  "analytics_token": "" if preview else ANALYTICS_TOKEN, "DOMAIN": DOMAIN, "STAGE": STAGE,
                  "STAGE_NOTE": STAGE_NOTE, "VEHICLE": VEHICLE, "STATUS": STATUS, "ENTITY": ENTITY, "JURIS": JURIS,
                  "paused": paused, "examples": examples, "verified": registry.data().get("verified_default"),
                  "n_programs": len(recs), "held_choices": [r for r in recs.values() if r["leads_to"]]}
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "program").mkdir(parents=True)

    def render(template, path, page, **ctx):
        (DIST / path).write_text(env.get_template(template).render(**common_ctx, page=page, **ctx))

    pts, missing = chart_points(recs)
    soon, later = closing_soon(recs, today)
    rated = [r for r in recs.values() if r["rate"] is not None]
    render("index.html.j2", "index.html", "index", soon=soon, later=later, soon_days=SOON_DAYS, missing=missing,
           chart=Markup(charts.size_odds(pts, desc="Programs by typical award size and published success rate")),
           n_rated=len(rated), rate_lo=min(r["rate"] for r in rated), rate_hi=max(r["rate"] for r in rated))
    render("roadmap.html.j2", "roadmap.html", "roadmap",
           data_json=Markup(json.dumps(data, separators=(",", ":")).replace("</", "<\\/")))
    render("programs.html.j2", "programs.html", "programs", recs=recs)
    for r in recs.values():
        render("program.html.j2", f"program/{r['id']}.html", "program", r=r, up="../")
    render("paths.html.j2", "paths.html", "paths", trees=paths(recs))
    entry_rated = sorted((r for r in rated if r["p"]["stage"] == "entry"), key=lambda r: r["rate"])
    render("methods.html.j2", "methods.html", "methods", rated=sorted(rated, key=lambda r: r["name"]),
           entry_rated=entry_rated, example=recs["nsf-sbir-1"])
    render("status.html.j2", "status.html", "status", **status_context(recs, today))
    for f in (HERE / "static").iterdir():
        shutil.copy(f, DIST / f.name)
    (DIST / ".nojekyll").touch()
    print(f"site/dist: {sum(1 for _ in DIST.rglob('*') if _.is_file())} files{' (preview)' if preview else ''}")


if __name__ == "__main__":
    args = sys.argv[1:]
    day = dt.date.fromisoformat(args[args.index("--today") + 1]) if "--today" in args else None
    main(preview="--preview" in args, today=day)
