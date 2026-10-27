#!/usr/bin/env python3
"""The most active Pons v2 bonding curves on Robinhood Chain (chain ID 4663) in the last N hours:
buys, sells, distinct traders, volume and net quote in, and how far each curve is toward graduation.

Read-only and keyless. Data source: the official public RPC, via eth_chainId, eth_blockNumber,
eth_getLogs (curve Buy / Sell events) and eth_call (token() and getReserves() on each curve,
getLaunchedToken on the Pons v2 factory, totalSupply() / name() / symbol() / decimals()).

Tokens still on a curve have no DEX pair yet, so market scanners that read DEX pools do not see them.

Usage:
  python3 pons_curve_movers.py [--hours 6] [--top 10] [--json]

Exit codes: 0 ok, 2 RPC unreachable or wrong chain (PONS_MOVERS_RPC_DOWN), 3 bad input (PONS_MOVERS_BAD_INPUT).
"""
import argparse, json, re, sys, time, unicodedata, urllib.error, urllib.request
from collections import Counter, defaultdict

RPC = 'https://rpc.mainnet.chain.robinhood.com'
CHAIN_ID = 4663
FACTORY = '0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e'  # Pons v2, docs.ponsfamily.com/v2#contracts
# Curve events, read from live curves on 2026-10-26. Topics 1-2 are sender and recipient.
# Buy data:  quote in (gross), tokens out, fee 1, fee 2.   Sell data: tokens in, quote out (net), fee 1, fee 2.
# Check: summing buys (quote - fees) minus sells (quote + fees) equals the curve's real quote reserve above
# its starting virtual reserve, and two graduated curves hit their factory threshold in the graduating buy.
BUY = '0xec36bf571f136799e8dc0b0b8bea4b04d8bd3d43de838aab0d5fc21d4cbfc455'
SELL = '0x8113d738abdcb6b38357e9d53a54a7157861a09031b453651f0fe7fe151f59df'
GET_LAUNCHED, TOKEN, RESERVES = '0x3cf28b5a', '0xfc0c546a', '0x0902f1ac'
NAME, SYMBOL, DECIMALS, SUPPLY = '0x06fdde03', '0x95d89b41', '0x313ce567', '0x18160ddd'
PHASE = ['bonding curve', 'swept, pool pending', 'Uniswap v4 pool, liquidity locked', 'rescued (recovery path)']
ZERO = '0x' + '0' * 40
SEC_PER_BLOCK = 0.102
LOG_STEP = 30_000      # topic-only filter: the public RPC allows 30k blocks per request
CANDIDATES = 40        # busiest emitters checked against the factory before ranking
BATCH = 50
MAX_HOURS = 24
HEADERS = {'Content-Type': 'application/json', 'User-Agent': 'aeon-pons-curve-movers/1.0'}
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
        except (urllib.error.URLError, TimeoutError):
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
    """Logs for one topic in [lo, hi], halving the range whenever the RPC's log cap is hit."""
    try:
        return rpc('eth_getLogs', [{'topics': [topic], 'fromBlock': hex(lo), 'toBlock': hex(hi)}])
    except RpcError as e:
        if 'exceeds limit' not in str(e) or hi <= lo:
            raise
        mid = (lo + hi) // 2
        return get_logs(topic, lo, mid) + get_logs(topic, mid + 1, hi)


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


def parse_trade(log):
    """A curve Buy or Sell log. None for anything else. The curve itself is validated later."""
    t = log.get('topics') or []
    if len(t) != 3 or log.get('removed') or str(t[0]).lower() not in (BUY, SELL):
        return None
    w = words(log.get('data'))
    if len(w) != 4:
        return None
    try:
        a, b, f1, f2 = (int(x, 16) for x in w)
        buy = str(t[0]).lower() == BUY
        return {'curve': str(log['address']).lower(), 'buy': buy, 'trader': '0x' + str(t[2])[-40:].lower(),
                'block': int(log['blockNumber'], 16),
                # quote moved by the trade, before fees, and its effect on the curve's real quote reserve
                'volume': a if buy else b + f1 + f2, 'net': a - f1 - f2 if buy else -(b + f1 + f2)}
    except (TypeError, ValueError, KeyError):
        return None


def aggregate(trades):
    per = defaultdict(lambda: {'buys': 0, 'sells': 0, 'traders': set(), 'byTrader': Counter(), 'volume': 0, 'net': 0, 'lastBlock': 0})
    for t in trades:
        a = per[t['curve']]
        a['buys' if t['buy'] else 'sells'] += 1
        a['traders'].add(t['trader'])
        a['byTrader'][t['trader']] += 1
        a['volume'] += t['volume']
        a['net'] += t['net']
        a['lastBlock'] = max(a['lastBlock'], t['block'])
    return per


