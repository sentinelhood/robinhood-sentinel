#!/usr/bin/env python3
"""Watch new Pons v2 launches on Robinhood Chain (chain ID 4663) for copies of your ticker.

Read-only and keyless. Data source: the official public RPC, via eth_chainId,
eth_blockNumber, eth_getLogs (TokenLaunched on the Pons v2 factory) and eth_call
(name() / symbol() on each new token).

Usage:
  python3 pons_launch_watch.py --watch SNTL,Sentinel --official 0x2da8...CbD0 \
      --state memory/state/pons-launch-watch.json [--hours 24] [--json]

A launch is a LOOKALIKE when its normalised symbol or name equals a watched term and its
address is not one of --official. The state file keeps the last block scanned, the launches
seen inside the window (so later runs only read new tokens) and the lookalikes already
reported, so each one is reported once.
"""
import argparse, json, re, sys, time, unicodedata, urllib.error, urllib.request
import http.client
from collections import Counter
from pathlib import Path

RPC = 'https://rpc.mainnet.chain.robinhood.com'
CHAIN_ID = 4663
# Pons v2 launch factory on Robinhood Chain (docs.ponsfamily.com/v2#contracts).
FACTORY = '0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e'
# keccak256("TokenLaunched(address,address,address,address,uint256,uint256)")
TOKEN_LAUNCHED = '0x8d4aad4953d0ca700d468f3753aa14432d1b35b43ec6409f051fb6aa43a89607'
NAME, SYMBOL = '0x06fdde03', '0x95d89b41'
SEC_PER_BLOCK = 0.102
LOG_STEP = 1_000_000   # address + topic filter: RPC allows 10M blocks / 10k logs per query
BATCH = 50             # eth_call per JSON-RPC batch; the public RPC accepts this without 429s
SERIAL = 10            # deployers with at least this many launches in the window are listed
MAX_LISTED = 10        # lookalikes printed per run; the rest are counted
SEEN_KEYS = ('token', 'deployer', 'block', 'symbol', 'name')  # cached launch rows, stored as arrays
HEADERS = {'Content-Type': 'application/json', 'User-Agent': 'aeon-pons-launch-watch/1.0'}
ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')


class RpcError(RuntimeError):
    pass


def post(body):
    for attempt in range(8):
        req = urllib.request.Request(RPC, json.dumps(body).encode(), HEADERS)
        try:
            data = json.load(urllib.request.urlopen(req, timeout=90))
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504):
                time.sleep(min(20, 1.5 * (attempt + 1)))
                continue
            raise RpcError(f'HTTP {e.code}') from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            time.sleep(min(20, 1.5 * (attempt + 1)))
            continue
        if isinstance(data, dict) and (data.get('error') or {}).get('code') == 429:
            time.sleep(min(20, 1.5 * (attempt + 1)))
            continue
        return data
    raise RpcError('gave up after retries')


