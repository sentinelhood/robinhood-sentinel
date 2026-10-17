#!/usr/bin/env python3
"""Measure real usage of Aeon's Uniswap v4 hooks on Robinhood Chain (chain ID 4663).

Read-only and keyless. Data sources:
  - aeonfun/univ4-hooks hooklist.json (which hooks exist, and their Robinhood addresses)
  - the official public RPC, via eth_blockNumber and eth_getLogs only

Usage:
  python3 hook_usage.py --state memory/state/hook-usage.json [--days 7] [--json]

The state file caches the pools found so far plus the last block scanned. The first
run backfills from the first registry date; later runs only scan new blocks.
"""
import argparse, json, sys, time, urllib.error, urllib.request
from pathlib import Path

RPC = 'https://rpc.mainnet.chain.robinhood.com'
HOOKLIST = 'https://raw.githubusercontent.com/aeonfun/univ4-hooks/main/hooklist.json'
CHAIN_ID = 4663
# Uniswap v4 PoolManager on Robinhood Chain, same value as deploy-uni-hook/templates/chains.tsv.
POOL_MANAGER = '0x8366a39cc670b4001a1121b8f6a443a643e40951'
# keccak256 of the v4 PoolManager event signatures.
INITIALIZE = '0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438'
SWAP = '0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f'
BACKFILL_FROM = 22_000_000  # 2026-07-28, before the earliest Robinhood hook in the registry
INIT_STEP = 1_000_000       # RPC allows 10M blocks / 10k logs per single-address query
SWAP_STEP = 100_000         # RPC allows 100k blocks when a topic slot is an OR-list
SEC_PER_BLOCK = 0.102
HEADERS = {'Content-Type': 'application/json', 'User-Agent': 'aeon-hook-usage/1.0'}


class RpcError(RuntimeError):
    pass


def rpc(method, params):
    for attempt in range(8):
        req = urllib.request.Request(RPC, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode(), HEADERS)
        try:
            body = json.load(urllib.request.urlopen(req, timeout=90))
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504):
                time.sleep(min(30, 3 * (attempt + 1)))
                continue
            raise RpcError(f'{method}: HTTP {e.code}') from e
        except (urllib.error.URLError, TimeoutError):
            time.sleep(min(30, 3 * (attempt + 1)))
            continue
        if 'error' in body:
            raise RpcError(f"{method}: {body['error'].get('message', body['error'])}")
        return body['result']
    raise RpcError(f'{method}: gave up after retries')


def get_logs(topics, lo, hi):
    """eth_getLogs on the PoolManager, halving the range whenever the 10k-log cap is hit."""
    try:
        return rpc('eth_getLogs', [{'address': POOL_MANAGER, 'topics': topics, 'fromBlock': hex(lo), 'toBlock': hex(hi)}])
    except RpcError as e:
        if 'exceeds limit' not in str(e) or hi <= lo:
            raise
        mid = (lo + hi) // 2
        return get_logs(topics, lo, mid) + get_logs(topics, mid + 1, hi)


def hook_from_initialize(data):
    """Initialize data = fee, tickSpacing, hooks, sqrtPriceX96, tick (5 words). Return hooks address."""
    raw = data[2:] if data.startswith('0x') else data
    if len(raw) != 5 * 64:
        raise ValueError(f'Initialize data must be 5 words, got {len(raw) / 64:g}')
    return '0x' + raw[2 * 64: 3 * 64][-40:].lower()


def load_registry(fetch=None):
    fetch = fetch or (lambda url: json.load(urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30)))
    reg = fetch(HOOKLIST)
    hooks = {}
    for h in reg.get('hooks', []):
        addr = (h.get('addresses') or {}).get('robinhood')
        if addr:
            hooks[addr.lower()] = {'name': h['name'], 'stage': h.get('stage'), 'date': h.get('date'),
                                   'flagsMatch': (int(addr, 16) & 0x3FFF) == int(h.get('flags', '0x0'), 16)}
    return hooks


