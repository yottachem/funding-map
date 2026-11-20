"""Offline tests for the ingest layer: matching, parsing, merging, queue dedupe, status derivation, review edits."""
from __future__ import annotations

import json
from datetime import date

import pytest

from ingest import common, dsip, grants_gov, status
from tools import review
from tracker import registry

TODAY = date(2026, 11, 20)


def hit(number, title, status_="posted", id_=1, close="03/04/2027"):
    return {"id": id_, "number": number, "title": title, "agencyCode": "X", "oppStatus": status_,
            "openDate": "01/01/2026", "closeDate": close}


def opp(program, status_, close, last_seen="2026-11-20", source="grants.gov", opp_id="1"):
    return {"program": program, "source": source, "opp_id": opp_id, "status": status_, "close_date": close,
            "first_seen": "2026-11-01", "last_seen": last_seen}


# ---------------------------------------------------------------- signals.yaml

def test_signals_reference_known_programs():
    ids = {p["id"] for p in registry.programs()}
    sig = common.signals()
    for section in ("grants_gov", "dsip", "manual"):
        assert set(sig[section]) <= ids, (section, set(sig[section]) - ids)


def test_every_program_has_a_feed_or_manual_check():
    sig = common.signals()
    covered = set(sig["grants_gov"]) | set(sig["dsip"]) | set(sig["manual"])
    assert {p["id"] for p in registry.programs()} == covered


def test_reporter_groups_are_programs():
    ids = {p["id"] for p in registry.programs()}
    assert set(common.signals().get("reporter") or {}) <= ids


def test_pattern_rules_name_a_search_keyword():
    for pid, rules in common.signals()["grants_gov"].items():
        if rules.get("patterns"):
            assert rules.get("search"), pid


# ---------------------------------------------------------------- Grants.gov

def test_number_match_is_exact():
    assert grants_gov.tracked_programs(hit("PA-27-101", "SBIR Phase IIB")) == ["nih-sbir-2"]
    assert grants_gov.tracked_programs(hit("PA-27-1010", "something else")) == []


def test_usda_pattern_takes_phase_i_only():
    assert grants_gov.tracked_programs(hit("USDA-NIFA-SBIR-010774", "SBIR and STTR Programs Phase I")) == ["usda-sbir-1"]
    assert grants_gov.tracked_programs(hit("USDA-NIFA-SBIR-012221", "SBIR and STTR Programs Phase II")) == []


def test_arpa_e_open_pattern():
    assert grants_gov.tracked_programs(hit("DE-FOA-0003500", "ARPA-E OPEN 2027")) == ["arpa-e-open"]
    assert grants_gov.tracked_programs(hit("DE-FOA-0001", "Open Access Data Platform")) == []
    assert grants_gov.tracked_programs(hit("SFOP0006524", "OPEN 2027 Government Partnership")) == []


@pytest.mark.parametrize("raw, out", [("03/04/2027", "2027-03-04"), ("Sep 17, 2024 12:00:00 AM EDT", "2024-09-17"),
                                      ("", ""), (None, ""), ("garbage", "")])
def test_dates(raw, out):
    assert grants_gov._date(raw) == out


@pytest.mark.parametrize("raw, out", [("181500", "181500"), ("none", ""), ("0", ""), ("1", ""), (2000000, "2000000"),
                                      ("1,250,000", "1250000"), (None, "")])
def test_money(raw, out):
    assert grants_gov._money(raw) == out


def test_row_unescapes_title_and_reads_synopsis():
    r = grants_gov.row("nsf-ttp", hit("25-540", "Translation &amp; Practice", id_=9),
                       {"synopsis": {"awardCeiling": "2000000", "awardFloor": "none", "estimatedFunding": "30000000"}})
    assert r["title"] == "Translation & Practice" and r["award_ceiling"] == "2000000" and r["award_floor"] == ""
    assert r["close_date"] == "2027-03-04" and r["url"].endswith("/9")


def test_cap_change_only_above_map_and_only_live():
    base = {"program": "nsf-ttp", "opp_id": "9", "number": "25-540", "url": ""}
    cap = common.programs()["nsf-ttp"]["award"]["max"]
    assert grants_gov.cap_changes([dict(base, award_ceiling=str(cap), status="posted")]) == []
    assert len(grants_gov.cap_changes([dict(base, award_ceiling=str(cap + 1), status="posted")])) == 1
    assert grants_gov.cap_changes([dict(base, award_ceiling=str(cap + 1), status="closed")]) == []
    assert grants_gov.cap_changes([dict(base, award_ceiling="", status="posted")]) == []


@pytest.mark.parametrize("title, keep", [
    ("SBIR/STTR Commercialization Readiness Pilot (CRP) Program", True),
    ("FY 2027 Build to Scale Notice of Funding Opportunity", True),
    ("Accelerating Scale-up and Pre-piloting of Emerging Chemical Technologies", True),
    ("Shared Instrumentation Grant (SIG) Program (S10 Clinical Trial Not Allowed)", False),
    ("Limited Competition: Kirschstein NRSA Small Business Predoctoral Training", False),
    ("Clinical and Translational Science Award (UM1 Clinical Trial Optional)", False)])
def test_discovery_title_filter(title, keep):
    cfg = common.signals()["discovery"]
    assert grants_gov.candidate(title, cfg["title_terms"], cfg["exclude_terms"]) is keep


# ---------------------------------------------------------------- DSIP

