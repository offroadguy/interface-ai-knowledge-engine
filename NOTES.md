# Versioned evidence engine

The solution uses Python 3.11 and the standard library. It runs offline and requires no API keys or paid services. Each ingest keeps a separate index for that crawl. Current questions use the latest crawl, and historical questions use the latest crawl at or before the supplied date. Inline ISO dates are supported when the caller omits the date argument.

Rate tables preserve the product, term, tier, metric, and source row. The resolver uses explicit effective dates to distinguish competing official rates and treats calculators and promotions as lower authority. Expired rows cannot answer a current rate question. Auto rates compare overlapping model-year ranges for the same term. The conflict report also captures structured rate corrections that reuse an effective date, as well as competing routing-number and branch-count claims. Ordinary changes with different effective dates remain part of the history.

The prose index ranks passages using both text and page context. Focused extractors check branch identity, contact details, links, and fee schedules. If a fee schedule disappears, the answer can cite a previous schedule as last known and explicitly marks the current fee unverified. Other unsupported or unresolved questions abstain. Citations carry the URL and snapshot ID, plus the supporting row or passage when available. The prose fallback is lexical and can miss unfamiliar wording. Conflict detection covers the structured facts above. It does not claim exhaustive contradiction detection in arbitrary prose.

In a production rollout, I would validate a new crawl before activating it. I would check rate-table coverage, citation integrity, and known-answer probes against the candidate index. A failed check would hold promotion and alert the operator. The last validated crawl would remain available within an explicit freshness limit. Beyond that limit, rate questions would abstain until the data was verified.

I used Codex to help develop the implementation, regression tests, and documentation. The evaluation commands below reproduce the reported checks with the organizer's kit.

## Run locally

Put the organizer-provided kit in a sibling directory named `participant-kit`. From this repository, with Python 3.11 active, run:

```sh
PYTHONPATH=../participant-kit/harness python -m unittest -v

python ../participant-kit/harness/run_eval.py \
  --submission . \
  --snapshots ../participant-kit/snapshots \
  --eval ../participant-kit/eval/public_eval.jsonl \
  --out ../participant-kit/results/submission

python ../participant-kit/harness/run_eval.py \
  --submission . \
  --snapshots ../participant-kit/harness/selftest/snapshots \
  --eval ../participant-kit/harness/selftest/eval.jsonl \
  --conflicts-gold ../participant-kit/harness/selftest/conflicts_gold.json \
  --out ../participant-kit/results/submission-selftest
```
