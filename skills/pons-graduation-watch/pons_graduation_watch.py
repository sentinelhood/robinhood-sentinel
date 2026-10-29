#!/usr/bin/env python3
"""Alert when a Pons v2 token graduates from its bonding curve to a locked Uniswap v4 pool on
Robinhood Chain (chain ID 4663), plus the graduation rate for the window.

Read-only and keyless. Data source: the official public RPC, via eth_chainId, eth_blockNumber,
eth_getLogs (graduation and TokenLaunched events on the Pons v2 factory) and eth_call
(getLaunchedToken for phase, deployer and pair; name() / symbol() / decimals()).

Usage:
  python3 pons_graduation_watch.py --state memory/state/pons-graduation-watch.json \
      [--watch 0xTOKEN,0xDEPLOYER] [--hours 24] [--json]

Without --watch every new graduation is reported. With --watch only graduations of a listed token,
or of a token made by a listed deployer, are reported. Each graduation is reported once.

Exit codes: 0 ok, 2 RPC unreachable or wrong chain (PONS_GRAD_RPC_DOWN),
3 bad input (PONS_GRAD_BAD_WATCH).
"""
import argparse, json, re, sys, time, unicodedata, urllib.error, urllib.request
import http.client
from pathlib import Path

RPC = 'https://rpc.mainnet.chain.robinhood.com'
CHAIN_ID = 4663
FACTORY = '0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e'  # Pons v2, docs.ponsfamily.com/v2#contracts
TOKEN_LAUNCHED = '0x8d4aad4953d0ca700d468f3753aa14432d1b35b43ec6409f051fb6aa43a89607'
# Emitted by the factory when a curve graduates: topic1 = token, data = (quote into pool, tokens into pool).
# Verified 2026-10-25: all 21 tokens that emitted it in the prior ~2.8 days read phase 2 from getLaunchedToken.
GRADUATED = '0xcdb72f157fd3666758a6ce201387ffb52038c7562e4fff352828da1096c4b6b4'
GET_LAUNCHED, NAME, SYMBOL, DECIMALS = '0x3cf28b5a', '0x06fdde03', '0x95d89b41', '0x313ce567'
PHASE = ['bonding curve', 'swept, pool pending', 'Uniswap v4 pool, liquidity locked', 'rescued (recovery path)']
ZERO = '0x' + '0' * 40
SEC_PER_BLOCK = 0.102
LOG_STEP = 1_000_000   # address + topic filter: the public RPC allows up to 10M blocks / 10k logs
BATCH = 50
MAX_LISTED = 10
ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')
HEADERS = {'Content-Type': 'application/json', 'User-Agent': 'aeon-pons-graduation-watch/1.0'}
EXPLORER = 'https://robinhoodchain.blockscout.com'


class RpcError(RuntimeError):
    pass


def post(body):
    for attempt in range(6):
        req = urllib.request.Request(RPC, json.dumps(body).encode(), HEADERS)
        try:
            data = json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RpcError(f'HTTP {e.code}') from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            time.sleep(1.5 * (attempt + 1))
            continue
        if isinstance(data, dict) and (data.get('error') or {}).get('code') == 429:
            time.sleep(1.5 * (attempt + 1))
            continue
        return data
    raise RpcError('gave up after retries')