def topic(sol, comp, phases, status_="Open", start=1795266000000, end=1796058000000):
    return {"solicitationNumber": sol, "component": comp, "program": "SBIR", "topicStatus": status_,
            "solicitationTitle": "DoW SBIR", "topicStartDate": start, "topicEndDate": end,
            "phaseHierarchy": json.dumps({"config": [{"phase": p} for p in phases]})}


def test_dsip_routing():
    assert dsip.route(topic("27.BZ", "NAVY", ["1", "2", "2S"])) == ["dod-sbir-1", "dod-sbir-2"]
    assert dsip.route(topic("27.BZ", "NAVY", ["D2", "2"])) == ["dod-sbir-2"]
    assert dsip.route(dict(topic("x", "y", []), phaseHierarchy="not json")) == []


def test_dsip_aggregate_counts_and_status():
    rows = dsip.aggregate([topic("27.BZ", "NAVY", ["1"]), topic("27.BZ", "NAVY", ["1"], status_="Pre-Release"),
                           topic("27.TZ", "USAF", ["1"], status_="Pre-Release")])
    by = {r["opp_id"]: r for r in rows}
    assert by["27.BZ|NAVY|SBIR"]["topics"] == "2" and by["27.BZ|NAVY|SBIR"]["status"] == "posted"
    assert by["27.TZ|USAF|SBIR"]["status"] == "forecasted"
    assert by["27.BZ|NAVY|SBIR"]["close_date"] == dsip._day(1796058000000)


# ---------------------------------------------------------------- opportunities and queue

def test_merge_keeps_first_seen_and_closes_past_rows():
    old = [dict(opp("nsf-ttp", "posted", "2026-11-01", opp_id="a"), first_seen="2025-01-01"),
           opp("nsf-ttp", "posted", "2027-05-01", opp_id="b"),
           opp("dod-sbir-1", "posted", "2026-01-01", source="dsip", opp_id="c")]
    fresh = [dict(opp("nsf-ttp", "posted", "2027-05-18", opp_id="a"))]
    out = {r["opp_id"]: r for r in common.merge_opps(old, fresh, "grants.gov", TODAY)}
    assert out["a"]["first_seen"] == "2025-01-01" and out["a"]["last_seen"] == "2026-11-20"
    assert out["b"]["status"] == "posted"            # not returned, but not past its close date
    assert out["c"]["status"] == "posted"            # another source's row is untouched


def test_merge_marks_unreturned_past_close_as_closed():
    old = [opp("nsf-ttp", "posted", "2026-11-01", opp_id="a")]
    assert common.merge_opps(old, [], "grants.gov", TODAY)[0]["status"] == "closed"


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "QUEUE", tmp_path / "queue.csv")
    return tmp_path / "queue.csv"


def item(ident="x", kind="new-program"):
    return {"qid": common.qid(kind, "t", ident), "signal": "t", "program": "", "kind": kind, "title": ident, "url": "",
            "detail": {"a": 1}}


def test_enqueue_dedupes_even_after_rejection(queue):
    assert len(common.enqueue([item("x"), item("x"), item("y")], TODAY)) == 2
    rows = common.read_queue()
    rows[0]["status"] = "rejected"
    common.write_queue(rows)
    assert common.enqueue([item("x")], TODAY) == []
    assert json.loads(common.read_queue()[0]["detail"]) == {"a": 1}


def test_enqueue_rejects_unknown_kind(queue):
    with pytest.raises(AssertionError):
        common.enqueue([item("x", kind="other")], TODAY)


# ---------------------------------------------------------------- status

def test_status_derivation():
    opps = [opp("nsf-ttp", "posted", "2027-05-18"), opp("nsf-icorps", "posted", ""),
            opp("nih-sbir-1", "posted", "2026-11-01"), opp("nih-sbir-1", "forecasted", "2027-01-05", opp_id="2"),
            opp("usda-sbir-1", "closed", "2024-09-17", last_seen="2025-06-01")]
    s = status.derive(opps, TODAY)
    assert s["nsf-ttp"]["derived"] == "open"
    assert s["nsf-icorps"]["derived"] == "open"
    assert s["nih-sbir-1"]["derived"] == "upcoming" and s["nih-sbir-1"]["next_close"] == "2027-01-05"
    assert s["usda-sbir-1"]["derived"] == "between-rounds"
    assert s["arpa-e-open"]["derived"] == ""          # nothing on record: no claim
    kinds = {(i["program"], i["kind"]) for i in status.queue_items(s, TODAY)}
    assert ("usda-sbir-1", "possible-lapse") in kinds
    assert ("nih-sbir-1", "status-change") in kinds   # yaml says open
    assert not any(p == "arpa-e-open" for p, _ in kinds)


# ---------------------------------------------------------------- review

def test_set_status_edits_one_block():
    text = review.PROGRAMS.read_text()
    new = review.set_status("usda-sbir-1", "open", text)
    changed = [(a, b) for a, b in zip(text.splitlines(), new.splitlines()) if a != b]
    assert changed == [("    status: between-rounds", "    status: open")]
    with pytest.raises(KeyError):
        review.set_status("no-such-program", "open", text)


def test_decide_records_and_refuses_twice(queue):
    common.enqueue([item("x")], TODAY)
    q = common.read_queue()[0]["qid"]
    assert review.decide(q, "rejected", "not deep tech", TODAY)["note"] == "not deep tech"
    with pytest.raises(ValueError):
        review.decide(q, "accepted", "", TODAY)
