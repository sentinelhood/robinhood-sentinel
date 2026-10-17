#!/usr/bin/env bash
# Refresh public/hook-usage.json from the same helper Aeon operators run.
# Usage: scripts/snapshot-hook-usage.sh [state-file] [days]
# The state file is kept outside the repo so the backfill is reused between runs.
set -euo pipefail
cd "$(dirname "$0")/.."
STATE="${1:-${HOOK_USAGE_STATE:-$HOME/.cache/sentinel/hook-usage.json}}"
DAYS="${2:-7}"
mkdir -p "$(dirname "$STATE")"
tmp="$(mktemp)"
python3 skills/hook-usage/hook_usage.py --state "$STATE" --days "$DAYS" --json > "$tmp"
python3 - "$tmp" <<'PY'
import json, sys, datetime
r = json.load(open(sys.argv[1]))
assert r['chainId'] == 4663 and r['hooks'], 'refusing to publish an empty or wrong-chain report'
r['generatedAt'] = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
r['source'] = 'skills/hook-usage/hook_usage.py via rpc.mainnet.chain.robinhood.com'
json.dump(r, open('public/hook-usage.json', 'w'), indent=1)
print(f"public/hook-usage.json · block {r['block']:,} · {r['totals']}")
PY
rm -f "$tmp"
