#!/usr/bin/env python3
"""Check every address in Aeon's public Uniswap v4 hook registry (aeonfun/univ4-hooks) against its chain.

For each hook address: the chain answers with the right chain ID, there is code at the address, the low 14 bits
match the listed flags, and a hook deployed on several chains exposes the same function selectors everywhere.

Read-only and keyless. RPCs come from Aeon's own skills/deploy-uni-hook/templates/chains.tsv (read from this
checkout, or from aeonfun/aeon main when the file is not here). Calls: eth_chainId, eth_blockNumber, eth_getCode.

Usage:
  python3 hook_registry_check.py [--state memory/state/hook-registry-check.json] [--json]

Exit codes: 0 ok (problems are reported, not an error), 2 registry or chain table unreachable (HOOK_REGISTRY_DOWN).
"""
import argparse, hashlib, json, os, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

HOOKLIST = 'https://raw.githubusercontent.com/aeonfun/univ4-hooks/main/hooklist.json'
CHAINS_TSV_URL = 'https://raw.githubusercontent.com/aeonfun/aeon/main/skills/deploy-uni-hook/templates/chains.tsv'
CHAINS_TSV_LOCAL = Path(__file__).resolve().parents[2] / 'skills/deploy-uni-hook/templates/chains.tsv'
HEADERS = {'Content-Type': 'application/json', 'User-Agent': 'aeon-hook-registry-check/1.0'}
FLAG_MASK = 0x3FFF  # v4-core Hooks.sol: permissions live in the low 14 bits of the hook address
NO_CODE_REREADS = 2


class RpcError(RuntimeError):
    pass


def fetch_text(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30).read().decode()


def post(url, body):
    reason = 'no response'
    for attempt in range(5):
        req = urllib.request.Request(url, json.dumps(body).encode(), HEADERS)
        try:
            return json.load(urllib.request.urlopen(req, timeout=40))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503, 504):
                raise RpcError(f'HTTP {e.code}') from e
            reason = f'HTTP {e.code}'
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            reason = type(e).__name__
        time.sleep(2 * (attempt + 1))
    raise RpcError(f'gave up after retries ({reason})')


