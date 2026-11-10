# Versioned evidence engine

The solution uses Python 3.11 and the standard library. It runs offline and requires no API keys or paid services. Each ingest keeps a separate index for that crawl. Current questions use the latest crawl, and historical questions use the latest crawl at or before the supplied date. Inline ISO dates are supported when the caller omits the date argument.

Rate tables preserve the product, customer segment for deposits, term, tier, metric, and source row. The resolver uses explicit effective dates to distinguish competing official rates and treats calculators and promotions as lower authority. Expired rows cannot answer a current rate question. Auto rates compare overlapping model-year ranges for the same term. Answers keep the published “as low as” qualifier and abstain on requests for an unverified maximum loan APR. The conflict report also captures structured rate corrections that reuse an effective date, as well as competing routing-number and branch-count claims. Ordinary changes with different effective dates remain part of the history.

The prose index ranks passages using both text and page context. Focused extractors check branch identity, contact details, links, and fee schedules. If a fee schedule disappears, the answer can cite a previous schedule as last known and explicitly marks the current fee unverified. Other unsupported or unresolved questions abstain. Citations carry the URL and snapshot ID, plus the supporting row or passage when available. The prose fallback is lexical and can miss unfamiliar wording. Conflict detection covers the structured facts above. It does not claim exhaustive contradiction detection in arbitrary prose.

The optional crawl check compares counts of distinct usable rate facts by product family against the last validated crawl. Its default threshold is 80% per family, an initial review threshold that operators would tune using observed crawl history. A legitimate product retirement can trigger a hold. Optional probes check exact approved answers and supporting quotes from the candidate. They catch changes to covered facts even when the counts stay stable. The exact match means an approved wording or citation change also requires updating its probe. In production, on hold, the operator would investigate the affected family or probe and keep serving the last validated crawl within its freshness limit. Beyond that limit, rate questions would abstain until the data was verified.

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
