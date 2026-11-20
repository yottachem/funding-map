"""Quarterly award history: what funders actually paid, newer than the SBIR.gov bulk file.

  sbir        SBIR.gov bulk award CSV: re-downloaded only when its Last-Modified is newer than the copy in data/raw,
              then tools/sbir_stats.py rebuilds reference/awards/sbir_stats.csv.
  nih         NIH RePORTER v2: new awards (type 1) by activity code (R43, R44, R41, R42) and fiscal year.
  nsf         NSF Awards API: awards titled "SBIR Phase I:", "SBIR Phase II:", "STTR Phase I:", "STTR Phase II:" by
              NSF fiscal year of the award date. Amount = estimatedTotalAmt.
  arpa-e      USAspending: ARPA-E assistance awards (assistance listing 81.135, award ids DEAR*). The FOA named in the
              award description sets the group: "OPEN 2018", "OPEN 2021", ...; everything else is "other".

All four are tier 1 (the funder's own records or the federal spending record). Output is aggregate only:
reference/awards/recent.csv (dataset, group, fiscal_year, awards, amount_p10/median/p90, ma_awards, pulled).
Programs link to a row group with `award_recent: {dataset, group}` in programs.yaml.

Run: uv run --group data python -m ingest.award_stats [--skip-sbir]
"""
from __future__ import annotations

import argparse
import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime

import pandas as pd

from ingest.common import REF, RAW, session, write_snapshot

OUT = REF / "awards" / "recent.csv"
SBIR_CSV = "https://data.www.sbir.gov/awarddatapublic/award_data.csv"
SBIR_RAW = RAW / "sbir_award_data.csv"
SBIR_STAMP = RAW / "sbir_award_data.last_modified"
REPORTER = "https://api.reporter.nih.gov/v2/projects/search"
NSF = "https://api.nsf.gov/services/v1/awards.json"
USASPENDING = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
NIH_CODES = ("R43", "R44", "R41", "R42")
NSF_PREFIXES = ("SBIR Phase I", "SBIR Phase II", "STTR Phase I", "STTR Phase II")
OPEN_RE = re.compile(r"\bOPEN\s+(20\d\d)\b")


def fiscal_years(today: date) -> list[int]:
    """The last two completed federal fiscal years and the current one."""
    fy = today.year + (today.month >= 10)
    return [fy - 2, fy - 1, fy]


def fy_of(d: date) -> int:
    return d.year + (d.month >= 10)


# ---------------------------------------------------------------- SBIR.gov bulk file

def sbir_refresh(s) -> str:
    head = s.head(SBIR_CSV, timeout=60, allow_redirects=True)
    head.raise_for_status()
    remote = head.headers.get("Last-Modified", "")
    local = SBIR_STAMP.read_text().strip() if SBIR_STAMP.exists() else ""
    if SBIR_RAW.exists() and local and remote and parsedate_to_datetime(remote) <= parsedate_to_datetime(local):
        return f"unchanged ({local})"
    with s.get(SBIR_CSV, stream=True, timeout=600) as r:
        r.raise_for_status()
        SBIR_RAW.parent.mkdir(parents=True, exist_ok=True)
        with SBIR_RAW.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    SBIR_STAMP.write_text(remote)
    from tools import sbir_stats
    res = sbir_stats.build()
    res.to_csv(sbir_stats.OUT, index=False)
    return f"downloaded ({remote}); sbir_stats.csv rebuilt, {len(res)} rows"


# ---------------------------------------------------------------- collectors (one record per award)

def nih(s, years: list[int]) -> list[dict]:
    out = []
    for code in NIH_CODES:
        offset = 0
        while True:
            body = {"criteria": {"activity_codes": [code], "fiscal_years": years, "award_types": ["1"]},
                    "include_fields": ["ApplId", "ActivityCode", "FiscalYear", "AwardAmount", "Organization"],
                    "limit": 500, "offset": offset}
            r = s.post(REPORTER, json=body, timeout=120)
            r.raise_for_status()
            d = r.json()
            for p in d["results"]:
                out.append({"dataset": "nih-reporter", "group": p["activity_code"], "fiscal_year": p["fiscal_year"],
                            "amount": p.get("award_amount"), "state": (p.get("organization") or {}).get("org_state"),
                            "id": p["appl_id"]})
            offset += 500
            if offset >= d["meta"]["total"] or offset >= 15000:
                break
    return out


