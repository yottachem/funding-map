"""Picker rules on synthetic programs, plus smoke tests on the real registry and the fictional example profiles."""
from __future__ import annotations

from datetime import date

import pytest

from tracker import picker, registry
from tracker.picker import Picker, Profile

TODAY = date(2026, 11, 20)


def prog(pid, **kw):
    base = {"id": pid, "name": pid.upper(), "funder": "F", "jurisdiction": "federal", "vehicle": "grant",
            "stage": "entry", "entity": "small-business", "domains": ["materials"],
            "award": {"max": 100000, "source": "s"},
            "success": {"rate": 0.2, "year": "FY2022", "basis": "b", "source": "s"},
            "deadlines": {"cadence": "Annual", "next": [date(2027, 1, 5)], "source": "s"},
            "status": "open", "sources": ["s"]}
    base.update(kw)
    return base


def profile(**kw):
    base = dict(id="t", label="T", entity="small-business", domains=["materials"], state="OH")
    base.update(kw)
    return Profile(**base)


def run(progs, prof=None, stats=None, recent=None, opps=None):
    return Picker(prof or profile(), TODAY, progs=progs, stats=stats or {}, recent=recent or {}, opps=opps or {}).run()


def option(rm, pid):
    return next(o for o in rm.options if o.program == pid)


# ---------------------------------------------------------------- eligibility

@pytest.mark.parametrize("kw, reason", [
    ({"jurisdiction": "massachusetts"}, "MA companies only"),
    ({"entity": "academic"}, "university-led"),
    ({"domains": ["diagnostics"]}, "outside your domains"),
    ({"trl": [5, 8]}, "TRL 5-8 only"),
    ({"status": "closed"}, "closed")])
def test_exclusions_carry_a_reason(kw, reason):
    rm = run([prog("a", **kw)], profile(trl=3))
    assert rm.options == [] and reason in dict(rm.excluded)["a"]


def test_either_entity_and_matching_state_pass():
    rm = run([prog("a", entity="either", jurisdiction="massachusetts")], profile(state="MA", entity="academic"))
    assert [o.program for o in rm.options] == ["a"]


def test_follow_on_is_gated_until_held_or_chained():
    progs = [prog("a"), prog("b", stage="follow-on", requires={"any": ["a"]}, deadlines={"next": [date(2027, 12, 1)]})]
    rm = run(progs)
    assert [o.program for o in rm.options] == ["a"] and [n.program for n in rm.options[0].next] == ["b"]
    held = run(progs, profile(held=["a"]))
    assert [o.program for o in held.options] == ["b"] and dict(held.excluded)["a"] == "already held"


def test_unreachable_follow_on_says_what_it_needs():
    progs = [prog("a", domains=["diagnostics"]), prog("b", stage="follow-on", requires={"any": ["a"]})]
    assert dict(run(progs).excluded)["b"] == "needs one of: A"


# ---------------------------------------------------------------- size, odds, expected value

def test_expected_value_needs_published_odds():
    rm = run([prog("a"), prog("u", success={"published": False})])
    assert option(rm, "a").ev == 20000
    assert option(rm, "u").ev is None and option(rm, "u").odds_basis == "not published"
    assert rm.summary["without_odds"] == []         # u has no cash timing, so it is not a first award in the window


def test_chain_odds_multiply():
    progs = [prog("a", timing={"award_days": [100, 100]}),
             prog("b", stage="follow-on", requires={"any": ["a"]}, award={"max": 1000000, "source": "s"},
                  success={"rate": 0.5, "year": "FY2022", "basis": "b", "source": "s"},
                  deadlines={"next": [date(2027, 6, 1)]})]
    b = run(progs).options[0].next[0]
    assert b.chain_odds == pytest.approx(0.1) and b.ev == 100000


def test_size_prefers_recent_awards_then_sbir_data_then_cap():
    recent = {("ds", "g"): [{"awards": "3", "fiscal_year": "2025", "amount_median": "5"},
                            {"awards": "9", "fiscal_year": "2026", "amount_median": "7"}]}
    stats = {("NSF", "", "I"): {"awards": "10", "amount_median": "8", "days_p25": "", "days_p75": ""}}
    both = prog("a", award_recent={"dataset": "ds", "group": "g"}, award_data={"agency": "NSF", "phase": "I"})
    assert picker.typical_size(both, stats, recent) == (7, "median of 9 FY2026 awards")
    assert picker.typical_size(prog("a", award_data={"agency": "NSF", "phase": "I"}), stats, recent)[0] == 8
    assert picker.typical_size(prog("a"), stats, recent) == (100000, "cap")
    assert picker.typical_size(prog("a", award={"max": None, "not_stated": True}), {}, {})[1] == "not stated by the funder"


