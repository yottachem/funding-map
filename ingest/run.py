"""Scheduled entry point.

  uv run python -m ingest.run --weekly                      Grants.gov, DSIP, then status derivation
  uv run --group data python -m ingest.run --quarterly      award history (SBIR.gov file, RePORTER, NSF, USAspending)

A failing source is reported and the rest still run; the exit code is non-zero if any failed.
"""
from __future__ import annotations

import argparse
import sys
import traceback


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--weekly", action="store_true")
    g.add_argument("--quarterly", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.weekly:
        from ingest import dsip, grants_gov, status
        steps = [("grants.gov", lambda: grants_gov.run(a.dry_run)), ("dsip", lambda: dsip.run(a.dry_run)),
                 ("status", lambda: status.run(a.dry_run))]
    else:
        from ingest import award_stats
        steps = [("award_stats", award_stats.run)]
    failed = 0
    for name, fn in steps:
        try:
            print(f"{name}: {fn()}")
        except Exception:  # noqa: BLE001 - one source failing must not stop the others
            failed += 1
            print(f"{name}: FAILED\n{traceback.format_exc()}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
