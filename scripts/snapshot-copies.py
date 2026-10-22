#!/usr/bin/env python3
"""Snapshot of Pons v2 tokens that copy the $SNTL ticker or name, for public/copies.json.

Read-only and keyless. Runs the pons-launch-watch skill (the same helper Aeon operators
install) to update its cached view of the last 24 hours of launches, then lists every
launch in that window whose symbol or name normalises to SNTL or Sentinel and whose
address is not the official token.

Run: python3 scripts/snapshot-copies.py [state-file]
Only replaces public/copies.json after the skill run succeeds.
"""
import json, os, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills' / 'pons-launch-watch'))
import pons_launch_watch as plw  # noqa: E402

OFFICIAL = '0x2da80b9D1bc1B323693C80C76eb4a321ec08CbD0'
WATCH = ['SNTL', 'Sentinel']
HOURS = 24


def main():
    state = Path(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/.cache/sentinel/pons-launch-watch.json'))
    state.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run([sys.executable, str(ROOT / 'skills/pons-launch-watch/pons_launch_watch.py'),
                          '--state', str(state), '--hours', str(HOURS), '--json'], capture_output=True, text=True)
    if run.returncode != 0:
        sys.stderr.write(run.stderr)
        return run.returncode or 1
    report = json.loads(run.stdout)
    assert report['chainId'] == 4663 and report['launches'] > 0, 'refusing to publish an empty or wrong-chain report'
    seen = [dict(zip(plw.SEEN_KEYS, row)) for row in json.loads(state.read_text())['seen']]
    copies = sorted(plw.find_lookalikes(seen, WATCH, {OFFICIAL.lower()}), key=lambda h: -h['block'])
    out = {
        'chainId': 4663, 'official': OFFICIAL, 'watch': WATCH, 'windowHours': HOURS, 'block': report['block'],
        'generatedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'launches': report['launches'], 'sharedTickerLaunches': report['sharedTickerLaunches'],
        'copies': [{k: c[k] for k in ('token', 'deployer', 'block', 'symbol', 'name', 'matched', 'field')} for c in copies[:20]],
        'copyCount': len(copies),
        'source': 'skills/pons-launch-watch/pons_launch_watch.py via rpc.mainnet.chain.robinhood.com',
    }
    target = ROOT / 'public' / 'copies.json'
    with tempfile.NamedTemporaryFile('w', dir=target.parent, delete=False) as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write('\n')
    os.replace(f.name, target)
    print(f"public/copies.json · block {out['block']:,} · {out['copyCount']} copies in {out['launches']:,} launches")
    return 0


if __name__ == '__main__':
    sys.exit(main())
