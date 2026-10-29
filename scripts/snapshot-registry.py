#!/usr/bin/env python3
"""Snapshot of Aeon's Uniswap v4 hook registry checked on chain, for public/registry.json.

Read-only and keyless. Runs the hook-registry-check skill (the same helper Aeon operators install) and keeps
only the fields the site shows. Only replaces public/registry.json after the run succeeds and checks out.

Run: python3 scripts/snapshot-registry.py
"""
import json, os, re, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')
STATUSES = {'code', 'no-code', 'no-rpc', 'wrong-chain', 'rpc-error'}


def main():
    run = subprocess.run([sys.executable, str(ROOT / 'skills/hook-registry-check/hook_registry_check.py'), '--json'],
                         capture_output=True, text=True, timeout=900)
    if run.returncode != 0:
        sys.stderr.write(run.stderr)
        return run.returncode or 1
    r = json.loads(run.stdout)
    s = r['summary']
    rows = r['addresses']
    assert rows and s['addresses'] == len(rows), 'refusing to publish an empty or inconsistent report'
    hooks = {}
    for a in rows:
        assert ADDRESS.match(a['address']) and a['status'] in STATUSES, f"bad row {a['hook']}@{a['chain']}"
        hooks.setdefault(a['hook'], {'hook': a['hook'], 'stage': a['stage'], 'chains': []})['chains'].append(
            {'chain': a['chain'], 'address': a['address'].lower(), 'status': a['status'], 'flagsOk': bool(a['flagsOk'])})
    builds = {v['hook']: v['variants'] for v in r['variants']}
    split = {p.split('@')[0] for p in r['problems'] if 'function selectors differ' in p}
    out = {
        'generatedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'summary': {k: s[k] for k in ('addresses', 'hooks', 'chains', 'withCode', 'noCode', 'unchecked', 'flagMismatch')},
        'chains': [{'chain': c['chain'], 'chainId': c['chainId'], 'addresses': c['addresses'], 'block': c['block'],
                    'checked': c['block'] is not None} for c in r['chains']],
        'hooks': [dict(h, builds=builds.get(h['hook'], 0), selectorsMatch=h['hook'] not in split)
                  for h in sorted(hooks.values(), key=lambda h: h['hook'].lower())],
        'problems': r['problems'],
        'source': 'skills/hook-registry-check/hook_registry_check.py · RPCs from aeonfun/aeon deploy-uni-hook chains.tsv',
    }
    target = ROOT / 'public' / 'registry.json'
    with tempfile.NamedTemporaryFile('w', dir=target.parent, delete=False) as f:
        json.dump(out, f, indent=1)
        f.write('\n')
    os.replace(f.name, target)
    print(f"public/registry.json · {s['addresses']} addresses · {s['withCode']} with code · {s['unchecked']} not checked")
    return 0


if __name__ == '__main__':
    sys.exit(main())
