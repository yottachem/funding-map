"""DoD SBIR/STTR open and pre-release topics from the DSIP public topics API (no key needed).

Weekly. Topics are aggregated to one opportunities.csv row per solicitation x component x program (SBIR/STTR) x
mapped program, with the topic count, earliest open date and latest close date. Each topic's phaseHierarchy lists the
phases it funds; signals.yaml `dsip` routes those phase codes to dod-sbir-1 / dod-sbir-2 (a topic can feed both).
DSIP is the DoD's own system (tier 1), so rows are auto-accepted. Pre-Release topics are written as `forecasted`.

Run: uv run python -m ingest.dsip [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ingest.common import merge_opps, read_opps, session, signals, write_opps, write_snapshot

SEARCH = "https://www.dodsbirsttr.mil/topics/api/public/topics/search"
APP = "https://www.dodsbirsttr.mil/topics-app/"
QUERY = {"searchText": None, "components": None, "programYear": None, "solicitationCycleNames": ["openTopics"],
         "releaseNumbers": [], "topicReleaseStatus": [591, 592], "modernizationPriorities": None,
         "sortBy": "finalTopicCode,asc"}
STATUS = {"Open": "posted", "Pre-Release": "forecasted"}
ET = ZoneInfo("America/New_York")
SIZE = 100


def fetch(s) -> list[dict]:
    s.headers.update({"Accept": "application/json", "Referer": APP})
    base = f"{SEARCH}?searchParam={urllib.parse.quote(json.dumps(QUERY))}"
    topics, page = [], 0
    while True:
        r = s.get(f"{base}&size={SIZE}&page={page}", timeout=60)
        r.raise_for_status()
        d = r.json()
        topics += d["data"]
        page += 1
        if page * SIZE >= d["total"] or not d["data"]:
            return topics


def _day(ms) -> str:
    return datetime.fromtimestamp(ms / 1000, ET).date().isoformat() if ms else ""


def phases(topic: dict) -> set[str]:
    try:
        return {c["phase"] for c in json.loads(topic.get("phaseHierarchy") or "{}").get("config", [])}
    except (TypeError, ValueError):
        return set()


def route(topic: dict) -> list[str]:
    have = phases(topic)
    return [pid for pid, rule in signals()["dsip"].items() if have & set(rule["phases"])]


def aggregate(topics: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for t in topics:
        for pid in route(t):
            groups.setdefault((pid, t["solicitationNumber"], t["component"], t["program"]), []).append(t)
    rows = []
    for (pid, sol, comp, prog), ts in groups.items():
        opens = [_day(t.get("topicStartDate")) for t in ts if t.get("topicStartDate")]
        closes = [_day(t.get("topicEndDate")) for t in ts if t.get("topicEndDate")]
        status = "posted" if any(t["topicStatus"] == "Open" for t in ts) else "forecasted"
        rows.append({"program": pid, "source": "dsip", "opp_id": f"{sol}|{comp}|{prog}", "number": sol,
                     "title": f"{ts[0]['solicitationTitle']} ({comp} {prog})", "agency": f"DOD-{comp}",
                     "status": status, "open_date": min(opens, default=""), "close_date": max(closes, default=""),
                     "award_ceiling": "", "award_floor": "", "est_funding": "",
                     "topics": str(len(ts)), "url": APP})
    return rows


def run(dry_run: bool = False, today: date | None = None) -> dict:
    topics = fetch(session())
    write_snapshot("dsip", topics, today)
    rows = aggregate(topics)
    if not dry_run:
        write_opps(merge_opps(read_opps(), rows, "dsip", today))
    return {"topics": len(topics), "rows": len(rows)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    print(run(ap.parse_args().dry_run))