def nsf(s, years: list[int]) -> list[dict]:
    out, seen = [], set()
    for fy in years:
        start, end = f"10/01/{fy - 1}", f"09/30/{fy}"
        for prefix in NSF_PREFIXES:
            offset = 1
            while True:
                r = s.get(NSF, params={"keyword": f'"{prefix}"', "dateStart": start, "dateEnd": end, "rpp": 25,
                                       "offset": offset,
                                       "printFields": "id,title,estimatedTotalAmt,date,awardeeStateCode"}, timeout=120)
                r.raise_for_status()
                resp = r.json()["response"]
                awards = resp.get("award", [])
                for a in awards:
                    if not a["title"].startswith(prefix + ":") or a["id"] in seen:
                        continue
                    seen.add(a["id"])
                    out.append({"dataset": "nsf-awards", "group": prefix,
                                "fiscal_year": fy_of(datetime.strptime(a["date"], "%m/%d/%Y").date()),
                                "amount": a.get("estimatedTotalAmt"), "state": a.get("awardeeStateCode"),
                                "id": a["id"]})
                offset += 25
                if not awards or offset > resp.get("metadata", {}).get("totalCount", 0):
                    break
    return out


def arpa_e(s, first_fy: int, last_fy: int) -> list[dict]:
    out, page = [], 1
    body = {"filters": {"program_numbers": ["81.135"], "award_type_codes": ["02", "03", "04", "05"],
                        "time_period": [{"start_date": f"{first_fy - 1}-10-01", "end_date": f"{last_fy}-09-30"}]},
            "fields": ["Award ID", "Award Amount", "Start Date", "Place of Performance State Code", "Description"],
            "limit": 100, "sort": "Award Amount", "order": "desc"}
    while True:
        r = s.post(USASPENDING, json={**body, "page": page}, timeout=120)
        r.raise_for_status()
        d = r.json()
        for a in d["results"]:
            if not str(a["Award ID"]).startswith("DEAR") or not a.get("Start Date"):
                continue
            m = OPEN_RE.search(a.get("Description") or "")
            out.append({"dataset": "arpa-e", "group": f"OPEN {m.group(1)}" if m else "other",
                        "fiscal_year": fy_of(date.fromisoformat(a["Start Date"])), "amount": a["Award Amount"],
                        "state": a.get("Place of Performance State Code"), "id": a["Award ID"]})
        if not d.get("page_metadata", {}).get("hasNext"):
            return out
        page += 1


# ---------------------------------------------------------------- aggregate

def aggregate(records: list[dict], today: date) -> pd.DataFrame:
    df = pd.DataFrame(records)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df = df[df["amount"] > 0]
    q = lambda p: (lambda s: s.quantile(p))  # noqa: E731
    out = df.groupby(["dataset", "group", "fiscal_year"]).agg(
        awards=("amount", "size"), amount_p10=("amount", q(.10)), amount_median=("amount", "median"),
        amount_p90=("amount", q(.90)), ma_awards=("state", lambda s: int((s == "MA").sum()))).reset_index()
    num = ["amount_p10", "amount_median", "amount_p90"]
    out[num] = out[num].round(0).astype("Int64")
    out["pulled"] = today.isoformat()
    return out.sort_values(["dataset", "group", "fiscal_year"])


def run(skip_sbir: bool = False, today: date | None = None) -> dict:
    today = today or date.today()
    s = session()
    years = fiscal_years(today)
    result = {"sbir": "skipped" if skip_sbir else sbir_refresh(s)}
    records = nih(s, years) + nsf(s, years) + arpa_e(s, years[0] - 5, years[-1])
    write_snapshot("award_stats", records, today)
    out = aggregate(records, today)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    result.update(records=len(records), rows=len(out))
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-sbir", action="store_true")
    print(run(ap.parse_args().skip_sbir))
