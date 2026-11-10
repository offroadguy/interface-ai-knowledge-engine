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

## Measured results

| Check | Local Python 3.11 run |
| --- | --- |
| Organizer public evaluation, 40 questions | 0.9535 vs. 0.093 for the starter. Zero execution errors and zero stale-value traps. |
| Public answer latency | 0.02 s p95 on the development machine. |
| Organizer self-test | 1.0 across five questions and one labeled conflict. |
| Unit tests | Six passed. |

The public evaluation checks answer quality on the supplied questions. The labeled self-test exercises the conflict scorer on one known case. The hidden evaluation remains unmeasured.