def rpc(method, params):
    body = post({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    if 'error' in body:
        raise RpcError(f"{method}: {body['error'].get('message', body['error'])}")
    return body['result']


def get_logs(lo, hi):
    """TokenLaunched logs in [lo, hi], halving the range whenever the 10k-log cap is hit."""
    try:
        return rpc('eth_getLogs', [{'address': FACTORY, 'topics': [TOKEN_LAUNCHED], 'fromBlock': hex(lo), 'toBlock': hex(hi)}])
    except RpcError as e:
        if 'exceeds limit' not in str(e) or hi <= lo:
            raise
        mid = (lo + hi) // 2
        return get_logs(lo, mid) + get_logs(mid + 1, hi)


def parse_launch(log):
    """token, deployer, block from a TokenLaunched log. None for anything not from the factory."""
    t = log.get('topics') or []
    if len(t) != 4 or str(t[0]).lower() != TOKEN_LAUNCHED or str(log.get('address', '')).lower() != FACTORY or log.get('removed'):
        return None
    try:
        return {'token': '0x' + t[1][-40:].lower(), 'deployer': '0x' + t[3][-40:].lower(), 'block': int(log['blockNumber'], 16)}
    except (TypeError, ValueError):
        return None


def decode_string(hexdata):
    """ABI string, with a bytes32 fallback. Control characters stripped, capped at 64 chars."""
    raw = (hexdata or '')[2:]
    try:
        b = bytes.fromhex(raw)
    except ValueError:
        return ''
    if len(b) >= 64 and int.from_bytes(b[:32], 'big') == 32:
        n = int.from_bytes(b[32:64], 'big')
        b = b[64:64 + n] if n <= len(b) - 64 else b''
    elif len(b) == 32:
        b = b.rstrip(b'\0')
    else:
        return ''
    s = b.decode('utf-8', 'replace')
    return ''.join(ch for ch in s if unicodedata.category(ch)[0] != 'C' and ch != '\ufffd').strip()[:64]


def normalise(s):
    """Compare tickers the way people read them: case-folded, NFKC (full-width -> ASCII), no $ or punctuation."""
    s = unicodedata.normalize('NFKC', s or '').casefold()
    return ''.join(ch for ch in s if ch.isalnum())


def read_metadata(tokens):
    """name() and symbol() for each token, in JSON-RPC batches."""
    out = {}
    calls = [(tok, sel) for tok in tokens for sel in (NAME, SYMBOL)]
    for i in range(0, len(calls), BATCH):
        chunk = calls[i:i + BATCH]
        res = post([{'jsonrpc': '2.0', 'id': j, 'method': 'eth_call', 'params': [{'to': tok, 'data': sel}, 'latest']} for j, (tok, sel) in enumerate(chunk)])
        if not isinstance(res, list):
            raise RpcError('batch refused')
        for r in res:
            tok, sel = chunk[r['id']]
            out.setdefault(tok, {})['name' if sel == NAME else 'symbol'] = decode_string(r.get('result'))
        time.sleep(0.2)
    return out


def find_lookalikes(launches, watch, official):
    """Launches whose symbol or name equals a watched term, excluding the official addresses."""
    terms = {normalise(w): w for w in watch if normalise(w)}
    hits = []
    for l in launches:
        if l['token'] in official:
            continue
        for field in ('symbol', 'name'):
            key = normalise(l.get(field))
            if key in terms:
                hits.append({**l, 'matched': terms[key], 'field': field})
                break
    return hits


def build_report(launches, lookalikes, head, hours):
    tickers = Counter(normalise(l.get('symbol')) for l in launches if normalise(l.get('symbol')))
    shown = {}
    for l in launches:
        k = normalise(l.get('symbol'))
        if k and k not in shown:
            shown[k] = l.get('symbol')
    deployers = Counter(l['deployer'] for l in launches)
    return {
        'chainId': CHAIN_ID, 'block': head, 'windowHours': hours,
        'launches': len(launches),
        'sharedTickerLaunches': sum(n for n in tickers.values() if n > 1),
        'distinctTickers': len(tickers),
        'topRepeated': [{'symbol': shown[k], 'launches': n} for k, n in tickers.most_common(5) if n > 1],
        'serialDeployers': [{'deployer': d, 'launches': n} for d, n in deployers.most_common() if n >= SERIAL][:5],
        'lookalikes': lookalikes,
    }


def short(a):
    return f'{a[:6]}…{a[-4:]}'


def to_markdown(r):
    lines = []
    if r['lookalikes']:
        lines.append(f"LOOKALIKE LAUNCHES · {len(r['lookalikes'])} new · block {r['block']:,}")
        for h in r['lookalikes'][-MAX_LISTED:][::-1]:
            lines.append(f"• {h.get('symbol') or '?'} ({h.get('name') or 'unnamed'}) matches \"{h['matched']}\" by {h['field']}: "
                         f"{h['token']} by {short(h['deployer'])} · robinhoodchain.blockscout.com/token/{h['token']}")
        if len(r['lookalikes']) > MAX_LISTED:
            lines.append(f"• +{len(r['lookalikes']) - MAX_LISTED} more (newest shown first)")
        lines.append('Not your official address. Warn your community to check the CA.')
        lines.append('')
    pct = round(100 * r['sharedTickerLaunches'] / r['launches']) if r['launches'] else 0
    lines.append(f"Pons v2 launches on Robinhood Chain · last {r['windowHours']:g}h · block {r['block']:,}")
    lines.append(f"{r['launches']:,} launches · {r['distinctTickers']:,} distinct tickers · {r['sharedTickerLaunches']:,} ({pct}%) share a ticker with another launch")
    if r['topRepeated']:
        lines.append('Most repeated: ' + ', '.join(f"{t['symbol']} ×{t['launches']}" for t in r['topRepeated']))
    if r['serialDeployers']:
        lines.append('Busiest deployers: ' + ', '.join(f"{short(d['deployer'])} ×{d['launches']}" for d in r['serialDeployers']))
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--watch', default='', help='comma-separated tickers or names to guard, e.g. SNTL,Sentinel')
    ap.add_argument('--official', default='', help='comma-separated official token addresses (never flagged)')
    ap.add_argument('--state', default='memory/state/pons-launch-watch.json')
    ap.add_argument('--hours', type=float, default=24, help='window for the summary, and the first-run lookback')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    log = lambda m: print(m, file=sys.stderr, flush=True)

    watch = [w.strip() for w in args.watch.split(',') if w.strip()]
    official = {a.strip().lower() for a in args.official.split(',') if ADDRESS.match(a.strip())}
    if any(a.strip() and not ADDRESS.match(a.strip()) for a in args.official.split(',')):
        log('PONS_WATCH_BAD_OFFICIAL: --official must be 0x + 40 hex addresses')
        return 2
    state_path = Path(args.state)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    try:
        if int(rpc('eth_chainId', []), 16) != CHAIN_ID:
            log('PONS_WATCH_RPC_DOWN: unexpected chain ID')
            return 2
        head = int(rpc('eth_blockNumber', []), 16)
        window_start = max(0, head - int(args.hours * 3600 / SEC_PER_BLOCK))
        # Launches already read on an earlier run stay cached; only blocks after lastBlock are scanned.
        cached = {}
        for row in state.get('seen', []):
            if isinstance(row, list) and len(row) == len(SEEN_KEYS) and isinstance(row[2], int) and row[2] >= window_start:
                l = dict(zip(SEEN_KEYS, row))
                cached[l['token']] = l
        scan_from = max(window_start, state.get('lastBlock', -1) + 1) if cached else window_start
        logs = []
        for lo in range(scan_from, head + 1, LOG_STEP):
            logs += get_logs(lo, min(lo + LOG_STEP - 1, head))
        fresh = [l for l in {l['token']: l for l in filter(None, map(parse_launch, logs))}.values() if l['token'] not in cached]
        meta = read_metadata([l['token'] for l in fresh])
    except RpcError as e:
        log(f'PONS_WATCH_RPC_DOWN: {e}')
        return 2
    for l in fresh:
        l.update(meta.get(l['token'], {}))
    launches = sorted([*cached.values(), *fresh], key=lambda l: l['block'])
    log(f'  {len(fresh)} new launches read, {len(cached)} from cache')

    reported = set(state.get('reported', []))
    # Check the whole window (cheap, in memory) so a newly added --watch term also catches cached launches;
    # the reported set keeps each lookalike to a single notification.
    hits = [h for h in find_lookalikes(launches, watch, official) if h['token'] not in reported]
    report = build_report(launches, sorted(hits, key=lambda h: h['block']), head, args.hours)

    state = {'lastBlock': head, 'seen': [[l.get(k) for k in SEEN_KEYS] for l in launches],
             'reported': sorted(reported | {h['token'] for h in hits})[-500:]}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, separators=(',', ':'), ensure_ascii=False))
    tmp.replace(state_path)
    print(json.dumps(report, indent=1) if args.json else to_markdown(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
