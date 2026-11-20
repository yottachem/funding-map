"""Derive each fed program's status from reference/opportunities.csv and queue differences from programs.yaml.

  open            a posted opportunity whose close date is today or later (or has none)
  upcoming        no open one, but a forecasted opportunity not yet past its close date
  between-rounds  opportunities on record, all closed
  (none)          no opportunities on record: the program has no feed, or its feed has not matched yet

Writes data/program_status.csv. Queues a status-change when the derived status differs from programs.yaml, and a
possible-lapse when a fed program's newest opportunity was last seen more than LAPSE_DAYS ago. programs.yaml only
changes when a queue item is accepted (tools/review.py).
"""
from __future__ import annotations

import csv
from datetime import date, timedelta

from ingest.common import ROOT, enqueue, programs, qid, read_opps, signals

OUT = ROOT / "data" / "program_status.csv"
COLUMNS = ["program", "yaml_status", "derived", "open", "forecasted", "next_close", "last_seen"]
LAPSE_DAYS = 365


def fed_programs() -> set[str]:
    sig = signals()
    return set(sig["grants_gov"]) | set(sig["dsip"])


def derive(opps: list[dict], today: date) -> dict[str, dict]:
    t = today.isoformat()
    live = lambda r: not r["close_date"] or r["close_date"] >= t  # noqa: E731
    out = {}
    for pid in sorted(fed_programs()):
        rows = [r for r in opps if r["program"] == pid]
        posted = [r for r in rows if r["status"] == "posted" and live(r)]
        forecast = [r for r in rows if r["status"] == "forecasted" and live(r)]
        derived = "open" if posted else "upcoming" if forecast else "between-rounds" if rows else ""
        closes = sorted(r["close_date"] for r in posted + forecast if r["close_date"])
        out[pid] = {"program": pid, "yaml_status": programs()[pid]["status"], "derived": derived,
                    "open": len(posted), "forecasted": len(forecast), "next_close": closes[0] if closes else "",
                    "last_seen": max((r["last_seen"] for r in rows), default="")}
    return out


def queue_items(status: dict[str, dict], today: date) -> list[dict]:
    items = []
    cutoff = (today - timedelta(days=LAPSE_DAYS)).isoformat()
    for pid, s in status.items():
        if s["derived"] and s["derived"] != s["yaml_status"]:
            items.append({"qid": qid("status-change", "derived", f"{pid}|{s['yaml_status']}|{s['derived']}"),
                          "signal": "derived", "program": pid, "kind": "status-change",
                          "title": f"{pid}: {s['yaml_status']} -> {s['derived']}", "url": "",
                          "detail": {"from": s["yaml_status"], "to": s["derived"], "open": s["open"],
                                     "forecasted": s["forecasted"], "next_close": s["next_close"]}})
        if s["last_seen"] and s["last_seen"] < cutoff:
            items.append({"qid": qid("possible-lapse", "derived", f"{pid}|{s['last_seen']}"), "signal": "derived",
                          "program": pid, "kind": "possible-lapse",
                          "title": f"{pid}: no opportunity seen since {s['last_seen']}", "url": "",
                          "detail": {"last_seen": s["last_seen"]}})
    return items


def run(dry_run: bool = False, today: date | None = None) -> dict:
    today = today or date.today()
    status = derive(read_opps(), today)
    items = queue_items(status, today)
    if not dry_run:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("w", newline="") as f:
            w = csv.DictWriter(f, COLUMNS)
            w.writeheader()
            w.writerows(status.values())
        items = enqueue(items, today)
    return {"programs": len(status), "queued": len(items)}


if __name__ == "__main__":
    print(run())
