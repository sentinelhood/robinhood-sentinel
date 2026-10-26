#!/usr/bin/env python3
"""Snapshot of the busiest Pons v2 bonding curves, for public/movers.json.

Read-only and keyless. Runs the pons-curve-movers skill (the same helper Aeon operators install)
and keeps only the fields the site shows. Quote amounts stay as integer strings, so nothing above
2^53 passes through a JavaScript number.

Run: python3 scripts/snapshot-movers.py [hours] [top]
Only replaces public/movers.json after the skill run succeeds and the result checks out.
"""
import json, os, re, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDRESS = re.compile(r'^0x[0-9a-f]{40}$')


def text(x):
    return x if isinstance(x, str) and 0 < len(x) <= 64 else None


def main():
    hours = float(sys.argv[1]) if len(sys.argv) > 1 else 6
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    run = subprocess.run([sys.executable, str(ROOT / 'skills/pons-curve-movers/pons_curve_movers.py'),
                          '--hours', str(hours), '--top', str(top), '--json'], capture_output=True, text=True)
    if run.returncode != 0:
        sys.stderr.write(run.stderr)
        return run.returncode or 1
    r = json.loads(run.stdout)
    assert r['chainId'] == 4663 and r['trades'] > 0 and r['movers'], 'refusing to publish an empty or wrong-chain report'
    movers = []
    for m in r['movers']:
        assert ADDRESS.match(m['token']) and ADDRESS.match(m['curve']) and ADDRESS.match(m['pairToken']), 'bad address'
        movers.append({
            'token': m['token'], 'symbol': text(m.get('symbol')), 'name': text(m.get('name')),
            'buys': int(m['buys']), 'sells': int(m['sells']), 'traders': int(m['traders']),
            'volumeRaw': str(int(m['volume'])), 'netRaw': str(int(m['net'])),
            'pairSymbol': text(m.get('pairSymbol')), 'pairDecimals': m.get('pairDecimals'),
            'phase': int(m['phase']), 'progress': m.get('progress'),
        })
    out = {
        'chainId': 4663, 'block': r['block'], 'windowHours': r['windowHours'],
        'generatedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'trades': r['trades'], 'curves': r['curves'], 'skipped': r['skipped'], 'movers': movers,
        'source': 'skills/pons-curve-movers/pons_curve_movers.py via rpc.mainnet.chain.robinhood.com',
    }
    target = ROOT / 'public' / 'movers.json'
    with tempfile.NamedTemporaryFile('w', dir=target.parent, delete=False) as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write('\n')
    os.replace(f.name, target)
    print(f"public/movers.json · block {out['block']:,} · {out['trades']:,} trades on {out['curves']:,} curves · top {len(movers)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