def scan_pools(state, hooks, head, log=print):
    lo = state.get('lastBlock', BACKFILL_FROM - 1) + 1
    pools = state.setdefault('pools', {})
    while lo <= head:
        hi = min(lo + INIT_STEP - 1, head)
        for entry in get_logs([INITIALIZE], lo, hi):
            hook = hook_from_initialize(entry['data'])
            if hook in hooks:
                pools[entry['topics'][1]] = {'hook': hook, 'block': int(entry['blockNumber'], 16)}
        state['lastBlock'] = hi
        lo = hi + 1
        log(f'  scanned to block {hi:,} ({len(pools)} hooked pools)')
        time.sleep(0.25)
    return pools


def scan_swaps(pool_ids, head, days, log=print):
    swaps, senders = {}, {}
    if not pool_ids:
        return swaps, senders
    start = max(0, head - int(days * 86400 / SEC_PER_BLOCK))
    ids = sorted(pool_ids)
    for chunk in (ids[i:i + 50] for i in range(0, len(ids), 50)):
        for lo in range(start, head + 1, SWAP_STEP):
            for entry in get_logs([SWAP, chunk], lo, min(lo + SWAP_STEP - 1, head)):
                pid = entry['topics'][1]
                swaps[pid] = swaps.get(pid, 0) + 1
                senders.setdefault(pid, set()).add(entry['topics'][2])
            time.sleep(0.2)
    log(f'  swaps in the last {days:g} days: {sum(swaps.values())}')
    return swaps, senders


def build_report(hooks, pools, swaps, senders, head, days):
    rows = []
    for addr, meta in hooks.items():
        mine = [pid for pid, p in pools.items() if p['hook'] == addr]
        who = set().union(*(senders.get(pid, set()) for pid in mine)) if mine else set()
        rows.append({'hook': meta['name'], 'address': addr, 'stage': meta['stage'], 'flagsMatch': meta['flagsMatch'],
                     'pools': len(mine), 'activePools': sum(1 for pid in mine if swaps.get(pid)),
                     'swaps': sum(swaps.get(pid, 0) for pid in mine), 'uniqueSenders': len(who)})
    rows.sort(key=lambda r: (-r['swaps'], -r['pools'], r['hook']))
    return {'chainId': CHAIN_ID, 'block': head, 'windowDays': days, 'hooks': rows,
            'totals': {'hooks': len(rows), 'hooksWithPools': sum(1 for r in rows if r['pools']),
                       'pools': sum(r['pools'] for r in rows), 'swaps': sum(r['swaps'] for r in rows)}}


def to_markdown(report):
    t = report['totals']
    lines = [f"Aeon hooks on Robinhood Chain · block {report['block']:,}",
             f"{t['hooksWithPools']}/{t['hooks']} hooks have pools · {t['pools']} pools · {t['swaps']} swaps in {report['windowDays']:g}d", '']
    for r in report['hooks']:
        flag = '' if r['flagsMatch'] else '  (!) flag bits mismatch'
        lines.append(f"• {r['hook']}: {r['pools']} pools, {r['activePools']} active, {r['swaps']} swaps, {r['uniqueSenders']} callers{flag}")
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--state', default='memory/state/hook-usage.json')
    ap.add_argument('--days', type=float, default=7)
    ap.add_argument('--json', action='store_true', help='print the JSON report instead of markdown')
    args = ap.parse_args(argv)
    log = lambda m: print(m, file=sys.stderr, flush=True)

    state_path = Path(args.state)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    hooks = load_registry()
    if not hooks:
        log('HOOK_USAGE_NO_HOOKS: registry lists no Robinhood Chain hooks')
        return 0
    if int(rpc('eth_chainId', []), 16) != CHAIN_ID:
        log('HOOK_USAGE_RPC_DOWN: unexpected chain ID')
        return 2
    head = int(rpc('eth_blockNumber', []), 16)
    pools = scan_pools(state, hooks, head, log)
    swaps, senders = scan_swaps(set(pools), head, args.days, log)
    report = build_report(hooks, pools, swaps, senders, head, args.days)

    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state))
    tmp.replace(state_path)
    print(json.dumps(report, indent=1) if args.json else to_markdown(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
