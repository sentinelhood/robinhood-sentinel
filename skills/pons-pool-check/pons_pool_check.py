#!/usr/bin/env python3
"""Which Uniswap v4 pool is a Pons v2 token's official one, and which other v4 pools exist for the same token.

Anyone can create a Uniswap v4 pool for any token, with any fee. After a Pons token graduates, its locked pool sits
next to pools other people made: on 2026-11-05, every one of the 13 tokens that graduated in the previous 24 hours
had other v4 pools, 137 in total, most with no hook and swap fees from 10% to 99.9%. A router or wallet that picks a
pool by token pair alone can route a buyer into one of those.

The official pool is identified from chain, not from a list: it is the pool whose PoolKey uses the Pons meme hook,
the factory's recorded poolFee and tickSpacing, and the token with its recorded pair token. Read-only and keyless.
Data source: the official public RPC (eth_chainId, eth_blockNumber, eth_getLogs on the v4 PoolManager, eth_call on
the Pons v2 factory, the v4 StateView and the token).

Usage:
  python3 pons_pool_check.py <token-address> [--json]

Exit codes: 0 ok, 2 RPC unreachable or wrong chain (PONS_POOL_RPC_DOWN), 3 bad input or not a Pons v2 token (PONS_POOL_BAD_TARGET).
"""
import argparse, json, re, sys, time, urllib.error, urllib.request

RPC = 'https://rpc.mainnet.chain.robinhood.com'
CHAIN_ID = 4663
FACTORY = '0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e'      # Pons v2, docs.ponsfamily.com/v2#contracts
MEME_HOOK = '0xe5e702641ea86f4ae6cc3cdaed2b886f976be044'    # Pons v2 meme hook, same page
POOL_MANAGER = '0x8366a39cc670b4001a1121b8f6a443a643e40951'  # Uniswap v4, Aeon deploy-uni-hook chains.tsv
STATE_VIEW = '0xf3334192d15450cdd385c8b70e03f9a6bd9e673b'    # Uniswap v4 StateView, same row
# Event topics and selectors, checked against 4byte.directory on 2026-11-05.
INITIALIZE = '0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438'  # Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)
SWAP = '0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f'        # Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)
GET_LAUNCHED, GET_LIQUIDITY, SYMBOL = '0x3cf28b5a', '0xfa6793d5', '0x95d89b41'
PHASE = ['bonding curve', 'swept, pool pending', 'Uniswap v4 pool, liquidity locked', 'rescued (recovery path)']
ZERO = '0x' + '0' * 40
DYNAMIC_FEE = 0x800000      # v4 LPFeeLibrary: fee field flag for a hook-set dynamic fee
SPAN = 9_900_000            # the RPC allows 10M blocks per filtered eth_getLogs
SWAP_STEP = 100_000         # and 100k when a topic slot is an OR-list
SWAP_WINDOW_H = 24
SEC_PER_BLOCK = 0.102
HEADERS = {'Content-Type': 'application/json', 'User-Agent': 'aeon-pons-pool-check/1.0'}
ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')


class RpcError(RuntimeError):
    pass


def post(body):
    reason = 'no response'
    for attempt in range(6):
        req = urllib.request.Request(RPC, json.dumps(body).encode(), HEADERS)
        try:
            data = json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503, 504):
                raise RpcError(f'HTTP {e.code}') from e
            reason = f'HTTP {e.code}'
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
            reason = type(e).__name__
        else:
            if isinstance(data, dict) and (data.get('error') or {}).get('code') == 429:
                reason = 'rate limited'
            else:
                return data
        time.sleep(1.5 * (attempt + 1))
    raise RpcError(f'gave up after retries ({reason})')


