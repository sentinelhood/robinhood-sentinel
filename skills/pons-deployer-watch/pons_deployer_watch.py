#!/usr/bin/env python3
"""Alert when a watched deployer launches a new token on Pons v2 (Robinhood Chain, chain ID 4663),
plus the busiest deployers in the window.

Read-only and keyless. Data source: the official public RPC, via eth_chainId, eth_blockNumber,
eth_getLogs (TokenLaunched on the Pons v2 factory) and eth_call (getLaunchedToken to resolve a
token to its deployer, name() / symbol() on matched launches).

Usage:
  python3 pons_deployer_watch.py --watch 0xDEPLOYER,0xTOKEN --state memory/state/pons-deployer-watch.json \
      [--hours 24] [--json]

--watch takes deployer addresses, token addresses, or both. A token address is resolved to the
deployer the Pons factory records for it. Each launch by a watched deployer is reported once.

Exit codes: 0 ok, 2 RPC unreachable or wrong chain (PONS_DEPLOYER_RPC_DOWN),
3 bad input (PONS_DEPLOYER_BAD_WATCH).
"""
import argparse, json, re, sys, time, unicodedata, urllib.error, urllib.request
import http.client
from collections import Counter
from pathlib import Path

RPC = 'https://rpc.mainnet.chain.robinhood.com'
CHAIN_ID = 4663
FACTORY = '0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e'  # Pons v2, docs.ponsfamily.com/v2#contracts
TOKEN_LAUNCHED = '0x8d4aad4953d0ca700d468f3753aa14432d1b35b43ec6409f051fb6aa43a89607'
GET_LAUNCHED, NAME, SYMBOL = '0x3cf28b5a', '0x06fdde03', '0x95d89b41'
SEC_PER_BLOCK = 0.102
LOG_STEP = 1_000_000   # address + topic filter: the public RPC allows up to 10M blocks / 10k logs
BATCH = 50
BUSIEST = 5            # deployers listed in the summary
MAX_LISTED = 10        # launches listed per run; the rest are counted
ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')
HEADERS = {'Content-Type': 'application/json', 'User-Agent': 'aeon-pons-deployer-watch/1.0'}
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


def get_logs(lo, hi):
    """TokenLaunched logs in [lo, hi], halving the range whenever the 10k-log cap is hit."""
    try:
        return rpc('eth_getLogs', [{'address': FACTORY, 'topics': [TOKEN_LAUNCHED], 'fromBlock': hex(lo), 'toBlock': hex(hi)}])
    except RpcError as e:
        if 'exceeds limit' not in str(e) or hi <= lo:
            raise
        mid = (lo + hi) // 2
        return get_logs(lo, mid) + get_logs(mid + 1, hi)


def calls(pairs, block='latest'):
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
def parse_launch(log):
    """token, deployer, block, tx from a TokenLaunched log. None for anything not from the factory."""
    t = log.get('topics') or []
    if len(t) != 4 or str(t[0]).lower() != TOKEN_LAUNCHED or str(log.get('address', '')).lower() != FACTORY or log.get('removed'):
        return None
    try:
        return {'token': '0x' + t[1][-40:].lower(), 'deployer': '0x' + t[3][-40:].lower(),
                'block': int(log['blockNumber'], 16), 'tx': str(log.get('transactionHash', '')).lower()}
    except (TypeError, ValueError):
        return None


def parse_watch(raw):
    """Split --watch into addresses. Returns (addresses, bad entries)."""
    items = [x.strip() for x in (raw or '').split(',') if x.strip()]
    return sorted({x.lower() for x in items if ADDRESS.match(x)}), [x for x in items if not ADDRESS.match(x)]


def deployer_of(record_hex):
    """Deployer from a getLaunchedToken record (15 words, last = exists). None if not a Pons token."""
    raw = (record_hex or '')[2:]
    if len(raw) != 64 * 15 or not re.fullmatch(r'[0-9a-fA-F]+', raw) or int(raw[-64:], 16) != 1:
        return None
    return '0x' + raw[64 * 2 + 24:64 * 3].lower()


def decode_string(hexdata):
    raw = (hexdata or '')[2:]
    try:
        b = bytes.fromhex(raw)
    except ValueError:
        return None
    if len(b) >= 64 and int.from_bytes(b[:32], 'big') == 32:
        n = int.from_bytes(b[32:64], 'big')
        b = b[64:64 + n] if n <= len(b) - 64 else b''
    elif len(b) == 32:
        b = b.rstrip(b'\0')
    else:
        return None
    s = ''.join(ch for ch in b.decode('utf-8', 'replace') if unicodedata.category(ch)[0] != 'C' and ch != '\ufffd').strip()[:64]
    return s or None