def rpc(method, params):
    body = post({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    if 'error' in body:
        raise RpcError(f"{method}: {body['error'].get('message', body['error'])}")
    return body['result']


def get_logs(topic, lo, hi):
    """Factory logs for one topic in [lo, hi], halving the range whenever the 10k-log cap is hit."""
    try:
        return rpc('eth_getLogs', [{'address': FACTORY, 'topics': [topic], 'fromBlock': hex(lo), 'toBlock': hex(hi)}])
    except RpcError as e:
        if 'exceeds limit' not in str(e) or hi <= lo:
            raise
        mid = (lo + hi) // 2
        return get_logs(topic, lo, mid) + get_logs(topic, mid + 1, hi)


def scan(topic, start, head):
    out = []
    for lo in range(start, head + 1, LOG_STEP):
        out += get_logs(topic, lo, min(lo + LOG_STEP - 1, head))
    return out


def calls(pairs, block):
    out = []
    for i in range(0, len(pairs), BATCH):
        chunk = pairs[i:i + BATCH]
        res = post([{'jsonrpc': '2.0', 'id': j, 'method': 'eth_call', 'params': [{'to': to, 'data': data}, block]}
                    for j, (to, data) in enumerate(chunk)])
        if not isinstance(res, list) or len(res) != len(chunk):
            raise RpcError('batch refused')
        part = [None] * len(chunk)
        for r in res:
            part[r['id']] = r.get('result')
        out += part
    return out


# ---------- pure helpers (tested offline) ----------
def words(hexdata):
    raw = hexdata[2:] if isinstance(hexdata, str) and hexdata.startswith('0x') else ''
    if not re.fullmatch(r'(?:[0-9a-fA-F]{64})*', raw):
        return []
    return [raw[i:i + 64] for i in range(0, len(raw), 64)]


def parse_graduation(log):
    """token, amounts, block, tx from a graduation log. None for anything not from the factory."""
    t = log.get('topics') or []
    if len(t) != 2 or str(t[0]).lower() != GRADUATED or str(log.get('address', '')).lower() != FACTORY or log.get('removed'):
        return None
    w = words(log.get('data'))
    if len(w) != 2:
        return None
    try:
        return {'token': '0x' + t[1][-40:].lower(), 'quoteRaw': int(w[0], 16), 'tokensRaw': int(w[1], 16),
                'block': int(log['blockNumber'], 16), 'tx': str(log.get('transactionHash', '')).lower()}
    except (TypeError, ValueError):
        return None


def count_launches(logs):
    """Distinct tokens launched through the factory in these logs."""
    seen = set()
    for log in logs:
        t = log.get('topics') or []
        if len(t) == 4 and str(t[0]).lower() == TOKEN_LAUNCHED and str(log.get('address', '')).lower() == FACTORY \
                and not log.get('removed'):
            seen.add(t[1][-40:].lower())
    return len(seen)


def decode_record(hexdata):
    """getLaunchedToken: 15-word struct. None if the token is unknown (exists = false) or malformed."""
    w = words(hexdata)
    if len(w) != 15 or int(w[14], 16) != 1:
        return None
    a = lambda x: '0x' + x[24:].lower()
    return {'deployer': a(w[2]), 'pairToken': a(w[4]), 'phase': int(w[10], 16)}


def decode_string(hexdata):
    w = words(hexdata)
    if len(w) >= 2 and int(w[0], 16) == 32 and int(w[1], 16) <= (len(w) - 2) * 32:
        b = bytes.fromhex(''.join(w[2:]))[:int(w[1], 16)]
    elif len(w) == 1:
        b = bytes.fromhex(w[0]).rstrip(b'\0')
    else:
        return None
    s = ''.join(ch for ch in b.decode('utf-8', 'replace') if unicodedata.category(ch)[0] != 'C' and ch != '\ufffd').strip()[:64]
    return s or None


def decode_uint8(hexdata):
    w = words(hexdata)
    if len(w) != 1:
        return None
    n = int(w[0], 16)
    return n if n <= 36 else None


def parse_watch(raw):
    items = [x.strip() for x in (raw or '').split(',') if x.strip()]
    return sorted({x.lower() for x in items if ADDRESS.match(x)}), [x for x in items if not ADDRESS.match(x)]


def select_new(grads, watch, last_block, reported):
    """Graduations after last_block, not reported before, matching the watch list (all if empty). Oldest first."""
    w = set(watch)
    return sorted((g for g in grads if g['block'] > last_block and g['token'] not in reported
                   and (not w or g['token'] in w or g.get('deployer') in w)),
                  key=lambda g: (g['block'], g['token']))


def amount(raw, decimals):
    if decimals is None:
        return None
    s = f'{raw / 10 ** decimals:,.4f}'.rstrip('0').rstrip('.')
    return s


def build_report(grads, new, launches, watch, head, hours):
    return {'chainId': CHAIN_ID, 'block': head, 'windowHours': hours, 'graduations': len(grads),
            'launches': launches, 'rate': round(100 * len(grads) / launches, 2) if launches else None,
            'watch': list(watch), 'new': new}


def short(a):
    return f'{a[:6]}…{a[-4:]}'


def to_markdown(r):
    lines = []
    if r['new']:
        lines.append(f"NEW PONS GRADUATIONS · {len(r['new'])} · block {r['block']:,}")
        for g in r['new'][-MAX_LISTED:][::-1]:
            quote = amount(g['quoteRaw'], g.get('pairDecimals'))
            pool = f"{quote} {g.get('pairSymbol') or '?'}" if quote is not None else 'quote amount unknown'
            ago = (r['block'] - g['block']) * SEC_PER_BLOCK / 3600
            lines.append(f"• {g.get('symbol') or '?'} ({g.get('name') or 'unnamed'}) · {pool} into the pool · "
                         f"deployer {short(g['deployer']) if g.get('deployer') else '?'} · now: {g.get('phaseLabel') or '?'} · "
                         f"~{ago:.1f}h ago · {EXPLORER}/token/{g['token']}")
        if len(r['new']) > MAX_LISTED:
            lines.append(f"• +{len(r['new']) - MAX_LISTED} more (newest shown first)")
        lines.append('Graduation means the curve filled and liquidity moved to a locked pool. It is a fact, not a verdict.')
        lines.append('')
    lines.append(f"Pons v2 graduations · last {r['windowHours']:g}h · block {r['block']:,}")
    rate = f" ({r['rate']:g}% of launches)" if r['rate'] is not None else ''
    lines.append(f"{r['graduations']:,} graduated · {r['launches']:,} launched{rate}")
    if r['watch']:
        lines.append('Watching: ' + ', '.join(short(w) for w in r['watch']))
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--watch', default='', help='comma-separated token and/or deployer addresses; empty = all')
    ap.add_argument('--state', default='memory/state/pons-graduation-watch.json')
    ap.add_argument('--hours', type=float, default=24, help='summary window, and the first-run lookback')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    log = lambda m: print(m, file=sys.stderr, flush=True)

    watch, bad = parse_watch(a.watch)
    if bad:
        log(f'PONS_GRAD_BAD_WATCH: not 0x + 40 hex: {", ".join(bad[:5])}')
        return 3
    state_path = Path(a.state)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    try:
        if int(rpc('eth_chainId', []), 16) != CHAIN_ID:
            log('PONS_GRAD_RPC_DOWN: unexpected chain ID')
            return 2
        head = int(rpc('eth_blockNumber', []), 16)
        block = hex(head)
        start = max(0, head - int(a.hours * 3600 / SEC_PER_BLOCK))
        grads = list({g['token']: g for g in filter(None, map(parse_graduation, scan(GRADUATED, start, head)))}.values())
        launches = count_launches(scan(TOKEN_LAUNCHED, start, head))
        recs = calls([(FACTORY, GET_LAUNCHED + g['token'][2:].rjust(64, '0')) for g in grads], block) if grads else []
        for g, rec in zip(grads, recs):
            g.update(decode_record(rec) or {})
        last_block = state.get('lastBlock', start - 1) if state.get('watch') == watch else start - 1
        new = select_new(grads, watch, last_block, set(state.get('reported', [])))
        pairs = sorted({g['pairToken'] for g in new if g.get('pairToken') and g['pairToken'] != ZERO})
        meta = calls([(g['token'], s) for g in new for s in (NAME, SYMBOL)] +
                     [(p, s) for p in pairs for s in (SYMBOL, DECIMALS)], block) if new else []
    except RpcError as e:
        log(f'PONS_GRAD_RPC_DOWN: {e}')
        return 2
    pair_meta = {ZERO: ('ETH', 18)}
    for i, p in enumerate(pairs):
        k = 2 * len(new) + 2 * i
        pair_meta[p] = (decode_string(meta[k]), decode_uint8(meta[k + 1]))
    for i, g in enumerate(new):
        g['name'], g['symbol'] = decode_string(meta[2 * i]), decode_string(meta[2 * i + 1])
        g['pairSymbol'], g['pairDecimals'] = pair_meta.get(g.get('pairToken'), (None, None))
        ph = g.get('phase')
        g['phaseLabel'] = PHASE[ph] if isinstance(ph, int) and 0 <= ph < len(PHASE) else None
    report = build_report(grads, new, launches, watch, head, a.hours)
    state = {'lastBlock': head, 'watch': watch,
             'reported': (state.get('reported', []) + [g['token'] for g in new])[-1000:]}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, separators=(',', ':')))
    tmp.replace(state_path)
    print(json.dumps(report, indent=1, ensure_ascii=False) if a.json else to_markdown(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
