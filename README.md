# Versioned evidence engine

A Python solution for the Interface.ai take-home. It answers questions against dated website snapshots, cites the evidence it used, and reports conflicting claims with a resolution when the evidence supports one.

## Evaluate

Use Python 3.11 and unpack the organizer-provided kit next to this checkout as `participant-kit`. Run this from the checkout:

```sh
sh scripts/verify.sh
```

The script runs the unit tests, the unchanged public evaluator, and the organizer's labeled self-test. It prints the results and writes local reports under `results/`. To use another kit location, pass its path as the first argument. Set `PYTHON` to select a different Python 3.11 executable. The solution uses the standard library and needs no network connection or credentials.

The grader entry point is [`solution.build()`](solution.py). It returns a system with `ingest`, `answer`, and `conflicts` methods. [NOTES.md](NOTES.md) has the equivalent direct scorer commands and describes the decision rules.

## What to inspect

| Behavior | Implementation | Verification |
| --- | --- | --- |
| Select a crawl for current and historical questions | [solution.py](solution.py) | [Historical rate and balance boundary tests](test_knowledge.py) |
| Compare loan rates only for the same term and overlapping model years | [auto_rates.py](auto_rates.py) | [Auto loan source and ambiguity tests](test_auto_rates.py) |
| Keep rates distinct by product, customer segment, term, and tier | [rate_tables.py](rate_tables.py) | [Deposit segment, loan amount, and offer expiry tests](test_knowledge.py) |
| Require evidence for the named institution or branch | [evidence.py](evidence.py) | [Routing and branch service tests](test_knowledge.py) |
| Check a candidate crawl's coverage and approved answers | [scripts/check_crawl.py](scripts/check_crawl.py) | [Coverage, rate, and citation checks](test_check_crawl.py) |

## Check a candidate crawl

Run the optional [crawl check](scripts/check_crawl.py) against the last validated snapshot before serving a candidate. It emits JSON with the crawl IDs, rate coverage, probe counts, and the decision. Exit code `0` means pass, `1` means hold, and `2` means invalid inputs.

```sh
PYTHONPATH=../participant-kit/harness python3.11 -m scripts.check_crawl \
  --snapshots ../participant-kit/snapshots \
  --reference 04_2026-08-27_rebaseline \
  --candidate 05_2026-09-28_latest
```

Add `--probes /path/to/approved-probes.json` to verify critical answers as well as coverage. The file contains a nonempty JSON array of uniquely named probes. This fabricated example shows the format.

```json
[
  {
    "id": "auto-48",
    "question": "What's the 48-month auto loan APR for a 2025 vehicle?",
    "expected_text": "The published 48-month auto loan rate for a 2025 vehicle is as low as 4.75% APR.",
    "source_url": "https://example.test/rates",
    "source_quote": "| 2024-27 Model Year | 48 Months | 4.75% APR |"
  }
]
```

The check requires a confident answer with the exact approved text and a matching citation whose quote occurs in the candidate crawl. Review and update the expected text and citation when a source confirms a legitimate change.

## Sample run

A local Python 3.11 run of `sh scripts/verify.sh` produced the following excerpts.

```text
Ran 15 tests
OK

Public evaluation
  "questions": 40,
  "stale_trap_hits": 0,
  "errors": 0,
  "final_score": 0.9535,

Organizer self-test
  "questions": 5,
  "matched": 1,
  "resolution_accuracy": 1.0
  "final_score": 1.0,
```

The starter scored 0.093 on the same public questions. The solution's p95 response time was 0.02 seconds on the development machine. The labeled self-test checks one known conflict. The hidden evaluation remains unmeasured.

The coverage check passed for the August-to-September comparison above. In a separate run, the fabricated candidate replaced a 48-month loan tier and changed the 60-month APR. The counts stayed the same and both probes failed.

```json
{
  "decision": "hold",
  "reference": "validated",
  "candidate": "candidate",
  "minimum_percent": 80,
  "coverage": {
    "auto": {
      "reference": 2,
      "candidate": 2
    }
  },
  "probes": {
    "total": 2,
    "failed": 2
  },
  "failures": [
    "probe auto-48: candidate answer was unverified",
    "probe auto-60: candidate answer did not match the approved text"
  ]
}
```
