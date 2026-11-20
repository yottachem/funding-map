# Non-Dilutive Funding Map

Grant and contract programs for deep tech companies (instruments, diagnostics, materials, energy and climate, hardware), graded on sourced award size, success rate, and time to award. Federal programs plus Massachusetts.

Every figure links its source. Success rates come only from the funder or the SBA; where none is published the map says so rather than estimating.

## Layout

| Path | Holds |
|------|-------|
| `reference/programs.yaml` | Program registry: rules, caps, published success rates, deadlines, stacking links, and the source for each |
| `reference/awards/sbir_stats.csv` | Computed from SBIR.gov award data (award years 2022-2024): award size p10/median/p90 and days from proposal receipt to award, per agency, branch, and phase |
| `tools/sbir_stats.py` | Builds `sbir_stats.csv` from the SBIR.gov bulk CSV (download to `data/raw/sbir_award_data.csv`) |
| `tracker/registry.py` | Registry rules (`problems()`) and the launch gate (`launch_problems()`) |

## Run

```
uv sync --all-groups
curl -o data/raw/sbir_award_data.csv https://data.www.sbir.gov/awarddatapublic/award_data.csv
uv run python tools/sbir_stats.py
uv run pytest            # LAUNCH_GATE=1 adds the launch gate
```

## Status

Phase 1 (registry seed, award statistics, rules and tests). Ingest, picker, and site follow.
