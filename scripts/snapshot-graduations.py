#!/usr/bin/env python3
"""Snapshot of Pons v2 graduations in the last 24 hours, for public/graduations.json.

Read-only and keyless. Runs the pons-graduation-watch skill (the same helper Aeon operators install) with a
throwaway state file, so it lists every graduation in the window, not only new ones. Quote amounts stay
integer strings, so nothing above 2^53 passes through a JavaScript number.

Run: python3 scripts/snapshot-graduations.py [hours]
Only replaces public/graduations.json after the skill run succeeds and the result checks out.
"""
import json, os, re, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDRESS = re.compile(r'^0x[0-9a-f]{40}$')
TX = re.compile(r'^0x[0-9a-f]{64}$')
MAX_LISTED = 20


def text(x):
    return x if isinstance(x, str) and 0 < len(x) <= 64 else None


POOL_ID = re.compile(r'^0x[0-9a-f]{64}$')
DYNAMIC_FEE = 0x800000


def pools(token):
    """pons-pool-check for one token -> counts for the site. None when the check fails, so a flaky read never shows as 0."""
    try:
        run = subprocess.run([sys.executable, str(ROOT / 'skills/pons-pool-check/pons_pool_check.py'), token, '--json'],
                             capture_output=True, text=True, timeout=180)
        if run.returncode != 0:
            return None
        r = json.loads(run.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        return None
    o, others = r.get('official'), r.get('others') or []
    if o is not None and not POOL_ID.match(str(o.get('poolId', ''))):
        return None
    fixed = [p['fee'] for p in others if not p['fee'] & DYNAMIC_FEE]
    return {'official': o['poolId'] if o else None, 'officialSwaps': int(o['swaps']) if o else 0,
            'others': len(others), 'othersHalfFee': sum(f >= 500_000 for f in fixed),
            'othersSwaps': sum(int(p['swaps']) for p in others)}


def main():
    hours = float(sys.argv[1]) if len(sys.argv) > 1 else 24
    with tempfile.TemporaryDirectory() as d:
        run = subprocess.run([sys.executable, str(ROOT / 'skills/pons-graduation-watch/pons_graduation_watch.py'),
                              '--state', str(Path(d) / 'state.json'), '--hours', str(hours), '--json'],
                             capture_output=True, text=True)
    if run.returncode != 0:
        sys.stderr.write(run.stderr)
        return run.returncode or 1
    r = json.loads(run.stdout)
    assert r['chainId'] == 4663 and r['launches'] > 0, 'refusing to publish an empty or wrong-chain report'
    assert len(r['new']) == r['graduations'], 'a first run must list every graduation in the window'
    rows = []
    for g in sorted(r['new'], key=lambda g: -g['block'])[:MAX_LISTED]:
        assert ADDRESS.match(g['token']) and TX.match(g['tx']), 'bad address or tx'
        dep, pair = g.get('deployer'), g.get('pairToken')
        rows.append({
            'token': g['token'], 'symbol': text(g.get('symbol')), 'name': text(g.get('name')),
            'deployer': dep if isinstance(dep, str) and ADDRESS.match(dep) else None,
            'block': int(g['block']), 'tx': g['tx'],
            'quoteRaw': str(int(g['quoteRaw'])), 'pairSymbol': text(g.get('pairSymbol')), 'pairDecimals': g.get('pairDecimals'),
            'phase': g.get('phase') if isinstance(g.get('phase'), int) else None,
            'pools': pools(g['token']),
        })
    out = {
        'chainId': 4663, 'block': r['block'], 'windowHours': r['windowHours'],
        'generatedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'launches': r['launches'], 'graduations': r['graduations'], 'graduated': rows,
        'source': 'skills/pons-graduation-watch/pons_graduation_watch.py via rpc.mainnet.chain.robinhood.com',
    }
    target = ROOT / 'public' / 'graduations.json'
    with tempfile.NamedTemporaryFile('w', dir=target.parent, delete=False) as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write('\n')
    os.replace(f.name, target)
    print(f"public/graduations.json · block {out['block']:,} · {out['graduations']} graduated of {out['launches']:,} launches in {hours:g}h")
    return 0


if __name__ == '__main__':
    sys.exit(main())
