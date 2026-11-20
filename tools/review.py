"""Review queue: list open items, accept or reject them.

  uv run python -m tools.review                     list open items
  uv run python -m tools.review all                 list every item with its decision
  uv run python -m tools.review accept Q1a2b3c4 [note...]
  uv run python -m tools.review reject Q1a2b3c4 [note...]

Accepting a status-change also edits that program's `status:` line in programs.yaml. Every other kind is a decision
record only: a new-program needs a curated record, a cap-change needs the funder's text checked, a possible-lapse
needs a look at the funder's page. A rejected item never re-enters the queue (enqueue dedupes on qid).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date

from ingest.common import read_queue, write_queue
from tracker.registry import REFERENCE

PROGRAMS = REFERENCE / "programs.yaml"


def set_status(pid: str, status: str, text: str | None = None) -> str:
    """Replace the status line inside one program block; raises if the block or line is missing."""
    text = PROGRAMS.read_text() if text is None else text
    block = re.search(rf"^  - id: {re.escape(pid)}\n(?:(?!^  - id: ).*\n?)*", text, re.M)
    if not block:
        raise KeyError(pid)
    new, n = re.subn(r"^    status: \S+", f"    status: {status}", block.group(0), count=1, flags=re.M)
    if not n:
        raise ValueError(f"{pid}: no status line")
    return text[:block.start()] + new + text[block.end():]


def decide(q: str, verdict: str, note: str = "", today: date | None = None) -> dict:
    queue = read_queue()
    item = next((r for r in queue if r["qid"] == q), None)
    if item is None:
        raise KeyError(q)
    if item["status"] != "open":
        raise ValueError(f"{q} already {item['status']}")
    if verdict == "accepted" and item["kind"] == "status-change":
        PROGRAMS.write_text(set_status(item["program"], json.loads(item["detail"])["to"]))
    item.update(status=verdict, decided=(today or date.today()).isoformat(), note=note)
    write_queue(queue)
    return item


def show(rows: list[dict]) -> None:
    for r in rows:
        d = json.loads(r["detail"] or "{}")
        extra = ", ".join(f"{k}={v}" for k, v in d.items())
        print(f"{r['qid']}  {r['kind']:<15} {r['title']}")
        if extra:
            print(f"{'':11}{extra}")
        if r["url"]:
            print(f"{'':11}{r['url']}")
        if r["status"] != "open":
            print(f"{'':11}[{r['status']} {r['decided']}] {r['note']}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "all":
        rows = read_queue() if args else [r for r in read_queue() if r["status"] == "open"]
        show(sorted(rows, key=lambda r: (r["kind"], r["program"], r["title"])))
        print(f"\n{len(rows)} item(s)")
    elif args[0] in ("accept", "reject") and len(args) >= 2:
        r = decide(args[1], args[0] + "ed", " ".join(args[2:]))
        print(f"{r['qid']} {r['status']}: {r['title']}")
    else:
        sys.exit(__doc__)
