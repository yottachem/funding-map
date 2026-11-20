"""Award size and timing per agency (and DoD/HHS/DOC branch) and phase, from the SBIR.gov bulk award CSV.

Source: https://data.www.sbir.gov/awarddatapublic/award_data.csv (download to data/raw/sbir_award_data.csv).
Window: award years 2022-2024 (the file's latest complete year as of its 2026-01-01 update is 2024).

Days to award = Proposal Award Date - Proposal Receipt Date (receipt is present on every row; solicitation close dates
are unreliable for open-window agencies such as NSF). Intervals < 0 or > 730 days are dropped as entry errors.
SBIR and STTR are combined per phase; a program record links here by (agency, branch, phase).
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/raw/sbir_award_data.csv"
OUT = ROOT / "reference/awards/sbir_stats.csv"
YEARS = (2022, 2023, 2024)

AGENCY = {"Department of Health and Human Services": "HHS", "National Science Foundation": "NSF",
          "Department of Energy": "DOE", "Department of Defense": "DOD",
          "National Aeronautics and Space Administration": "NASA", "Department of Agriculture": "USDA",
          "Department of Commerce": "DOC", "Environmental Protection Agency": "EPA",
          "Department of Homeland Security": "DHS", "Department of Transportation": "DOT",
          "Department of Education": "ED"}
BRANCH = {"National Institutes of Health": "NIH", "National Oceanic and Atmospheric Administration": "NOAA",
          "National Institute of Standards and Technology": "NIST", "Defense Health Program": "DHA",
          "Air Force": "Air Force", "Navy": "Navy", "Army": "Army",
          "Defense Advanced Research Projects Agency": "DARPA"}


def load() -> pd.DataFrame:
    cols = ["Agency", "Branch", "Phase", "Award Year", "Award Amount", "Proposal Receipt Date", "Proposal Award Date",
            "State"]
    df = pd.read_csv(SRC, usecols=cols, dtype=str, low_memory=False)
    df["agency"] = df["Agency"].map(AGENCY).fillna(df["Agency"])
    df["branch"] = df["Branch"].map(BRANCH)
    df["phase"] = df["Phase"].str.replace("Phase ", "", regex=False)
    df["year"] = pd.to_numeric(df["Award Year"], errors="coerce")
    df["amount"] = pd.to_numeric(df["Award Amount"].str.replace(",", ""), errors="coerce")
    received = pd.to_datetime(df["Proposal Receipt Date"], format="%m/%d/%Y", errors="coerce")
    awarded = pd.to_datetime(df["Proposal Award Date"], format="%m/%d/%Y", errors="coerce")
    df["days"] = (awarded - received).dt.days
    df.loc[(df["days"] < 0) | (df["days"] > 730), "days"] = pd.NA
    return df[df["year"].isin(YEARS)]


def stats(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    q = lambda p: (lambda s: s.quantile(p))  # noqa: E731
    out = df.groupby(keys, dropna=False).agg(
        awards=("amount", "size"), amount_p10=("amount", q(.10)), amount_median=("amount", "median"),
        amount_p90=("amount", q(.90)), days_p25=("days", q(.25)), days_median=("days", "median"),
        days_p75=("days", q(.75)), days_n=("days", "count"), ma_awards=("State", lambda s: int((s == "MA").sum())))
    return out.reset_index()


def build() -> pd.DataFrame:
    df = load()
    whole = stats(df, ["agency", "phase"]).assign(branch="")
    parts = stats(df[df["branch"].notna()], ["agency", "branch", "phase"])
    res = pd.concat([whole, parts], ignore_index=True)
    res = res[["agency", "branch", "phase", "awards", "amount_p10", "amount_median", "amount_p90", "days_p25",
               "days_median", "days_p75", "days_n", "ma_awards"]]
    num = res.columns[3:]
    res[num] = res[num].round(0).astype("Int64")
    return res.sort_values(["agency", "branch", "phase"])


if __name__ == "__main__":
    res = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT, index=False)
    print(f"award years {YEARS[0]}-{YEARS[-1]} -> {OUT.relative_to(ROOT)} ({len(res)} rows)")
    print(res.to_string(index=False))
