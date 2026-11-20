"""Load and check reference/programs.yaml against its rules.

`problems()` returns every rule violation as a string so one test shows them all. `launch_problems()` adds the
launch gate: no open `verify` fields, every program has a sourced award size (cap, or a typical award computed from
sbir_stats.csv or recent.csv) and a
sourced success rate or an explicit "not published", and deadlines carry a source.
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "reference"
STATS = REFERENCE / "awards" / "sbir_stats.csv"
RECENT = REFERENCE / "awards" / "recent.csv"

JURISDICTIONS = ("federal", "massachusetts")
VEHICLES = ("grant", "contract", "cooperative-agreement", "other-transaction", "grant-or-contract", "milestone-award",
            "via-intermediary")
STAGES = ("entry", "follow-on", "scale", "training", "cost-share")
ENTITIES = ("small-business", "academic", "either")
DOMAINS = ("life-science-tools", "diagnostics", "materials", "energy-climate", "hardware")
STATUSES = ("open", "between-rounds", "upcoming", "paused", "closed", "unknown")
REQUIRED = ("id", "name", "funder", "jurisdiction", "vehicle", "stage", "entity", "domains", "award", "success",
            "deadlines", "status", "sources")
KEYS = set(REQUIRED) | {"office", "award_data", "award_recent", "timing", "prerequisites", "cost_share", "trl", "verify", "feeds",
                        "requires", "lead"}
GATED_STAGES = ("follow-on", "cost-share")


def data() -> dict:
    return yaml.safe_load((REFERENCE / "programs.yaml").read_text())


def programs() -> list[dict]:
    return data()["programs"]


def sources() -> dict:
    return data()["sources"]


def sbir_stats() -> dict[tuple[str, str, str], dict]:
    if not STATS.exists():
        return {}
    with STATS.open() as f:
        return {(r["agency"], r["branch"], r["phase"]): r for r in csv.DictReader(f)}


def recent_stats() -> dict[tuple[str, str], list[dict]]:
    """reference/awards/recent.csv rows grouped by (dataset, group), one row per fiscal year."""
    if not RECENT.exists():
        return {}
    out: dict[tuple[str, str], list[dict]] = {}
    with RECENT.open() as f:
        for r in csv.DictReader(f):
            out.setdefault((r["dataset"], r["group"]), []).append(r)
    return out


def award_row(p: dict, stats: dict | None = None) -> dict | None:
    key = p.get("award_data")
    if not key:
        return None
    stats = sbir_stats() if stats is None else stats
    return stats.get((key["agency"], key.get("branch", ""), key["phase"]))


def _get(entry: dict, path: str):
    node = entry
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def problems(progs: list[dict] | None = None, srcs: dict | None = None, stats: dict | None = None,
             recent: dict | None = None) -> list[str]:
    progs = programs() if progs is None else progs
    srcs = sources() if srcs is None else srcs
    stats = sbir_stats() if stats is None else stats
    recent = recent_stats() if recent is None else recent
    out: list[str] = []
    ids = [p.get("id") for p in progs]
    for dup in {i for i in ids if ids.count(i) > 1}:
        out.append(f"duplicate id {dup}")
    for key, s in srcs.items():
        if not str(s.get("url", "")).startswith("https://"):
            out.append(f"source {key}: needs an https url")
        if s.get("tier") not in (1, 2):
            out.append(f"source {key}: tier must be 1 or 2")
    for p in progs:
        pid = p.get("id", "?")
        for k in REQUIRED:
            if k not in p:
                out.append(f"{pid}: missing {k}")
        for k in set(p) - KEYS:
            out.append(f"{pid}: unknown key {k}")
        for field, allowed in (("jurisdiction", JURISDICTIONS), ("vehicle", VEHICLES), ("stage", STAGES),
                               ("entity", ENTITIES), ("status", STATUSES)):
            if field in p and p[field] not in allowed:
                out.append(f"{pid}: {field} {p[field]!r} not in {allowed}")
        for d in p.get("domains", []):
            if d not in DOMAINS:
                out.append(f"{pid}: domain {d!r} not in {DOMAINS}")
        refs = list(p.get("sources", []))
        for path in ("award.source", "success.source", "success.also", "timing.source", "deadlines.source"):
            v = _get(p, path)
            if v is not None:
                refs.append(v)
        for r in refs:
            if r not in srcs:
                out.append(f"{pid}: source key {r!r} not in sources")
        award = p.get("award", {})
        if award.get("max") is not None and not award.get("source"):
            out.append(f"{pid}: award.max needs a source")
        if award.get("max") is None and "award.max" not in p.get("verify", []) and not award.get("note"):
            out.append(f"{pid}: no award.max; add a note or a verify flag")
        if award.get("not_stated"):
            if award.get("max") is not None:
                out.append(f"{pid}: award.not_stated with a max")
            if srcs.get(award.get("source"), {}).get("tier") != 1:
                out.append(f"{pid}: award.not_stated needs the funder's own document (tier-1 source)")
        succ = p.get("success", {})
        if "rate" in succ:
            if not 0 < succ["rate"] < 1:
                out.append(f"{pid}: success.rate must be a fraction")
            if not (succ.get("year") and succ.get("basis") and succ.get("source")):
                out.append(f"{pid}: success.rate needs year, basis and source")
        elif succ.get("published") is not False:
            out.append(f"{pid}: success needs a sourced rate or published: false")
        if p.get("award_data") and award_row(p, stats) is None and stats:
            out.append(f"{pid}: award_data {p['award_data']} not in sbir_stats.csv")
        rec = p.get("award_recent")
        if rec and recent and (rec.get("dataset"), rec.get("group")) not in recent:
            out.append(f"{pid}: award_recent {rec} not in recent.csv")
        for nxt in _get(p, "deadlines.next") or []:
            if not isinstance(nxt, dt.date):
                out.append(f"{pid}: deadlines.next {nxt!r} is not a date")
        trl = p.get("trl")
        if trl is not None and not (len(trl) == 2 and 1 <= trl[0] <= trl[1] <= 9):
            out.append(f"{pid}: trl must be [low, high] within 1-9")
        req = p.get("requires")
        if p.get("stage") in GATED_STAGES and not req:
            out.append(f"{pid}: stage {p['stage']} needs requires")
        for r in (req or {}).get("any", []):
            if r not in ids or r == pid:
                out.append(f"{pid}: requires unknown program {r}")
        lead = p.get("lead")
        if lead is not None:
            d = lead.get("days")
            if d is not None and not (isinstance(d, list) and len(d) == 2 and all(isinstance(x, int) and x >= 0 for x in d)
                                      and d[0] <= d[1]):
                out.append(f"{pid}: lead.days must be [low, high] whole days or null")
            if not (lead.get("basis") and lead.get("source")):
                out.append(f"{pid}: lead needs basis and source")
            elif lead["source"] not in srcs:
                out.append(f"{pid}: source key {lead['source']!r} not in sources")
        for f in p.get("feeds", []):
            if f not in ids:
                out.append(f"{pid}: feeds unknown program {f}")
            if f == pid:
                out.append(f"{pid}: feeds itself")
    return out


def launch_problems(progs: list[dict] | None = None, srcs: dict | None = None) -> list[str]:
    progs = programs() if progs is None else progs
    srcs = sources() if srcs is None else srcs
    out = problems(progs, srcs)
    for p in progs:
        pid = p["id"]
        if p.get("verify"):
            out.append(f"{pid}: open verify flags {p['verify']}")
        if p["award"].get("max") is None and not (p.get("award_data") or p.get("award_recent")
                                                   or p["award"].get("not_stated")):
            out.append(f"{pid}: no sourced award size (cap or award data)")
        if not _get(p, "deadlines.source"):
            out.append(f"{pid}: deadlines need a source")
        rate_src = _get(p, "success.source")
        if "rate" in p["success"] and srcs.get(rate_src, {}).get("tier") != 1:
            out.append(f"{pid}: success rate must come from a tier-1 source")
    return out
