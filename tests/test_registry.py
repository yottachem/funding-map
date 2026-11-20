import datetime as dt
import os

import pytest

from tracker import registry


def test_registry_rules():
    assert registry.problems() == []


def test_cdr_is_not_a_domain():
    """Decided 2026-11-20: the map can support CDR work but is not built around it."""
    assert not any("cdr" in d for d in registry.DOMAINS)
    text = (registry.REFERENCE / "programs.yaml").read_text().lower()
    assert "nonlinear" not in text


def test_success_rates_never_estimated():
    for p in registry.programs():
        s = p["success"]
        assert ("rate" in s) != (s.get("published") is False), p["id"]


def test_every_sbir_program_has_award_data():
    stats = registry.sbir_stats()
    assert stats, "run tools/sbir_stats.py first"
    for p in registry.programs():
        if p.get("award_data"):
            row = registry.award_row(p, stats)
            assert int(row["awards"]) >= 10, p["id"]


def test_rules_catch_errors():
    srcs = {"a": {"url": "https://example.gov", "tier": 1}}
    progs = [{"id": "x", "name": "X", "funder": "F", "jurisdiction": "mars", "vehicle": "grant", "stage": "entry",
              "entity": "either", "domains": ["cdr"], "award": {"max": 1000}, "success": {"rate": 0.2},
              "deadlines": {"next": ["soon"]}, "status": "open", "sources": ["nope"], "feeds": ["x", "y"],
              "trl": [5, 3], "colour": 1}]
    found = "\n".join(registry.problems(progs, srcs, {}))
    for msg in ("jurisdiction", "domain 'cdr'", "award.max needs a source", "needs year, basis and source",
                "not a date", "not in sources", "feeds unknown program y", "feeds itself", "trl", "unknown key colour"):
        assert msg in found, msg


def test_launch_gate_flags_verify_and_tier2_rates():
    srcs = {"t2": {"url": "https://example.com", "tier": 2}}
    progs = [{"id": "x", "name": "X", "funder": "F", "jurisdiction": "federal", "vehicle": "grant", "stage": "entry",
              "entity": "either", "domains": ["materials"], "award": {"max": None, "note": "n"},
              "success": {"rate": 0.2, "year": "FY2022", "basis": "b", "source": "t2"},
              "deadlines": {"cadence": "Annual", "next": [dt.date(2027, 1, 5)]}, "status": "open",
              "sources": ["t2"], "verify": ["award.max"]}]
    found = "\n".join(registry.launch_problems(progs, srcs))
    for msg in ("open verify flags", "no sourced award size", "deadlines need a source", "tier-1 source"):
        assert msg in found, msg


def test_not_stated_needs_the_funders_document():
    srcs = {"t1": {"url": "https://example.gov", "tier": 1}, "t2": {"url": "https://example.com", "tier": 2}}
    base = {"id": "x", "name": "X", "funder": "F", "jurisdiction": "federal", "vehicle": "grant", "stage": "entry",
            "entity": "either", "domains": ["materials"], "success": {"published": False},
            "deadlines": {"cadence": "Rolling", "source": "t1"}, "status": "open", "sources": ["t1"]}
    ok = dict(base, award={"max": None, "not_stated": True, "source": "t1", "note": "n"})
    assert registry.launch_problems([ok], srcs) == []
    secondary = dict(base, award={"max": None, "not_stated": True, "source": "t2", "note": "n"})
    assert "tier-1 source" in "\n".join(registry.problems([secondary], srcs, {}))
    with_max = dict(base, award={"max": 5, "not_stated": True, "source": "t1"})
    assert "not_stated with a max" in "\n".join(registry.problems([with_max], srcs, {}))


@pytest.mark.skipif(not os.environ.get("LAUNCH_GATE"), reason="launch gate runs with LAUNCH_GATE=1")
def test_launch_gate():
    assert registry.launch_problems() == []


NESTED = {"award": {"max", "duration_months", "source", "note", "not_stated"},
          "success": {"rate", "year", "basis", "source", "also", "published", "note"},
          "timing": {"notify_days", "award_days", "basis", "source"},
          "deadlines": {"cadence", "next", "source"},
          "award_data": {"agency", "branch", "phase"},
          "award_recent": {"dataset", "group"},
          "requires": {"any", "after_months"}}


def test_nested_keys_are_known():
    """Catches flow-map values split by an unquoted comma ("Jan 5, Apr 5" becomes a stray key)."""
    for p in registry.programs():
        for key, allowed in NESTED.items():
            if key in p:
                assert set(p[key]) <= allowed, (p["id"], key, set(p[key]) - allowed)


def test_no_duplicate_yaml_keys():
    import yaml

    class Strict(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        keys = [loader.construct_object(k, deep=deep) for k, _ in node.value]
        dup = {k for k in keys if keys.count(k) > 1}
        assert not dup, f"duplicate keys {dup} at line {node.start_mark.line + 1}"
        return loader.construct_mapping(node, deep)

    Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    yaml.load((registry.REFERENCE / "programs.yaml").read_text(), Loader=Strict)
