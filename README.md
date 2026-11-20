# Non-Dilutive Funding Map

Grant and contract programs for deep tech companies (instruments, diagnostics, materials, energy and climate, hardware), graded on sourced award size, success rate, and time to award. Federal programs plus Massachusetts.

Every figure links its source. Success rates come only from the funder or the SBA; where none is published the map says so rather than estimating.

## Layout

| Path | Holds |
|------|-------|
| `reference/programs.yaml` | Program registry: rules, caps, published success rates, deadlines, stacking links, and the source for each |
| `reference/awards/sbir_stats.csv` | Computed from SBIR.gov award data (award years 2022-2024): award size p10/median/p90 and days from proposal receipt to award, per agency, branch, and phase |
| `tools/sbir_stats.py` | Builds `sbir_stats.csv` from the SBIR.gov bulk CSV (download to `data/raw/sbir_award_data.csv`) |
| `reference/awards/recent.csv` | Recent fiscal years from NIH RePORTER (R41-R44 new awards), NSF Awards API (SBIR/STTR Phase I and II) and USAspending (ARPA-E by OPEN cohort): award size p10/median/p90 per group and year |
| `reference/signals.yaml` | Fetch settings: Grants.gov numbers and patterns, DSIP phase routing, manual-check URLs, discovery terms |
| `reference/opportunities.csv` | Open and forecast solicitations matched to programs (Grants.gov, DSIP); tier 1, auto-accepted |
| `data/review/queue.csv` | Review queue: new-program, cap-change, status-change and possible-lapse candidates with decisions |
| `data/program_status.csv` | Status derived from opportunities, beside the registry's status |
| `ingest/` | Collectors (`grants_gov`, `dsip`, `award_stats`), status derivation, and the `run` entry point |
| `tools/review.py` | List, accept and reject queue items (accepting a status-change edits `programs.yaml`) |
| `tracker/registry.py` | Registry rules (`problems()`) and the launch gate (`launch_problems()`) |
| `tracker/picker.py` | Picker: profile in; eligible programs ranked by expected value (typical size x published odds), stacking chains along `requires`, an 18-month calendar, and the reason each other program is out |
| `reference/example_profiles.yaml` | Three fictional company profiles used by the tests and the site |

## Run

```
uv sync --all-groups
curl -o data/raw/sbir_award_data.csv https://data.www.sbir.gov/awarddatapublic/award_data.csv
uv run python tools/sbir_stats.py
uv run pytest            # LAUNCH_GATE=1 adds the launch gate

uv run python -m ingest.run --weekly                    # Grants.gov + DSIP + status derivation
uv run --group data python -m ingest.run --quarterly    # award history; re-downloads the SBIR file only when newer
uv run python -m tools.review                           # open queue items
uv run python -m tools.review accept|reject <qid> [note]
uv run python -m tracker.picker [--profile id] [--start YYYY-MM-DD] [--json]   # roadmaps for the example profiles
```

Nothing a collector finds edits `programs.yaml` directly. Opportunities from the funders' own systems are recorded as found; anything that would change the registry (a new program, a higher cap, a status change, a possible lapse) waits in the review queue. A rejected item never returns.

## Status

Phase 3 (picker) done 2026-11-20: eligibility, expected value from published odds only, stacking, calendar; dates never guessed. Phase 2 (ingest and review queue) done 2026-11-20; first queue review 2026-11-20 added 4 NIH programs (31 total). Site follows (Phase 4). Launch gate clear 2026-11-20 (`LAUNCH_GATE=1 pytest`): every program has a sourced size, sourced deadlines and no verify flags.
