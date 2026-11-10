"""Report whether a candidate crawl retains enough usable rate coverage."""

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path

from auto_rates import auto_rate_conflicts, extract_auto_rates
from contract import Snapshot
from rate_tables import extract_rates, resolved_rates
from run_eval import load_snapshots


def rate_coverage(snapshot: Snapshot) -> Counter:
    published, _ = resolved_rates(extract_rates(snapshot), date.fromisoformat(snapshot.taken_on))
    # A second copy of the same rate on another page cannot inflate coverage.
    facts = {(row.key, metric) for row, metric, _ in published}
    counts = Counter(key[0] for key, _ in facts)
    auto = extract_auto_rates(snapshot)
    unresolved = {source.quote for conflict in auto_rate_conflicts(auto) if conflict.resolution is None
                  for source in conflict.sources}
    counts["auto"] = len({
        (row.months, row.first_year, row.last_year)
        for row in auto if row.official and row.source.quote not in unresolved
    })
    return counts


def check_crawl(reference: Snapshot, candidate: Snapshot, minimum_percent: int = 80) -> dict:
    if not 1 <= minimum_percent <= 100:
        raise ValueError("Minimum coverage must be between 1 and 100 percent.")
    if date.fromisoformat(candidate.taken_on) <= date.fromisoformat(reference.taken_on):
        raise ValueError("The candidate must be newer than the validated reference.")

    before, after = rate_coverage(reference), rate_coverage(candidate)
    if not any(before.values()):
        raise ValueError("The reference crawl has no usable official rate facts.")

    coverage, failures = {}, []
    for family in sorted(before.keys() | after.keys()):
        coverage[family] = {"reference": before[family], "candidate": after[family]}
        if 100 * after[family] < minimum_percent * before[family]:
            failures.append(f"{family}: {after[family]}/{before[family]} usable rate facts")
    return {
        "decision": "hold" if failures else "pass",
        "reference": reference.snapshot_id,
        "candidate": candidate.snapshot_id,
        "minimum_percent": minimum_percent,
        "coverage": coverage,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--reference", required=True, help="ID of the last validated crawl")
    parser.add_argument("--candidate", required=True, help="ID of the crawl to check")
    parser.add_argument("--minimum-percent", type=int, default=80)
    args = parser.parse_args()
    try:
        snapshots = {snapshot.snapshot_id: snapshot for snapshot in load_snapshots(args.snapshots)}
        report = check_crawl(snapshots[args.reference], snapshots[args.candidate], args.minimum_percent)
    except (KeyError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))
    return 1 if report["decision"] == "hold" else 0


if __name__ == "__main__":
    raise SystemExit(main())
