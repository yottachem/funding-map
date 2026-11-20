"""Shared helpers: HTTP session, signal config, raw snapshots, the opportunities file and the review queue.

Pattern from ai-materials-tracker ingest/common.py, cut down: the funding map has one registry (programs) and one
event stream (opportunities), and nothing it collects changes reference/programs.yaml without review.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date
from functools import cache
from pathlib import Path

import requests
import yaml

from tracker import registry

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "reference"
RAW = ROOT / "data" / "raw"
SIGNALS = REF / "signals.yaml"
OPPS = REF / "opportunities.csv"
OPP_COLUMNS = ["program", "source", "opp_id", "number", "title", "agency", "status", "open_date", "close_date",
               "award_ceiling", "award_floor", "est_funding", "topics", "url", "first_seen", "last_seen"]
QUEUE = ROOT / "data" / "review" / "queue.csv"
QUEUE_COLUMNS = ["qid", "found", "signal", "program", "kind", "title", "url", "detail", "status", "decided", "note"]
KINDS = ("new-program", "cap-change", "status-change", "possible-lapse")
UA = "funding-map/0.1 (open-data research tool)"


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


@cache
def signals() -> dict:
    return yaml.safe_load(SIGNALS.read_text())


@cache
def programs() -> dict[str, dict]:
    return {p["id"]: p for p in registry.programs()}


def write_snapshot(source: str, payload, day: date | None = None) -> Path:
    """Raw API responses, one file per source per day (data/raw is not committed)."""
    day = day or date.today()
    path = RAW / source / f"{day.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, default=str))
    return path


# ---------------------------------------------------------------- opportunities

def read_opps() -> list[dict]:
    if not OPPS.exists():
        return []
    with OPPS.open(newline="") as f:
        return list(csv.DictReader(f))


def write_opps(rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: (r["program"], r["source"], r["close_date"] or "9999", r["opp_id"]))
    with OPPS.open("w", newline="") as f:
        w = csv.DictWriter(f, OPP_COLUMNS)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in OPP_COLUMNS} for r in rows)


def merge_opps(existing: list[dict], fresh: list[dict], source: str, today: date | None = None) -> list[dict]:
    """Upsert this source's rows by (program, opp_id). Rows the source no longer returns are kept and marked closed
    once their close date has passed, so history survives (lapse detection reads last_seen)."""
    today_s = (today or date.today()).isoformat()
    key = lambda r: (r["program"], r["source"], r["opp_id"])  # noqa: E731
    old = {key(r): r for r in existing}
    seen = set()
    for r in fresh:
        k = key(r)
        seen.add(k)
        prev = old.get(k)
        r["first_seen"] = prev["first_seen"] if prev else today_s
        r["last_seen"] = today_s
        old[k] = r
    for k, r in old.items():
        if k[1] == source and k not in seen and r["status"] not in ("closed", "archived"):
            if r["close_date"] and r["close_date"] < today_s:
                r["status"] = "closed"
    return list(old.values())


# ---------------------------------------------------------------- review queue

def read_queue() -> list[dict]:
    if not QUEUE.exists():
        return []
    with QUEUE.open(newline="") as f:
        return list(csv.DictReader(f))


def write_queue(rows: list[dict]) -> None:
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE.open("w", newline="") as f:
        w = csv.DictWriter(f, QUEUE_COLUMNS)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in QUEUE_COLUMNS} for r in rows)


def qid(kind: str, signal: str, ident: str) -> str:
    return "Q" + hashlib.sha1(f"{kind}|{signal}|{ident}".encode()).hexdigest()[:8]


def enqueue(items: list[dict], today: date | None = None) -> list[dict]:
    """Add candidates whose qid is not already in the queue (any status: a rejected item never returns)."""
    assert all(i["kind"] in KINDS for i in items)
    queue = read_queue()
    have = {q["qid"] for q in queue}
    added = []
    for i in items:
        if i["qid"] in have:
            continue
        row = dict(i, found=(today or date.today()).isoformat(), status="open")
        row["detail"] = json.dumps(row.get("detail") or {}, sort_keys=True)
        queue.append(row)
        have.add(i["qid"])
        added.append(row)
    if added:
        write_queue(queue)
    return added