def rpc(method, params):
    body = post({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    if not isinstance(body, dict) or 'error' in body or 'result' not in body:
        raise RpcError(f"{method}: {body.get('error') if isinstance(body, dict) else 'bad response'}")
    return body['result']


# ---------- pure helpers (tested offline) ----------
def words(hexdata):
    raw = hexdata[2:] if isinstance(hexdata, str) and hexdata.startswith('0x') else ''
    if not re.fullmatch(r'(?:[0-9a-fA-F]{64})*', raw):
        return []
    return [raw[i:i + 64] for i in range(0, len(raw), 64)]


def signed24(word):
    v = int(word, 16) & 0xFFFFFF
    return v - (1 << 24) if v & 0x800000 else v


def decode_record(hexdata):
    """getLaunchedToken -> the fields that build the official PoolKey. None if unknown or malformed."""
    w = words(hexdata)
    if len(w) != 15 or int(w[14], 16) != 1:
        return None
    a = lambda x: '0x' + x[24:].lower()
    return {'token': a(w[0]), 'deployer': a(w[2]), 'pairToken': a(w[4]), 'poolFee': int(w[6], 16) & 0xFFFFFF,
            'tickSpacing': signed24(w[7]), 'phase': int(w[10], 16)}


def parse_initialize(log):
    """A PoolManager Initialize log -> pool. None for anything else."""
    t = log.get('topics') or []
    w = words(log.get('data'))
    if len(t) != 4 or str(t[0]).lower() != INITIALIZE or len(w) < 3 or log.get('removed'):
        return None
    try:
        return {'poolId': str(t[1]).lower(), 'currency0': '0x' + str(t[2])[-40:].lower(), 'currency1': '0x' + str(t[3])[-40:].lower(),
                'fee': int(w[0], 16) & 0xFFFFFF, 'tickSpacing': signed24(w[1]), 'hooks': '0x' + w[2][-40:].lower(),
                'block': int(log['blockNumber'], 16), 'tx': str(log.get('transactionHash', '')).lower()}
    except (KeyError, ValueError, TypeError):
        return None


def is_official(pool, record):
    """The Pons PoolKey: meme hook, recorded fee and spacing, and exactly {token, pairToken} as the currencies."""
    pair = sorted([record['token'], record['pairToken']])
    return (pool['hooks'] == MEME_HOOK and pool['fee'] == record['poolFee'] and pool['tickSpacing'] == record['tickSpacing']
            and [pool['currency0'], pool['currency1']] == pair)


def fee_label(fee):
    return 'dynamic (set by its hook)' if fee & DYNAMIC_FEE else f'{fee / 10_000:g}%'


def classify(pools, record):
    official = [p for p in pools if is_official(p, record)]
    others = sorted((p for p in pools if not is_official(p, record)), key=lambda p: (-p.get('swaps', 0), p['block']))
    return official, others


def to_markdown(r):
    lines = [f"*Pons Pool Check: {r.get('symbol') or '?'}* `{r['token']}` · Robinhood Chain 4663 · block {r['block']:,}",
             f"Phase: {r['phaseLabel']}", '']
    o = r['official']
    if o:
        lines.append(f"Official Pons pool: `{o['poolId']}`")
        lines.append(f"  hook = Pons meme hook · pool fee {fee_label(o['fee'])} (the hook charges the Pons fee) · "
                     f"liquidity {'locked, non-zero' if o['liquidity'] else 'zero'} · {o['swaps']} swaps in {r['windowHours']}h")
    elif r['phase'] == 0:
        lines.append('No official pool yet: the token still trades on its Pons bonding curve. Buy and sell there.')
    else:
        lines.append('No pool matches the factory record. Treat any v4 pool for this token with care.')
    lines.append('')
    others = r['others']
    if not others:
        lines.append('No other Uniswap v4 pools for this token.')
    else:
        lines.append(f"Other Uniswap v4 pools for this token: {len(others)} (made by anyone, not by Pons)")
        nohook = sum(p['hooks'] == ZERO for p in others)
        high = sum(not p['fee'] & DYNAMIC_FEE and p['fee'] >= 100_000 for p in others)
        if nohook or high:
            lines.append(f"  {nohook} with no hook · {high} with a pool fee of 10% or more")
        for p in others[:r['top']]:
            lines.append(f"- `{p['poolId'][:18]}…` fee {fee_label(p['fee'])} · hook {'none' if p['hooks'] == ZERO else p['hooks']} · "
                         f"pair {r['pairLabels'].get(p['currency0'] if p['currency1'] == r['token'] else p['currency1'], '?')} · "
                         f"liquidity {'non-zero' if p['liquidity'] else 'zero'} · {p['swaps']} swaps in {r['windowHours']}h")
        if len(others) > r['top']:
            lines.append(f"- +{len(others) - r['top']} more")
    lines += ['', 'The official pool is the one built from the Pons factory record and its meme hook. Check the pool id your '
              'wallet or router uses. Read-only facts, not a price signal or a safety verdict.']
    return '\n'.join(lines)


# ---------- network ----------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('token')
    ap.add_argument('--top', type=int, default=8)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    log = lambda m: print(m, file=sys.stderr, flush=True)
    if not ADDRESS.match(a.token) or not 1 <= a.top <= 50:
        log('PONS_POOL_BAD_TARGET: token must be 0x + 40 hex, --top 1-50')
        return 3
    token = a.token.lower()
    try:
        if int(rpc('eth_chainId', []), 16) != CHAIN_ID:
            log('PONS_POOL_RPC_DOWN: unexpected chain ID')
            return 2
        head = int(rpc('eth_blockNumber', []), 16)
        block = hex(head)
        record = decode_record(rpc('eth_call', [{'to': FACTORY, 'data': GET_LAUNCHED + token[2:].rjust(64, '0')}, block]))
        if not record:
            log('PONS_POOL_BAD_TARGET: not a Pons v2 token (the factory has no record for it)')
            return 3
        pools = []
        for slot in (2, 3):
            topics = [INITIALIZE, None, None, None]
            topics[slot] = '0x' + token[2:].rjust(64, '0')
            for lo in range(max(0, head - 3 * SPAN), head + 1, SPAN):
                pools += [p for p in map(parse_initialize, rpc('eth_getLogs', [{'address': POOL_MANAGER, 'topics': topics,
                          'fromBlock': hex(lo), 'toBlock': hex(min(lo + SPAN - 1, head))}])) if p]
        pools = list({p['poolId']: p for p in pools}.values())
        since = max(0, head - int(SWAP_WINDOW_H * 3600 / SEC_PER_BLOCK))
        counts = {}
        ids = [p['poolId'] for p in pools]
        for i in range(0, len(ids), 40):
            chunk = ids[i:i + 40]
            for lo in range(since, head + 1, SWAP_STEP):
                for s in rpc('eth_getLogs', [{'address': POOL_MANAGER, 'topics': [SWAP, chunk], 'fromBlock': hex(lo),
                                              'toBlock': hex(min(lo + SWAP_STEP - 1, head))}]):
                    pid = str(s['topics'][1]).lower()
                    counts[pid] = counts.get(pid, 0) + 1
        for p in pools:
            p['swaps'] = counts.get(p['poolId'], 0)
            p['liquidity'] = int(rpc('eth_call', [{'to': STATE_VIEW, 'data': GET_LIQUIDITY + p['poolId'][2:]}, block]), 16)
        pairs = {c for p in pools for c in (p['currency0'], p['currency1']) if c != token}
        labels = {ZERO: 'ETH'}
        for c in pairs - {ZERO}:
            w = words(rpc('eth_call', [{'to': c, 'data': SYMBOL}, block]))
            if len(w) >= 3 and int(w[0], 16) == 32:
                labels[c] = bytes.fromhex(''.join(w[2:]))[:int(w[1], 16)].decode('utf-8', 'replace')[:16] or c[:10]
            else:
                labels[c] = c[:10]
        sym = words(rpc('eth_call', [{'to': token, 'data': SYMBOL}, block]))
        symbol = bytes.fromhex(''.join(sym[2:]))[:int(sym[1], 16)].decode('utf-8', 'replace')[:32] if len(sym) >= 3 else None
    except RpcError as e:
        log(f'PONS_POOL_RPC_DOWN: {e}')
        return 2
    official, others = classify(pools, record)
    ph = record['phase']
    report = {'chainId': CHAIN_ID, 'block': head, 'token': token, 'symbol': symbol, 'phase': ph,
              'phaseLabel': PHASE[ph] if 0 <= ph < len(PHASE) else f'phase {ph}', 'windowHours': SWAP_WINDOW_H, 'top': a.top,
              'official': official[0] if official else None, 'others': others, 'pairLabels': labels,
              'expected': {'hooks': MEME_HOOK, 'fee': record['poolFee'], 'tickSpacing': record['tickSpacing'], 'pairToken': record['pairToken']}}
    print(json.dumps(report, indent=1) if a.json else to_markdown(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