def rpc(url, method, params):
    body = post(url, {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    if not isinstance(body, dict) or 'error' in body or 'result' not in body:
        raise RpcError(f"{method}: {(body or {}).get('error', 'bad response') if isinstance(body, dict) else 'bad response'}")
    return body['result']


# ---------- pure helpers (tested offline) ----------
def parse_chains_tsv(text):
    """chains.tsv rows -> {chainId: {'name', 'rpc', 'poolManager'}}. Comment and malformed lines are skipped."""
    out = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        c = line.split('\t')
        if len(c) < 6 or not c[1].strip().isdigit() or not c[5].startswith('https://'):
            continue
        out[int(c[1])] = {'name': c[0].strip(), 'rpc': c[5].strip(), 'poolManager': c[3].strip().lower()}
    return out


def registry_entries(reg):
    """hooklist.json -> one row per (hook, chain, address), sorted for stable output."""
    chains = reg.get('chains') or {}
    rows = []
    for h in reg.get('hooks') or []:
        for chain, addr in (h.get('addresses') or {}).items():
            rows.append({'hook': h.get('name') or '?', 'stage': h.get('stage'), 'chain': chain,
                         'chainId': (chains.get(chain) or {}).get('chainId'), 'address': str(addr),
                         'flags': h.get('flags')})
    return sorted(rows, key=lambda r: (r['hook'].lower(), r['chain']))


def flags_match(address, flags):
    try:
        return int(address, 16) & FLAG_MASK == int(flags, 16)
    except (TypeError, ValueError):
        return False


def split_metadata(code):
    """Runtime bytecode -> (body, solc version or None). Solidity appends CBOR metadata whose length is the last 2 bytes."""
    if len(code) < 2:
        return code, None
    n = int.from_bytes(code[-2:], 'big')
    if not 0 < n < len(code) - 2:
        return code, None
    meta = code[-(n + 2):-2]
    i = meta.find(b'dsolcC')
    solc = '.'.join(str(b) for b in meta[i + 6:i + 9]) if i >= 0 and len(meta) >= i + 9 else None
    return code[:-(n + 2)], solc


def selectors(body):
    """4-byte constants pushed by the code (PUSH4). The dispatcher pushes every external function selector."""
    found, i = set(), 0
    while i < len(body):
        op = body[i]
        if op == 0x63 and i + 5 <= len(body):
            found.add(body[i + 1:i + 5].hex())
        i += 1 + (op - 0x5f if 0x60 <= op <= 0x7f else 0)
    return found


def fingerprint(code_hex, masks=()):
    """None for no code. Otherwise size, solc, selector set and a hash of the code without metadata.

    `masks` are per-chain immutables baked into the code (the PoolManager and the hook's own address); they are
    blanked before hashing so one build deployed to two chains hashes the same."""
    raw = code_hex[2:] if isinstance(code_hex, str) and code_hex.startswith('0x') else ''
    try:
        code = bytes.fromhex(raw)
    except ValueError:
        return None
    if not code:
        return None
    body, solc = split_metadata(code)
    blanked = body
    for m in masks:
        try:
            needle = bytes.fromhex(m[2:] if m.startswith('0x') else m)
        except ValueError:
            continue
        if len(needle) == 20:
            blanked = blanked.replace(needle, b'\0' * 20)
    return {'bytes': len(code), 'solc': solc, 'selectors': sorted(selectors(body)),
            'bodyHash': hashlib.sha256(blanked).hexdigest()[:16]}


def selector_split(rows):
    """For one hook's rows with code: chains whose selector set differs from the most common one."""
    sets = {}
    for r in rows:
        if r.get('fp'):
            sets.setdefault(tuple(r['fp']['selectors']), []).append(r['chain'])
    if len(sets) < 2:
        return []
    main = max(sets.values(), key=len)
    return sorted(c for chains in sets.values() if chains is not main for c in chains)


def problems(rows):
    """Stable problem keys. RPC hiccups are left out so a flaky endpoint does not look like a registry change."""
    out = []
    for r in rows:
        key = f"{r['hook']}@{r['chain']}"
        if r['status'] == 'no-code':
            out.append(f'{key}: no code at {r["address"]}')
        elif r['status'] == 'wrong-chain':
            out.append(f'{key}: RPC answered for another chain')
        elif r['status'] == 'no-rpc':
            out.append(f'{key}: chain not in deploy-uni-hook chains.tsv, cannot be checked')
        if not r['flagsOk']:
            out.append(f'{key}: flags {r["flags"]} do not match address low 14 bits {hex(int(r["address"], 16) & FLAG_MASK)}')
    by_hook = {}
    for r in rows:
        by_hook.setdefault(r['hook'], []).append(r)
    for hook, hr in sorted(by_hook.items()):
        for chain in selector_split(hr):
            out.append(f'{hook}@{chain}: function selectors differ from the same hook on other chains')
    return sorted(out)


def to_markdown(rep):
    s = rep['summary']
    head = 'HOOK REGISTRY: CHANGES' if rep['changed'] else 'Hook registry check'
    lines = [f"{head} · {s['addresses']} addresses · {s['hooks']} hooks · {s['chains']} chains",
             f"{s['withCode']} have code · {s['noCode']} no code · {s['unchecked']} not checked · {s['flagMismatch']} flag mismatch", '']
    if rep['problems']:
        lines.append('Findings:')
        lines += [f'- {p}' for p in rep['problems']]
        lines.append('')
    if rep['newSinceLast']:
        lines.append('New since last run:')
        lines += [f'- {p}' for p in rep['newSinceLast']]
        lines.append('')
    if rep['resolvedSinceLast']:
        lines.append('Resolved since last run:')
        lines += [f'- {p}' for p in rep['resolvedSinceLast']]
        lines.append('')
    for c in rep['chains']:
        state = f"block {c['block']:,}" if c.get('block') is not None else c['status']
        lines.append(f"{c['chain']} ({c['chainId']}): {c['addresses']} address(es), {state}")
    variants = [v for v in rep['variants'] if v['variants'] > 1 and v['selectorsMatch']]
    if variants:
        lines.append('')
        lines.append('Same hook, different bytecode per chain (selectors match, so this is a build difference, not a different contract):')
        for v in variants:
            lines.append(f"- {v['hook']}: {v['variants']} builds {v['groups']}")
    lines.append('')
    lines.append('A finding is a fact about the registry entry and the chain, not a verdict on the hook.')
    return '\n'.join(lines)


# ---------- network ----------
def check_chain(chain, cid, table, rows):
    """Fill status + fingerprint for the rows of one chain, all read at one block."""
    info = table.get(cid)
    meta = {'chain': chain, 'chainId': cid, 'addresses': len(rows), 'block': None}
    if not info:
        for r in rows:
            r['status'] = 'no-rpc'
        meta['status'] = 'no RPC in chains.tsv'
        return meta
    try:
        got = int(rpc(info['rpc'], 'eth_chainId', []), 16)
        if got != cid:
            for r in rows:
                r['status'] = 'wrong-chain'
            meta['status'] = f'RPC reports chain {got}'
            return meta
        block = hex(int(rpc(info['rpc'], 'eth_blockNumber', []), 16))
        meta['block'] = int(block, 16)
        for r in rows:
            masks = (info['poolManager'], r['address'].lower())
            r['fp'] = fingerprint(rpc(info['rpc'], 'eth_getCode', [r['address'], block]), masks)
            # Load-balanced public RPCs sometimes answer '0x' once (seen on Unichain 2026-10-28); re-read before reporting.
            for _ in range(NO_CODE_REREADS):
                if r['fp']:
                    break
                time.sleep(2)
                r['fp'] = fingerprint(rpc(info['rpc'], 'eth_getCode', [r['address'], block]), masks)
            r['status'] = 'code' if r['fp'] else 'no-code'
        meta['status'] = 'ok'
    except RpcError as e:
        for r in rows:
            r.setdefault('status', 'rpc-error')
        meta['status'] = f'RPC error: {e}'[:120]
    return meta


def load_state(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def save_state(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=p.parent, delete=False) as f:
        json.dump(data, f, indent=1)
    os.replace(f.name, p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--state', help='JSON file holding the last findings; enables change detection')
    ap.add_argument('--hooklist', help='read hooklist.json from this file instead of GitHub')
    ap.add_argument('--chains-tsv', help='read chains.tsv from this file')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    log = lambda m: print(m, file=sys.stderr, flush=True)
    try:
        reg = json.loads(Path(a.hooklist).read_text()) if a.hooklist else json.loads(fetch_text(HOOKLIST))
        if a.chains_tsv:
            tsv = Path(a.chains_tsv).read_text()
        elif CHAINS_TSV_LOCAL.is_file():
            tsv = CHAINS_TSV_LOCAL.read_text()
        else:
            tsv = fetch_text(CHAINS_TSV_URL)
    except (OSError, ValueError, urllib.error.URLError) as e:
        log(f'HOOK_REGISTRY_DOWN: {type(e).__name__}: {e}'[:200])
        return 2
    table = parse_chains_tsv(tsv)
    rows = registry_entries(reg)
    if not rows or not table:
        log('HOOK_REGISTRY_DOWN: empty registry or chain table')
        return 2
    for r in rows:
        r['flagsOk'] = flags_match(r['address'], r['flags'])
    chains_meta = []
    for chain in sorted({r['chain'] for r in rows}):
        cr = [r for r in rows if r['chain'] == chain]
        chains_meta.append(check_chain(chain, cr[0]['chainId'], table, cr))

    found = problems(rows)
    prev = load_state(a.state) if a.state else None
    before = set(prev.get('problems', [])) if prev else set()
    new, resolved = sorted(set(found) - before), sorted(before - set(found))
    variants = []
    for hook in sorted({r['hook'] for r in rows}, key=str.lower):
        groups, sels = {}, set()
        for r in rows:
            if r['hook'] == hook and r.get('fp'):
                groups.setdefault(r['fp']['bodyHash'], []).append(r['chain'])
                sels.add(tuple(r['fp']['selectors']))
        if groups:
            variants.append({'hook': hook, 'variants': len(groups), 'groups': sorted(groups.values()), 'selectorsMatch': len(sels) == 1})
    rep = {
        'summary': {'addresses': len(rows), 'hooks': len({r['hook'] for r in rows}), 'chains': len(chains_meta),
                    'withCode': sum(r['status'] == 'code' for r in rows), 'noCode': sum(r['status'] == 'no-code' for r in rows),
                    'unchecked': sum(r['status'] not in ('code', 'no-code') for r in rows),
                    'flagMismatch': sum(not r['flagsOk'] for r in rows)},
        'problems': found, 'newSinceLast': new if prev else [], 'resolvedSinceLast': resolved if prev else [],
        'changed': prev is None or bool(new or resolved),
        'chains': chains_meta, 'variants': variants,
        'addresses': [{k: r.get(k) for k in ('hook', 'stage', 'chain', 'chainId', 'address', 'status', 'flagsOk')} |
                      {'solc': (r.get('fp') or {}).get('solc'), 'bytes': (r.get('fp') or {}).get('bytes')} for r in rows],
    }
    if a.state:
        save_state(a.state, {'problems': found, 'checkedAt': int(time.time())})
    print(json.dumps(rep, indent=1) if a.json else to_markdown(rep))
    return 0


if __name__ == '__main__':
    sys.exit(main())
