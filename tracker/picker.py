"""Funding roadmap picker: a company profile in; ranked options, stacking chains and an 18-month calendar out.

Every number comes from the registry or the award files; nothing is estimated.

- Eligibility: state (Massachusetts programs), entity type, domain overlap, the funder's TRL band when it states one,
  and status (closed and paused programs are out). A program with `requires` needs one of those awards already held,
  or an earlier step in the same chain.
- Size: typical award from actual awards (recent.csv, the fiscal year with the most awards; then sbir_stats.csv),
  else the cap. Each size carries its basis.
- Odds: the published success rate only. No published rate, no expected value.
- Dates: registry `deadlines.next` and DSIP topic close dates inside the window. An open program with a rolling or
  anytime cadence can start at the earliest date; DOE-style go/no-go steps follow the earlier award's term.
  Anything else is "date not announced", never guessed.
- Cash: application date + days to award (registry timing, else SBIR.gov p25-p75 days to award). Timing that only
  covers notification is labeled as such.

A planning aid, not an eligibility determination: each step carries the funder's prerequisites text.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import json
import re
from dataclasses import asdict, dataclass, field

import yaml

from tracker import registry

STATE_OF = {"massachusetts": "MA"}
WINDOW_MONTHS = 18
MAX_DEPTH = 3
ROLLING = re.compile(r"\brolling\b|\banytime\b", re.I)
GO_NO_GO = re.compile(r"go/no-go", re.I)
PROFILES = registry.REFERENCE / "example_profiles.yaml"
OPPS = registry.REFERENCE / "opportunities.csv"
ENTITY_REASON = {"small-business": "needs a small business", "academic": "university-led"}


@dataclass
class Profile:
    id: str
    label: str
    entity: str                      # small-business | academic
    domains: list[str]
    state: str = ""                  # two-letter code
    trl: int | None = None
    held: list[str] = field(default_factory=list)   # program ids already won
    cash_need: int | None = None     # USD wanted from non-dilutive sources within the window
    runway_months: int | None = None
    prep_days: int = 30              # earliest application date = start + prep_days
    fictional: bool = False


@dataclass
class Step:
    program: str
    name: str
    apply: dt.date | None
    apply_basis: str                 # deadline | rolling | go/no-go | not announced | after window | ...
    later_dates: list[dt.date]
    cash: tuple[dt.date, dt.date] | None
    cash_basis: str
    size: int | None
    size_basis: str
    odds: float | None
    odds_basis: str
    chain_odds: float | None
    ev: int | None
    flags: list[str]
    prerequisites: str
    next: list["Step"] = field(default_factory=list)


@dataclass
class Roadmap:
    profile: Profile
    start: dt.date
    end: dt.date
    options: list[Step]
    excluded: list[tuple[str, str]]
    summary: dict


# ---------------------------------------------------------------- data

def add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def read_opps() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if OPPS.exists():
        with OPPS.open() as f:
            for r in csv.DictReader(f):
                out.setdefault(r["program"], []).append(r)
    return out


def load_profiles(path=PROFILES) -> list[Profile]:
    return [Profile(**p) for p in yaml.safe_load(path.read_text())["profiles"]]


def typical_size(p: dict, stats: dict, recent: dict) -> tuple[int | None, str]:
    rec = p.get("award_recent")
    rows = recent.get((rec["dataset"], rec["group"])) if rec else None
    if rows:
        r = max(rows, key=lambda r: (int(r["awards"]), r["fiscal_year"]))
        return round(float(r["amount_median"])), f"median of {r['awards']} FY{r['fiscal_year']} awards"
    row = registry.award_row(p, stats)
    if row:
        return round(float(row["amount_median"])), f"median of {row['awards']} awards, FY2022-24 (SBIR.gov)"
    if p["award"].get("max") is not None:
        return p["award"]["max"], "cap"
    return None, "not stated by the funder" if p["award"].get("not_stated") else "no size"


def cash_days(p: dict, stats: dict) -> tuple[tuple[int, int] | None, str]:
    t = p.get("timing") or {}
    if t.get("award_days"):
        return tuple(t["award_days"]), "award"
    row = registry.award_row(p, stats)
    if row and row.get("days_p25") and row.get("days_p75"):
        return (round(float(row["days_p25"])), round(float(row["days_p75"]))), "award (SBIR.gov p25-p75)"
    if t.get("notify_days"):
        return tuple(t["notify_days"]), "notice only; cash date not published"
    return None, "time to award not published"


def deadlines(p: dict, opps: dict, lo: dt.date, hi: dt.date) -> list[dt.date]:
    """Registry dates plus DSIP topic close dates. Grants.gov close dates are NOFO expiry dates, not deadlines."""
    found = {d for d in (p["deadlines"].get("next") or []) if lo <= d <= hi}
    for o in opps.get(p["id"], []):
        if o["source"] == "dsip" and o["status"] in ("posted", "forecasted") and o["close_date"]:
            d = dt.date.fromisoformat(o["close_date"])
            if lo <= d <= hi:
                found.add(d)
    return sorted(found)


# ---------------------------------------------------------------- rules

def ineligible(p: dict, prof: Profile) -> list[str]:
    out = []
    state = STATE_OF.get(p["jurisdiction"])
    if state and prof.state != state:
        out.append(f"{state} companies only")
    if p["entity"] != "either" and p["entity"] != prof.entity:
        out.append(ENTITY_REASON[p["entity"]])
    if not set(p["domains"]) & set(prof.domains):
        out.append("outside your domains")
    if prof.trl and p.get("trl") and not p["trl"][0] <= prof.trl <= p["trl"][1]:
        out.append(f"TRL {p['trl'][0]}-{p['trl'][1]} only")
    if p["status"] in ("closed", "paused"):
        out.append(f"{p['status']} (as of {registry.data().get('verified_default')})")
    return out


class Picker:
    def __init__(self, prof: Profile, start: dt.date, progs=None, stats=None, recent=None, opps=None):
        self.prof, self.start = prof, start
        self.end = add_months(start, WINDOW_MONTHS)
        self.progs = {p["id"]: p for p in (registry.programs() if progs is None else progs)}
        self.stats = registry.sbir_stats() if stats is None else stats
        self.recent = registry.recent_stats() if recent is None else recent
        self.opps = read_opps() if opps is None else opps
        self.reasons = {pid: ineligible(p, prof) for pid, p in self.progs.items()}

    def eligible(self, pid: str) -> bool:
        return not self.reasons[pid]

    def successors(self, pid: str) -> list[str]:
        return [q for q, p in self.progs.items() if pid in (p.get("requires") or {}).get("any", []) and self.eligible(q)]

    def step(self, pid: str, prev: Step | None, chain_odds: float | None) -> Step:
        p = self.progs[pid]
        cad = str(p["deadlines"].get("cadence") or "")
        req = p.get("requires") or {}
        flags: list[str] = []
        earliest: dt.date | None = self.start + dt.timedelta(days=self.prof.prep_days)
        apply, basis = None, ""
        if prev is not None:
            if prev.apply is None:
                earliest, basis = None, f"after {prev.name}, which has no date in the window"
            elif prev.cash is None:
                earliest, basis = None, f"after the {prev.name} award; its time to award is not published"
            else:
                earliest = prev.cash[1]
                if req.get("after_months"):
                    earliest = add_months(earliest, req["after_months"])
        if earliest and earliest > self.end:
            earliest, basis = None, "after the 18-month window"
        dates = deadlines(p, self.opps, earliest, self.end) if earliest else []
        too_soon = (deadlines(p, self.opps, self.start, earliest - dt.timedelta(days=1))
                    if earliest and not dates and prev is None else [])
        if dates:
            apply, basis = dates[0], "deadline"
        elif earliest and prev is not None and GO_NO_GO.search(cad):
            months = (self.progs[prev.program]["award"].get("duration_months") or [None, None])[1]
            if months is None:
                basis = f"go/no-go at the end of {prev.name}; term not published"
            else:
                apply, basis = add_months(prev.cash[1], months), "go/no-go (no new application)"
        elif earliest and p["status"] == "open" and ROLLING.search(cad):
            apply, basis = earliest, "rolling"
        elif too_soon:
            basis = (f"{too_soon[-1]:%b %d} is inside the {self.prof.prep_days}-day prep time; next date not announced"
                     + (f" ({cad})" if cad else ""))
        elif earliest:
            basis = (f"no date announced after {earliest:%b %d, %Y}" if prev is not None else "date not announced") + (
                f" ({cad})" if cad else "")
        if apply and apply > self.end:
            apply, basis = None, "after the 18-month window"
        days, cash_basis = cash_days(p, self.stats)
        cash = (apply + dt.timedelta(days=days[0]), apply + dt.timedelta(days=days[1])) if apply and days else None
        if cash and self.prof.runway_months:
            runway_end = add_months(self.start, self.prof.runway_months)
            if cash[0] > runway_end:
                flags.append("cash lands after runway")
            elif cash[1] > runway_end:
                flags.append("cash may land after runway")
        if cash and cash[1] > self.end:
            flags.append("cash may land after the window")
        if p.get("cost_share"):
            flags.append(f"cost share: {p['cost_share']}")
        size, size_basis = typical_size(p, self.stats, self.recent)
        rate = p["success"].get("rate")
        odds_basis = f"{rate:.0%} ({p['success']['year']})" if rate is not None else "not published"
        chained = chain_odds * rate if chain_odds is not None and rate is not None else None
        ev = round(size * chained) if size is not None and chained is not None else None
        later = [d for d in dates[1:]]
        return Step(pid, p["name"], apply, basis, later, cash, cash_basis, size, size_basis, rate, odds_basis,
                    chained, ev, flags, str(p.get("prerequisites") or ""))

    def grow(self, s: Step, path: tuple[str, ...]) -> Step:
        if len(path) < MAX_DEPTH:
            for q in self.successors(s.program):
                if q not in path and q not in self.prof.held:
                    s.next.append(self.grow(self.step(q, s, s.chain_odds), path + (q,)))
        return s

    def run(self) -> Roadmap:
        held = set(self.prof.held)
        options, gated = [], []
        for pid, p in self.progs.items():
            if pid in held or not self.eligible(pid):
                continue
            req = (p.get("requires") or {}).get("any", [])
            if req and not held & set(req):
                gated.append(pid)
                continue
            options.append(self.grow(self.step(pid, None, 1.0), (pid,)))
        options.sort(key=lambda s: (s.apply is None, s.ev is None, -(s.ev or 0), -(s.size or 0)))
        reached = {n.program for o in options for n in walk(o)}
        excluded = [(pid, "; ".join(r)) for pid, r in self.reasons.items() if r]
        for pid in gated:
            if pid not in reached:
                names = ", ".join(self.progs[r]["name"] for r in self.progs[pid]["requires"]["any"])
                excluded.append((pid, f"needs one of: {names}"))
        excluded += [(pid, "already held") for pid in held if pid in self.progs]
        return Roadmap(self.prof, self.start, self.end, options, sorted(excluded), self.summarize(options))

    def summarize(self, options: list[Step]) -> dict:
        firsts = [o for o in options if o.apply and o.cash and o.cash[1] <= self.end]
        ev = sum(o.ev for o in firsts if o.ev is not None)
        return {"applications_dated": sum(1 for o in options if o.apply),
                "applications_undated": sum(1 for o in options if not o.apply),
                "expected_first_awards": ev,
                "expected_basis": "sum of size x published odds over first applications whose cash lands inside the window",
                "without_odds": [o.program for o in firsts if o.ev is None],
                "cash_need": self.prof.cash_need,
                "coverage": round(ev / self.prof.cash_need, 2) if self.prof.cash_need else None}


def walk(s: Step):
    yield s
    for n in s.next:
        yield from walk(n)


def pick(prof: Profile, start: dt.date | None = None, **data) -> Roadmap:
    return Picker(prof, start or dt.date.today(), **data).run()


def calendar_months(rm: Roadmap) -> list[tuple[str, list[str]]]:
    events: dict[str, set[str]] = {}
    for o in rm.options:
        for s in walk(o):
            if s.apply:
                events.setdefault(s.apply.strftime("%Y-%m"), set()).add(f"apply {s.program} ({s.apply:%b %d})")
            if s.cash:
                events.setdefault(s.cash[0].strftime("%Y-%m"), set()).add(f"cash from {s.program} begins")
    months, d = [], dt.date(rm.start.year, rm.start.month, 1)
    while d <= rm.end:
        key = d.strftime("%Y-%m")
        months.append((key, sorted(events.get(key, ()))))
        d = add_months(d, 1)
    return months


# ---------------------------------------------------------------- output

def money(v: int | None) -> str:
    return "-" if v is None else f"${v / 1e6:.2f}M" if v >= 999_500 else f"${v / 1e3:.0f}K"


def when(s: Step) -> str:
    if not s.apply:
        return s.apply_basis
    tail = f" (also {', '.join(f'{d:%b %d}' for d in s.later_dates[:2])})" if s.later_dates else ""
    return f"{s.apply:%Y-%m-%d} {s.apply_basis}{tail}"


def cash_text(s: Step) -> str:
    return f"{s.cash[0]:%b %Y}-{s.cash[1]:%b %Y}" if s.cash else s.cash_basis


def markdown(rm: Roadmap) -> str:
    p, sm = rm.profile, rm.summary
    out = [f"## {p.label}" + (" (fictional profile)" if p.fictional else ""), "",
           f"{p.entity}, {p.state or 'no state'}, TRL {p.trl or '-'}, domains {', '.join(p.domains)}; "
           f"held: {', '.join(p.held) or 'none'}; runway {p.runway_months or '-'} months; need {money(p.cash_need)}. "
           f"Window {rm.start} to {rm.end}.", "",
           f"Expected from first applications: **{money(sm['expected_first_awards'])}**"
           + (f" ({sm['coverage']:.0%} of the need)" if sm["coverage"] is not None else "")
           + f"; {sm['applications_dated']} dated, {sm['applications_undated']} without a date."
           + (f" No published odds for: {', '.join(sm['without_odds'])}." if sm["without_odds"] else ""), "",
           "| # | Program | Apply | Cash | Typical size | Odds | Expected | Flags |", "|---|---|---|---|---|---|---|---|"]
    for i, o in enumerate(rm.options, 1):
        out.append(f"| {i} | {o.name} | {when(o)} | {cash_text(o)} | {money(o.size)} ({o.size_basis}) | {o.odds_basis} "
                   f"| {money(o.ev)} | {'; '.join(o.flags)} |")
    chains = [o for o in rm.options if o.next]
    if chains:
        out += ["", "**Stacking**", ""]
        for o in chains:
            out.append(f"- {o.name}")
            for s in o.next:
                odds = f"chain odds {s.chain_odds:.1%}" if s.chain_odds is not None else "chain odds not published"
                out.append(f"  - then {s.name}: {when(s)}; cash {cash_text(s)}; {money(s.size)}; {odds}; "
                           f"expected {money(s.ev)}" + (f"; {'; '.join(s.flags)}" if s.flags else ""))
                later = sorted({n.name for n, _ in tree(s)})
                if later:
                    out.append(f"    - later: {', '.join(later)}")
    dated = [o for o in rm.options if o.apply and o.prerequisites]
    if dated:
        out += ["", "**Before you apply** (the funder's conditions; the picker does not check these)", ""]
        out += [f"- {o.name}: {o.prerequisites}" for o in dated]
    out += ["", "**Calendar**", "", "| Month | Events |", "|---|---|"]
    out += [f"| {m} | {'; '.join(e) or ''} |" for m, e in calendar_months(rm)]
    out += ["", "**Not a fit**", "", "| Program | Why |", "|---|---|"]
    out += [f"| {pid} | {why} |" for pid, why in rm.excluded]
    return "\n".join(out) + "\n"


def tree(s: Step, depth: int = 1):
    for n in s.next:
        yield n, depth
        yield from tree(n, depth + 1)


def to_json(rm: Roadmap) -> str:
    return json.dumps(asdict(rm), default=str, indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", help="profile id from reference/example_profiles.yaml (default: all)")
    ap.add_argument("--start", type=dt.date.fromisoformat, help="window start (default: today)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    for prof in load_profiles():
        if a.profile in (None, prof.id):
            rm = pick(prof, a.start)
            print(to_json(rm) if a.json else markdown(rm))
