#!/bin/sh
set -eu

repo_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
kit_dir=${1:-"$repo_dir/../participant-kit"}
python=${PYTHON:-python3.11}
results_dir="$repo_dir/results"

for file in harness/run_eval.py eval/public_eval.jsonl harness/selftest/eval.jsonl harness/selftest/conflicts_gold.json
do
    if [ ! -f "$kit_dir/$file" ]; then
        printf 'Missing %s. Pass the path to the unpacked organizer kit.\n' "$kit_dir/$file" >&2
        exit 1
    fi
done
kit_dir=$(CDPATH='' cd -- "$kit_dir" && pwd)

"$python" -c 'import sys; assert sys.version_info[:2] == (3, 11), "Python 3.11 required"'
cd "$repo_dir"
PYTHONPATH="$kit_dir/harness" "$python" -m unittest -v
"$python" "$kit_dir/harness/run_eval.py" \
    --submission "$repo_dir" \
    --snapshots "$kit_dir/snapshots" \
    --eval "$kit_dir/eval/public_eval.jsonl" \
    --out "$results_dir/public"
"$python" "$kit_dir/harness/run_eval.py" \
    --submission "$repo_dir" \
    --snapshots "$kit_dir/harness/selftest/snapshots" \
    --eval "$kit_dir/harness/selftest/eval.jsonl" \
    --conflicts-gold "$kit_dir/harness/selftest/conflicts_gold.json" \
    --out "$results_dir/selftest"
