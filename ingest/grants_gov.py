"""Open and forecast opportunities from Grants.gov (search2 + fetchOpportunity; no key needed).

Weekly. Two passes:
  tracked    every opportunity number or pattern in signals.yaml `grants_gov` is looked up; matches go to
             reference/opportunities.csv (tier 1, auto-accepted). A stated award ceiling above the program's
             award.max queues a cap-change; nothing edits programs.yaml.
  discovery  keyword searches over forecasted and posted opportunities; untracked hits whose title has a discovery
             term and no exclude term are queued as new-program candidates.

Run: uv run python -m ingest.grants_gov [--dry-run]
"""
from __future__ import annotations

import argparse
import html
import re
from datetime import date, datetime

from ingest.common import (enqueue, merge_opps, programs, qid, read_opps, session, signals, write_opps,
                           write_snapshot)

SEARCH = "https://api.grants.gov/v1/api/search2"
FETCH = "https://api.grants.gov/v1/api/fetchOpportunity"
VIEW = "https://www.grants.gov/search-results-detail/{id}"
ROWS = 100


def search(s, pages: int = 3, **body) -> list[dict]:
    """search2 is a relevance-ranked full-text search, so hit counts run into the thousands; the useful hits are on
    the first pages (an exact opportunity number ranks first)."""
    body = {"oppStatuses": "forecasted|posted", "rows": ROWS, **body}
    hits, start = [], 0
    while True:
        r = s.post(SEARCH, json={**body, "startRecordNum": start}, timeout=60)
        r.raise_for_status()
        data = r.json()["data"]
        hits += data["oppHits"]
        start += ROWS
        if start >= data["hitCount"] or start >= pages * ROWS:
            return hits


def detail(s, opp_id: str) -> dict:
    r = s.post(FETCH, json={"opportunityId": int(opp_id)}, timeout=60)
    r.raise_for_status()
    return r.json()["data"]


def _date(v: str | None) -> str:
    """'03/04/2027' or 'Mar 04, 2027 12:00:00 AM EST' -> '2027-03-04'."""
    if not v:
        return ""
    for fmt in ("%m/%d/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(v[:12].strip() if fmt == "%b %d, %Y" else v, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _money(v) -> str:
    try:
        n = int(float(str(v).replace(",", "")))
        return str(n) if n > 1 else ""
    except (TypeError, ValueError):
        return ""


def matches(hit: dict, rules: dict) -> bool:
    if hit["number"] in rules.get("numbers", []):
        return True
    text = f"{hit['number']} {html.unescape(hit['title'])}"
    return any(re.search(p, text, re.I) for p in rules.get("patterns", []))


def tracked_programs(hit: dict) -> list[str]:
    return [pid for pid, rules in signals()["grants_gov"].items() if matches(hit, rules)]


def row(pid: str, hit: dict, det: dict | None) -> dict:
    syn = (det or {}).get("synopsis") or {}
    return {"program": pid, "source": "grants.gov", "opp_id": str(hit["id"]), "number": hit["number"],
            "title": html.unescape(hit["title"]), "agency": hit["agencyCode"], "status": hit["oppStatus"],
            "open_date": _date(hit.get("openDate")), "close_date": _date(hit.get("closeDate")),
            "award_ceiling": _money(syn.get("awardCeiling")), "award_floor": _money(syn.get("awardFloor")),
            "est_funding": _money(syn.get("estimatedFunding")), "topics": "", "url": VIEW.format(id=hit["id"])}


def tracked_queries() -> list[dict]:
    """One first-page search per distinct number or `search` keyword (pattern rules name their own keywords)."""
    words = []
    for rules in signals()["grants_gov"].values():
        words += rules.get("numbers", []) + rules.get("search", [])
    return [{"keyword": w, "oppStatuses": "forecasted|posted|closed", "pages": 1} for w in dict.fromkeys(words)]


def cap_changes(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        ceiling = int(r["award_ceiling"] or 0)
        cap = programs()[r["program"]]["award"].get("max")
        if ceiling and cap and ceiling > cap and r["status"] in ("posted", "forecasted"):
            out.append({"qid": qid("cap-change", "grants.gov", f"{r['program']}|{r['opp_id']}|{ceiling}"),
                        "signal": "grants.gov", "program": r["program"], "kind": "cap-change",
                        "title": f"{r['number']}: ceiling ${ceiling:,} vs map ${cap:,}", "url": r["url"],
                        "detail": {"ceiling": ceiling, "map_max": cap, "number": r["number"]}})
    return out


def candidate(title: str, terms: list[str], exclude: list[str]) -> bool:
    low = title.lower()
    return any(t in low for t in terms) and not any(x in low for x in exclude)


def discover(s, tracked_ids: set[str]) -> list[dict]:
    cfg = signals()["discovery"]
    terms = [t.lower() for t in cfg["title_terms"]]
    exclude = [t.lower() for t in cfg.get("exclude_terms", [])]
    ignore = set(cfg.get("ignore") or {})
    found = {}
    for kw in cfg["keywords"]:
        for h in search(s, keyword=kw):
            title = html.unescape(h["title"])
            if str(h["id"]) in tracked_ids or h["number"] in ignore or not candidate(title, terms, exclude):
                continue
            found[str(h["id"])] = {
                "qid": qid("new-program", "grants.gov", h["number"]), "signal": "grants.gov", "program": "",
                "kind": "new-program", "title": f"{h['number']} ({h['agencyCode']}): {title}",
                "url": VIEW.format(id=h["id"]),
                "detail": {"status": h["oppStatus"], "open": _date(h.get("openDate")),
                           "close": _date(h.get("closeDate")), "keyword": kw}}
    return list(found.values())


def run(dry_run: bool = False, today: date | None = None) -> dict:
    s = session()
    hits = {}
    for q in tracked_queries():
        for h in search(s, **q):
            hits[str(h["id"])] = h
    rows, details = [], {}
    for h in hits.values():
        pids = tracked_programs(h)
        if not pids:
            continue
        details[str(h["id"])] = detail(s, h["id"])
        rows += [row(pid, h, details[str(h["id"])]) for pid in pids]
    candidates = discover(s, {str(h["id"]) for h in hits.values() if tracked_programs(h)})
    write_snapshot("grants_gov", {"tracked": list(hits.values()), "details": details, "candidates": candidates}, today)
    queued = cap_changes(rows) + candidates
    if not dry_run:
        write_opps(merge_opps(read_opps(), rows, "grants.gov", today))
        queued = enqueue(queued, today)
    return {"matched": len(rows), "queued": len(queued)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    print(run(ap.parse_args().dry_run))