def select_new(launches, watched, last_block, reported):
    """Launches by a watched deployer, after last_block, not reported before. Oldest first."""
    return sorted((l for l in launches if l['deployer'] in watched and l['block'] > last_block and l['token'] not in reported),
                  key=lambda l: (l['block'], l['token']))


def build_report(launches, new, watched, aliases, head, hours):
    per = Counter(l['deployer'] for l in launches)
    return {
        'chainId': CHAIN_ID, 'block': head, 'windowHours': hours, 'launches': len(launches),
        'deployers': len(per), 'watched': [{'deployer': d, 'via': aliases.get(d), 'launchesInWindow': per.get(d, 0)} for d in watched],
        'busiest': [{'deployer': d, 'launches': n} for d, n in per.most_common(BUSIEST)],
        'new': new,
    }


def short(a):
    return f'{a[:6]}…{a[-4:]}'


def to_markdown(r):
    lines = []
    if r['new']:
        lines.append(f"NEW LAUNCHES BY WATCHED DEPLOYERS · {len(r['new'])} · block {r['block']:,}")
        for l in r['new'][-MAX_LISTED:][::-1]:
            lines.append(f"• {l.get('symbol') or '?'} ({l.get('name') or 'unnamed'}) by {short(l['deployer'])} · "
                         f"{EXPLORER}/token/{l['token']}")
        if len(r['new']) > MAX_LISTED:
            lines.append(f"• +{len(r['new']) - MAX_LISTED} more (newest shown first)")
        lines.append('A new launch is a fact, not a verdict. Check the token before anyone buys.')
        lines.append('')
    lines.append(f"Pons v2 deployers · last {r['windowHours']:g}h · block {r['block']:,}")
    lines.append(f"{r['launches']:,} launches from {r['deployers']:,} deployers")
    if r['watched']:
        lines.append('Watching: ' + ', '.join(f"{short(w['deployer'])}{' (via token ' + short(w['via']) + ')' if w['via'] else ''} ×{w['launchesInWindow']}"
                                              for w in r['watched']))
    if r['busiest']:
        lines.append('Busiest: ' + ', '.join(f"{short(b['deployer'])} ×{b['launches']}" for b in r['busiest']))
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--watch', default='', help='comma-separated deployer and/or token addresses')
    ap.add_argument('--state', default='memory/state/pons-deployer-watch.json')
    ap.add_argument('--hours', type=float, default=24, help='summary window, and the first-run lookback')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    log = lambda m: print(m, file=sys.stderr, flush=True)

    addrs, bad = parse_watch(a.watch)
    if bad:
        log(f'PONS_DEPLOYER_BAD_WATCH: not 0x + 40 hex: {", ".join(bad[:5])}')
        return 3
    state_path = Path(a.state)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    try:
        if int(rpc('eth_chainId', []), 16) != CHAIN_ID:
            log('PONS_DEPLOYER_RPC_DOWN: unexpected chain ID')
            return 2
        head = int(rpc('eth_blockNumber', []), 16)
        # An address is a token if the factory has a record for it; then watch its deployer instead.
        records = calls([(FACTORY, GET_LAUNCHED + x[2:].rjust(64, '0')) for x in addrs]) if addrs else []
        watched, aliases = set(), {}
        for x, rec in zip(addrs, records):
            dep = deployer_of(rec)
            if dep:
                watched.add(dep)
                aliases.setdefault(dep, x)
            else:
                watched.add(x)
        start = max(0, head - int(a.hours * 3600 / SEC_PER_BLOCK))
        logs = []
        for lo in range(start, head + 1, LOG_STEP):
            logs += get_logs(lo, min(lo + LOG_STEP - 1, head))
        launches = list({l['token']: l for l in filter(None, map(parse_launch, logs))}.values())
        last_block = state.get('lastBlock', start - 1) if state.get('watched') == sorted(watched) else start - 1
        new = select_new(launches, watched, last_block, set(state.get('reported', [])))
        meta = calls([(l['token'], sel) for l in new for sel in (NAME, SYMBOL)]) if new else []
    except RpcError as e:
        log(f'PONS_DEPLOYER_RPC_DOWN: {e}')
        return 2
    for i, l in enumerate(new):
        l['name'], l['symbol'] = decode_string(meta[2 * i]), decode_string(meta[2 * i + 1])
    report = build_report(launches, new, sorted(watched), aliases, head, a.hours)
    state = {'lastBlock': head, 'watched': sorted(watched),
             'reported': (state.get('reported', []) + [l['token'] for l in new])[-1000:]}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, separators=(',', ':')))
    tmp.replace(state_path)
    print(json.dumps(report, indent=1, ensure_ascii=False) if a.json else to_markdown(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