def test_cash_timing_prefers_award_days_and_labels_notice_only():
    stats = {("NSF", "", "I"): {"awards": "10", "amount_median": "8", "days_p25": "200", "days_p75": "300"}}
    assert picker.cash_days(prog("a", timing={"award_days": [1, 2]}, award_data={"agency": "NSF", "phase": "I"}),
                            stats)[0] == (1, 2)
    assert picker.cash_days(prog("a", award_data={"agency": "NSF", "phase": "I"}), stats)[0] == (200, 300)
    assert "notice only" in picker.cash_days(prog("a", timing={"notify_days": [1, 2]}), {})[1]


# ---------------------------------------------------------------- dates

def test_first_date_after_prep_time():
    a = run([prog("a", deadlines={"next": [date(2026, 12, 1), date(2027, 1, 5)]})]).options[0]
    assert a.apply == date(2027, 1, 5) and a.apply_basis == "deadline"


def test_date_inside_prep_time_is_reported_not_dropped():
    a = run([prog("a", deadlines={"next": [date(2026, 12, 1)]})]).options[0]
    assert a.apply is None and "inside the 30-day prep time" in a.apply_basis


def test_no_date_in_window_is_not_guessed():
    a = run([prog("a", deadlines={"cadence": "Annual", "next": [date(2028, 12, 1)]})]).options[0]
    assert a.apply is None and a.apply_basis.startswith("date not announced")


def test_rolling_only_when_open():
    rolling = {"cadence": "Rolling, subject to funds"}
    assert run([prog("a", deadlines=rolling)]).options[0].apply == date(2026, 12, 20)
    assert run([prog("a", deadlines=rolling, status="between-rounds")]).options[0].apply is None


def test_dsip_close_dates_count_and_grants_gov_close_dates_do_not():
    opps = {"a": [{"source": "dsip", "status": "posted", "close_date": "2027-02-01"},
                  {"source": "grants.gov", "status": "posted", "close_date": "2027-01-01"}]}
    a = run([prog("a", deadlines={"cadence": "Rolling topic releases"})], opps=opps).options[0]
    assert a.apply == date(2027, 2, 1)


def test_after_months_gap_from_the_earlier_award():
    progs = [prog("a", timing={"award_days": [100, 100]}),
             prog("b", stage="follow-on", requires={"any": ["a"], "after_months": 6},
                  deadlines={"next": [date(2027, 7, 1), date(2027, 11, 1)]})]
    a = run(progs).options[0]
    assert a.cash == (date(2027, 4, 15), date(2027, 4, 15)) and a.next[0].apply == date(2027, 11, 1)


def test_go_no_go_follows_the_earlier_term():
    progs = [prog("a", timing={"award_days": [100, 100]}, award={"max": 1, "source": "s", "duration_months": [6, 12]}),
             prog("b", stage="follow-on", requires={"any": ["a"]}, deadlines={"cadence": "Go/No-Go at the end of Phase I"})]
    b = run(progs).options[0].next[0]
    assert b.apply == date(2028, 4, 15) and b.apply_basis == "go/no-go (no new application)"


def test_follow_on_of_an_undated_step_says_why():
    progs = [prog("a", deadlines={"cadence": "Annual"}), prog("b", stage="follow-on", requires={"any": ["a"]})]
    assert "which has no date in the window" in run(progs).options[0].next[0].apply_basis


def test_runway_flags():
    a = run([prog("a", timing={"award_days": [100, 300]})], profile(runway_months=6)).options[0]
    assert "cash may land after runway" in a.flags
    b = run([prog("a", timing={"award_days": [300, 330]})], profile(runway_months=6)).options[0]
    assert "cash lands after runway" in b.flags


def test_dated_options_rank_before_undated():
    rm = run([prog("big", deadlines={"cadence": "Annual"}, award={"max": 10**7, "source": "s"}), prog("small")])
    assert [o.program for o in rm.options] == ["small", "big"]


# ---------------------------------------------------------------- registry and examples

def test_registry_gates_follow_ons():
    srcs = {"s": {"url": "https://example.gov", "tier": 1}}
    found = "\n".join(registry.problems([prog("b", stage="follow-on"), prog("c", requires={"any": ["zz"]})], srcs, {}))
    assert "b: stage follow-on needs requires" in found and "c: requires unknown program zz" in found


def test_example_profiles_are_fictional_and_run():
    profiles = picker.load_profiles()
    assert len(profiles) == 3
    for prof in profiles:
        assert prof.fictional and prof.label.startswith("Fictional"), prof.id
        assert "cdr" not in prof.label.lower() and "nonlinear" not in prof.label.lower()
        rm = picker.pick(prof, TODAY)
        assert rm.options and any(o.apply for o in rm.options), prof.id
        md = picker.markdown(rm)
        assert "(fictional profile)" in md and md.count("\n| 20") == 19      # 19 calendar months


def test_held_phase_i_puts_phase_ii_first():
    prof = next(p for p in picker.load_profiles() if p.id == "instrument-co")
    rm = picker.pick(prof, TODAY)
    assert rm.options[0].program == "nsf-sbir-2" and ("nsf-sbir-1", "already held") in rm.excluded