def rank(per):
    """Most distinct traders first, then trades. Both are unit-free, so curves on different pairs compare fairly.

    Traders lead because one wallet can send thousands of dust buys; seen live on 2026-10-27."""
    return sorted(per, key=lambda c: (-len(per[c]['traders']), -(per[c]['buys'] + per[c]['sells']), c))


def concentration(agg):
    """The busiest recipient address on the curve, its trade count, and that share of all trades, in percent."""
    total = agg['buys'] + agg['sells']
    if not agg['byTrader']:
        return None, 0, None
    who, top = max(agg['byTrader'].items(), key=lambda kv: (kv[1], kv[0]))
    return who, top, (round(100 * top / total, 1) if total else None)


def recipient_kind(code):
    """'wallet' for no code or an EIP-7702 delegation (0xef0100 + address), 'contract' for real bytecode, None if unknown.

    Routers and aggregators receive curve trades for many people, so a contract here is not one person."""
    if not isinstance(code, str) or not re.fullmatch(r'0x(?:[0-9a-fA-F]{2})*', code):
        return None
    if code == '0x' or re.fullmatch(r'0xef0100[0-9a-fA-F]{40}', code):
        return 'wallet'
    return 'contract'


def decode_record(hexdata):
    """getLaunchedToken: 15-word struct. None if unknown (exists = false) or malformed."""
    w = words(hexdata)
    if len(w) != 15 or int(w[14], 16) != 1:
        return None
    a = lambda x: '0x' + x[24:].lower()
    return {'curve': a(w[1]), 'deployer': a(w[2]), 'pairToken': a(w[4]), 'threshold': int(w[5], 16), 'phase': int(w[10], 16)}


def address_of(hexdata):
    w = words(hexdata)
    return '0x' + w[0][24:].lower() if len(w) == 1 and int(w[0][:24], 16) == 0 else None


def uint(hexdata):
    w = words(hexdata)
    return int(w[0], 16) if len(w) == 1 else None


def progress(reserves_hex, supply, threshold):
    """Share of the graduation threshold raised so far, in percent.

    The curve is constant-product and starts at (virtual quote, total supply), so the starting virtual quote
    is reserveQuote * reserveToken / supply and the real quote raised is reserveQuote minus that."""
    w = words(reserves_hex)
    if len(w) < 2 or not supply or not threshold:
        return None
    q, t = int(w[0], 16), int(w[1], 16)
    raised = q - q * t // supply
    return round(max(0.0, min(100.0, 100 * raised / threshold)), 2)


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


def amount(raw, decimals):
    if decimals is None:
        return None
    return f'{raw / 10 ** decimals:,.4f}'.rstrip('0').rstrip('.')


def short(a):
    return f'{a[:6]}…{a[-4:]}'


