"""Check a candidate crawl's rate coverage and optional known answers."""

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path

from auto_rates import auto_rate_conflicts, extract_auto_rates
from contract import Snapshot
from rate_tables import extract_rates, resolved_rates
from run_eval import load_snapshots
from solution import build


@dataclass(frozen=True)
class Probe:
    id: str
    question: str
    expected_text: str
    source_url: str
    source_quote: str


def load_probes(path: Path) -> tuple[Probe, ...]:
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise ValueError("The probes file must contain a nonempty JSON array.")
    fields = {"id", "question", "expected_text", "source_url", "source_quote"}
    if any(not isinstance(record, dict) or record.keys() != fields or
           any(not isinstance(value, str) or not value.strip() for value in record.values())
           for record in records):
        raise ValueError("Each probe needs nonempty id, question, expected_text, source_url, and source_quote strings.")
    probes = tuple(Probe(**record) for record in records)
    if len({probe.id for probe in probes}) != len(probes):
        raise ValueError("Probe IDs must be unique.")
    return probes


def _probe_failures(candidate: Snapshot, probes: tuple[Probe, ...]) -> list[str]:
    system = build()
    system.ingest(candidate)
    pages = {page.url: page.markdown for page in candidate.pages}
    failures = []
    for probe in probes:
        answer = system.answer(probe.question)
        if not answer.confident:
            failures.append(f"probe {probe.id}: candidate answer was unverified")
        elif answer.text != probe.expected_text:
            failures.append(f"probe {probe.id}: candidate answer did not match the approved text")
        elif not any(source.url == probe.source_url and source.quote == probe.source_quote
                     and source.snapshot_id == candidate.snapshot_id and source.quote in pages.get(source.url, "")
                     for source in answer.sources):
            failures.append(f"probe {probe.id}: expected citation was not verified")
    return failures


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


def check_crawl(reference: Snapshot, candidate: Snapshot, minimum_percent: int = 80, *,
                probes: tuple[Probe, ...] = ()) -> dict:
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
    failed_probes = _probe_failures(candidate, probes) if probes else []
    failures.extend(failed_probes)
    return {
        "decision": "hold" if failures else "pass",
        "reference": reference.snapshot_id,
        "candidate": candidate.snapshot_id,
        "minimum_percent": minimum_percent,
        "coverage": coverage,
        "probes": {"total": len(probes), "failed": len(failed_probes)},
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--reference", required=True, help="ID of the last validated crawl")
    parser.add_argument("--candidate", required=True, help="ID of the crawl to check")
    parser.add_argument("--minimum-percent", type=int, default=80)
    parser.add_argument("--probes", type=Path, help="JSON file of approved candidate answers and citations")
    args = parser.parse_args()
    try:
        snapshots = {snapshot.snapshot_id: snapshot for snapshot in load_snapshots(args.snapshots)}
        probes = load_probes(args.probes) if args.probes is not None else ()
        report = check_crawl(snapshots[args.reference], snapshots[args.candidate], args.minimum_percent, probes=probes)
    except (KeyError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))
    return 1 if report["decision"] == "hold" else 0


if __name__ == "__main__":
    raise SystemExit(main())
