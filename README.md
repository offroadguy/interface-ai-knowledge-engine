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
| Keep APY, APR, balance tiers, and offer dates distinct | [rate_tables.py](rate_tables.py) | [Expired offer and historical correction tests](test_knowledge.py) |
| Cite prose evidence or abstain when a fact cannot be verified | [evidence.py](evidence.py) | [Missing location and historical fee tests](test_knowledge.py) |
| Hold an incomplete crawl before it serves rates | [scripts/check_crawl.py](scripts/check_crawl.py) | [Crawl coverage and failure tests](test_check_crawl.py) |

## Check a candidate crawl

Run the optional [crawl coverage check](scripts/check_crawl.py) against the last validated snapshot before serving a candidate. It emits JSON with the crawl IDs, the coverage counts, and the decision. Exit code `0` means the coverage check passed, `1` means hold, and `2` means the check could not run with the supplied inputs.

```sh
PYTHONPATH=../participant-kit/harness python3.11 -m scripts.check_crawl \
  --snapshots ../participant-kit/snapshots \
  --reference 04_2026-08-27_rebaseline \
  --candidate 05_2026-09-28_latest
```

## Sample run

A local Python 3.11 run of `sh scripts/verify.sh` produced the following excerpts.

```text
Ran 9 tests in 0.005s
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

The crawl check passed for the August-to-September comparison above. In a separate run with a fabricated candidate missing one of two auto-rate facts, it returned a hold.

```json
{
  "decision": "hold",
  "reference": "validated",
  "candidate": "candidate",
  "minimum_percent": 80,
  "coverage": {
    "auto": {
      "reference": 2,
      "candidate": 1
    }
  },
  "failures": [
    "auto: 1/2 usable rate facts"
  ]
}
```