def to_markdown(r):
    lines = [f"Pons v2 curve movers · last {r['windowHours']:g}h · block {r['block']:,}",
             f"{r['trades']:,} curve trades on {r['curves']:,} curves"]
    if r['skipped']:
        lines.append(f"{r['skipped']} busy emitter(s) skipped: not a curve the Pons factory recorded")
    lines.append('')
    if not r['movers']:
        lines.append('No curve trades in the window.')
    for i, m in enumerate(r['movers'], 1):
        unit = m.get('pairSymbol') or '?'
        vol, net = amount(m['volume'], m.get('pairDecimals')), amount(abs(m['net']), m.get('pairDecimals'))
        flow = f"{vol} {unit} traded, net {'+' if m['net'] >= 0 else '-'}{net} {unit}" if vol is not None else 'volume unknown'
        if m.get('phase') == 0:
            prog = f"{m['progress']:g}% to graduation" if m.get('progress') is not None else 'progress unknown'
        else:
            prog = f"now: {m.get('phaseLabel') or 'phase ' + str(m.get('phase'))}"
        if m.get('topRecipientKind') == 'wallet' and m.get('topTraderShare') is not None:
            top = f" (busiest wallet {m['topTraderShare']:g}% of trades)"
        elif m.get('topRecipientKind') == 'contract':
            top = ' (busiest recipient is a router contract)'
        else:
            top = ''
        lines.append(f"{i}. {m.get('symbol') or '?'} ({m.get('name') or 'unnamed'}) · {m['buys']} buys / {m['sells']} sells · "
                     f"{m['traders']} traders{top} · {flow} · {prog} · {EXPLORER}/token/{m['token']}")
    lines.append('')
    lines.append('Activity on a curve is a fact, not a verdict. Many trades can come from a few wallets.')
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--hours', type=float, default=6)
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    log = lambda m: print(m, file=sys.stderr, flush=True)
    if not 0 < a.hours <= MAX_HOURS or not 1 <= a.top <= 25:
        log(f'PONS_MOVERS_BAD_INPUT: --hours must be in (0, {MAX_HOURS}], --top in [1, 25]')
        return 3
    try:
        if int(rpc('eth_chainId', []), 16) != CHAIN_ID:
            log('PONS_MOVERS_RPC_DOWN: unexpected chain ID')
            return 2
        head = int(rpc('eth_blockNumber', []), 16)
        block = hex(head)
        start = max(0, head - int(a.hours * 3600 / SEC_PER_BLOCK))
        raw = []
        for topic in (BUY, SELL):
            for lo in range(start, head + 1, LOG_STEP):
                raw += get_logs(topic, lo, min(lo + LOG_STEP - 1, head))
        trades = list(filter(None, map(parse_trade, raw)))
        per = aggregate(trades)
        candidates = rank(per)[:CANDIDATES]
        # Any contract can emit these events. Keep only curves the factory records for their own token.
        tokens = [address_of(x) for x in calls([(c, TOKEN) for c in candidates], block)] if candidates else []
        recs = calls([(FACTORY, GET_LAUNCHED + (t or ZERO)[2:].rjust(64, '0')) for t in tokens], block) if tokens else []
        valid = []
        for c, t, rec in zip(candidates, tokens, recs):
            r = decode_record(rec)
            if t and r and r['curve'] == c:
                valid.append({'curve': c, 'token': t, **r})
        movers = valid[:a.top]
        tops = [concentration(per[m['curve']]) for m in movers]
        codes = post([{'jsonrpc': '2.0', 'id': i, 'method': 'eth_getCode', 'params': [t[0], block]} for i, t in enumerate(tops)]) if movers else []
        if not isinstance(codes, list) or len(codes) != len(movers):
            raise RpcError('batch refused')
        kinds = {r['id']: recipient_kind(r.get('result')) for r in codes}
        pairs = sorted({m['pairToken'] for m in movers if m['pairToken'] != ZERO})
        meta = calls([(m['curve'], RESERVES) for m in movers] + [(m['token'], s) for m in movers for s in (SUPPLY, NAME, SYMBOL)] +
                     [(p, s) for p in pairs for s in (SYMBOL, DECIMALS)], block) if movers else []
    except RpcError as e:
        log(f'PONS_MOVERS_RPC_DOWN: {e}')
        return 2
    n = len(movers)
    pair_meta = {ZERO: ('ETH', 18)}
    for i, p in enumerate(pairs):
        k = 4 * n + 2 * i
        d = uint(meta[k + 1])
        pair_meta[p] = (decode_string(meta[k]), d if d is not None and d <= 36 else None)
    out = []
    for i, m in enumerate(movers):
        agg = per[m['curve']]
        supply, name, sym = uint(meta[n + 3 * i]), decode_string(meta[n + 3 * i + 1]), decode_string(meta[n + 3 * i + 2])
        ps, pd = pair_meta.get(m['pairToken'], (None, None))
        ph = m['phase']
        out.append({'token': m['token'], 'curve': m['curve'], 'deployer': m['deployer'], 'name': name, 'symbol': sym,
                    'buys': agg['buys'], 'sells': agg['sells'], 'traders': len(agg['traders']),
                    'topTraderTrades': tops[i][1], 'topRecipientKind': kinds.get(i),
                    'topTraderShare': tops[i][2] if kinds.get(i) == 'wallet' else None,
                    'volume': agg['volume'], 'net': agg['net'], 'lastBlock': agg['lastBlock'],
                    'pairToken': m['pairToken'], 'pairSymbol': ps, 'pairDecimals': pd,
                    'phase': ph, 'phaseLabel': PHASE[ph] if 0 <= ph < len(PHASE) else None,
                    'progress': progress(meta[i], supply, m['threshold']) if ph == 0 else None})
    report = {'chainId': CHAIN_ID, 'block': head, 'windowHours': a.hours, 'trades': len(trades), 'curves': len(per),
              'skipped': len(candidates) - len(valid), 'movers': out}
    if a.json:
        print(json.dumps(report, indent=1, ensure_ascii=False, default=str))
    else:
        print(to_markdown(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
