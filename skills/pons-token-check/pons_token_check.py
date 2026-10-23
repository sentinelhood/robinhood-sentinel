#!/usr/bin/env python3
"""One-shot check of a token on Robinhood Chain (chain ID 4663): ERC-20 metadata, its Pons v2
factory record (phase, creator tax, base fee, buyback, pair), the deployer's full Pons launch
history, and what the deployer and fee recipient currently hold.

Read-only and keyless. Data source: the official public RPC, via eth_chainId, eth_blockNumber,
eth_getCode, eth_call and eth_getLogs. Every read is pinned to one block.

Usage:
  python3 pons_token_check.py 0xTOKEN [--json]

Exit codes: 0 report written, 2 RPC unreachable or wrong chain (PONS_CHECK_RPC_DOWN),
3 bad input (PONS_CHECK_BAD_TARGET).
"""
import argparse, json, re, sys, time, urllib.error, urllib.request, unicodedata

RPC = 'https://rpc.mainnet.chain.robinhood.com'
CHAIN_ID = 4663
FACTORY = '0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e'  # Pons v2, docs.ponsfamily.com/v2#contracts
TOKEN_LAUNCHED = '0x8d4aad4953d0ca700d468f3753aa14432d1b35b43ec6409f051fb6aa43a89607'
FIRST_BLOCK = 28_000_000      # first Pons v2 launch is just after 28.58M
LOG_WINDOW = 10_000_000       # address + topic filter: the public RPC allows 10M-block ranges
SEL = {'launch': '0x3cf28b5a', 'fee': '0x24a9d853', 'name': '0x06fdde03', 'symbol': '0x95d89b41',
       'decimals': '0x313ce567', 'supply': '0x18160ddd', 'balance': '0x70a08231'}
PHASE = ['bonding curve', 'swept, pool pending', 'Uniswap v4 pool, liquidity locked', 'rescued (recovery path)']
ZERO = '0x' + '0' * 40
ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')
HEADERS = {'Content-Type': 'application/json', 'User-Agent': 'aeon-pons-token-check/1.0'}
SERIAL = 10            # launches from one deployer at which the history is called out
BIG_HOLDER_PCT = 5.0   # deployer / fee recipient share of supply worth calling out
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


def calls(pairs, block):
    """eth_call for each (to, data) in one batch. A reverted or failed call returns None."""
    res = post([{'jsonrpc': '2.0', 'id': i, 'method': 'eth_call', 'params': [{'to': to, 'data': data}, block]}
                for i, (to, data) in enumerate(pairs)])
    if not isinstance(res, list) or len(res) != len(pairs):
        raise RpcError('batch refused')
    out = [None] * len(pairs)
    for r in res:
        out[r['id']] = r.get('result')
    return out


# ---------- decoding (pure, tested offline) ----------
def words(hexdata):
    raw = (hexdata or '')[2:] if isinstance(hexdata, str) and hexdata.startswith('0x') else ''
    if not re.fullmatch(r'(?:[0-9a-fA-F]{64})*', raw):
        return []
    return [raw[i:i + 64] for i in range(0, len(raw), 64)]


def uint(hexdata):
    w = words(hexdata)
    return int(w[0], 16) if len(w) == 1 else None


def decode_string(hexdata):
    """ABI string, with a bytes32 fallback. Control characters stripped, capped at 64 chars."""
    w = words(hexdata)
    if len(w) >= 2 and int(w[0], 16) == 32 and int(w[1], 16) <= (len(w) - 2) * 32:
        b = bytes.fromhex(''.join(w[2:]))[:int(w[1], 16)]
    elif len(w) == 1:
        b = bytes.fromhex(w[0]).rstrip(b'\0')
    else:
        return None
    s = b.decode('utf-8', 'replace')
    s = ''.join(ch for ch in s if unicodedata.category(ch)[0] != 'C' and ch != '\ufffd').strip()[:64]
    return s or None


def decode_launch(hexdata):
    """getLaunchedToken: a 15-word static struct; all zeros (exists = false) for an unknown token."""
    w = words(hexdata)
    if len(w) != 15:
        raise ValueError('unexpected factory response')
    if int(w[14], 16) != 1:
        return None
    a = lambda x: '0x' + x[24:].lower()
    return {'token': a(w[0]), 'curve': a(w[1]), 'deployer': a(w[2]), 'feeRecipient': a(w[3]), 'pairToken': a(w[4]),
            'creatorTaxBps': int(w[8], 16), 'buyback': int(w[9], 16) == 1, 'phase': int(w[10], 16)}


def delegated_to(code):
    """EIP-7702: an EOA delegating to a contract carries exactly 0xef0100 || address. It is a wallet."""
    m = re.fullmatch(r'0xef0100([0-9a-fA-F]{40})', code or '')
    return '0x' + m.group(1).lower() if m else None


def account_kind(code):
    if not code or code == '0x':
        return 'wallet'
    if delegated_to(code):
        return 'wallet, EIP-7702 delegated'
    return 'contract'


def history(logs, deployer, token):
    """Pons launches by this deployer (deduped, newest first) and this token's position in them."""
    own = {}
    for log in logs:
        t = log.get('topics') or []
        if (len(t) != 4 or str(t[0]).lower() != TOKEN_LAUNCHED or str(log.get('address', '')).lower() != FACTORY
                or log.get('removed') or '0x' + t[3][-40:].lower() != deployer):
            continue
        own.setdefault('0x' + t[1][-40:].lower(), int(log['blockNumber'], 16))
    ordered = sorted(own.items(), key=lambda kv: kv[1])
    tokens = [t for t, _ in ordered]
    return {'launches': len(ordered), 'firstBlock': ordered[0][1] if ordered else None,
            'number': tokens.index(token) + 1 if token in tokens else None}


def pct(part, total):
    return round(100 * part / total, 2) if total else None


def bps(n):
    return f"{n / 100:.2f}".rstrip('0').rstrip('.') + '%'


def short(a):
    return f'{a[:6]}…{a[-4:]}'


def facts(r):
    """Plain facts worth a second look. Never a verdict."""
    out, p = [], r.get('pons')
    if not r['erc20']:
        return ['Not an ERC-20 token: decimals() or totalSupply() did not answer.']
    if not p:
        return ['No Pons v2 launch record. Tax, supply and liquidity rules of Pons do not apply; read the contract itself.']
    if p['creatorTaxBps']:
        out.append(f"Creator tax {bps(p['creatorTaxBps'])} on every trade, on top of the {bps(p['baseFeeBps']) if p['baseFeeBps'] is not None else 'unknown'} base fee.")
    if p['phase'] == 0:
        out.append('Still on the bonding curve: no Uniswap v4 pool yet.')
    elif p['phase'] == 3:
        out.append('Launch went through the rescue (recovery) path.')
    for role in ('deployer', 'feeRecipient'):
        h = p['holdings'].get(role)
        if h and h['percent'] is not None and h['percent'] >= BIG_HOLDER_PCT:
            out.append(f"{'Deployer' if role == 'deployer' else 'Fee recipient'} holds {h['percent']}% of supply.")
    hist = p['deployerHistory']
    if hist and hist['launches'] >= SERIAL:
        out.append(f"Deployer has launched {hist['launches']} Pons tokens" + (f" (this is #{hist['number']})." if hist['number'] else '.'))
    return out


def to_markdown(r):
    head = f"*Pons Token Check: {r['symbol'] or '?'}" + (f" ({r['name']})" if r['name'] else '') + '*'
    lines = [head, f"`{r['token']}` · Robinhood Chain {CHAIN_ID} · block {r['block']:,}", '']
    if r['erc20']:
        lines.append(f"Supply: {r['totalSupply']} · decimals {r['decimals']}")
    p = r.get('pons')
    if p:
        cost = (f"{bps(p['baseFeeBps'] + p['creatorTaxBps'])} ({bps(p['baseFeeBps'])} base + {bps(p['creatorTaxBps'])} creator tax)"
                if p['baseFeeBps'] is not None else f"base fee unknown + {bps(p['creatorTaxBps'])} creator tax")
        pair = 'native ETH' if p['pairToken'] == ZERO else (p['pairSymbol'] or short(p['pairToken']))
        lines += [f"Launch: Pons v2 · phase: {PHASE[p['phase']] if p['phase'] < len(PHASE) else p['phase']}",
                  f"Trading cost: {cost} · buyback {'on' if p['buyback'] else 'off'} · pair: {pair}"]
        hist = p['deployerHistory']
        dh = p['holdings'].get('deployer')
        hist_txt = (f"{hist['launches']} Pons launch{'es' if hist['launches'] != 1 else ''}" + (f" (this is #{hist['number']})" if hist['number'] else '')) if hist else 'history unavailable'
        lines.append(f"Deployer: {short(p['deployer'])} ({p['deployerKind']}) · holds {dh['percent'] if dh else '?'}% · {hist_txt}")
        if p['feeRecipient'] == p['deployer']:
            lines.append('Fee recipient: same as deployer')
        elif p['feeRecipient'] != ZERO:
            fh = p['holdings'].get('feeRecipient')
            lines.append(f"Fee recipient: {short(p['feeRecipient'])} · holds {fh['percent'] if fh else '?'}%")
    lines += ['', 'Facts worth a look:']
    lines += [f'- {f}' for f in r['facts']] or ['- Nothing stood out in these reads.']
    lines += ['', f"Read-only facts at block {r['block']:,}. Not an audit, a price signal or a safety verdict. {EXPLORER}/token/{r['token']}"]
    return '\n'.join(lines)


# ---------- chain reads ----------
def check(token):
    if int(rpc('eth_chainId', []), 16) != CHAIN_ID:
        raise RpcError('wrong chain')
    block_n = int(rpc('eth_blockNumber', []), 16)
    block = hex(block_n)
    pad = lambda a: a[2:].rjust(64, '0')
    name, symbol, dec, supply, rec, code = calls(
        [(token, SEL['name']), (token, SEL['symbol']), (token, SEL['decimals']), (token, SEL['supply']),
         (FACTORY, SEL['launch'] + pad(token))], block) + [rpc('eth_getCode', [token, block])]
    if rec is None:
        raise RpcError('factory read failed')
    decimals, total = uint(dec), uint(supply)
    erc20 = decimals is not None and decimals <= 36 and total is not None
    r = {'chainId': CHAIN_ID, 'block': block_n, 'token': token, 'codeBytes': (len(code) - 2) // 2,
         'erc20': erc20, 'name': decode_string(name) if erc20 else None, 'symbol': decode_string(symbol) if erc20 else None,
         'decimals': decimals if erc20 else None, 'totalSupply': None, 'pons': None}
    if erc20:
        r['totalSupply'] = f'{total // 10 ** decimals:,}' + (f'.{total % 10 ** decimals:0{decimals}d}'.rstrip('0').rstrip('.') if decimals else '')
    launch = decode_launch(rec)
    if launch and launch['token'] != token:
        raise RpcError('factory record mismatch')
    if launch:
        holders = {'deployer': launch['deployer']}
        if launch['feeRecipient'] not in (ZERO, launch['deployer']):
            holders['feeRecipient'] = launch['feeRecipient']
        roles = list(holders)
        pair_q = [] if launch['pairToken'] == ZERO else [(launch['pairToken'], SEL['symbol'])]
        res = calls([(launch['curve'], SEL['fee'])] + [(token, SEL['balance'] + pad(holders[k])) for k in roles] + pair_q, block)
        fee = uint(res[0])
        launch['baseFeeBps'] = fee if fee is not None and fee <= 10000 else None
        launch['holdings'] = {}
        for k, raw in zip(roles, res[1:1 + len(roles)]):
            bal = uint(raw)
            launch['holdings'][k] = {'address': holders[k], 'percent': pct(bal, total) if bal is not None and erc20 else None}
        launch['pairSymbol'] = decode_string(res[-1]) if pair_q else None
        launch['deployerKind'] = account_kind(rpc('eth_getCode', [launch['deployer'], block]))
        try:
            launch['deployerHistory'] = deployer_history(launch['deployer'], token, block_n)
        except RpcError:
            launch['deployerHistory'] = None
        r['pons'] = launch
    r['facts'] = facts(r)
    return r


def deployer_history(deployer, token, head):
    topic = '0x' + deployer[2:].rjust(64, '0')
    filters = []
    for lo in range(FIRST_BLOCK, head + 1, LOG_WINDOW):
        filters.append({'address': FACTORY, 'topics': [TOKEN_LAUNCHED, None, None, topic],
                        'fromBlock': hex(lo), 'toBlock': hex(min(lo + LOG_WINDOW - 1, head))})
    res = post([{'jsonrpc': '2.0', 'id': i, 'method': 'eth_getLogs', 'params': [f]} for i, f in enumerate(filters)])
    if not isinstance(res, list) or len(res) != len(filters) or any(not isinstance(x.get('result'), list) for x in res):
        # Fall back to one window at a time; the public RPC sometimes refuses a heavy batch.
        logs = []
        for f in filters:
            logs += rpc('eth_getLogs', [f])
    else:
        logs = [log for x in sorted(res, key=lambda x: x['id']) for log in x['result']]
    return history(logs, deployer, token)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('token')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    token = a.token.strip()
    if not ADDRESS.match(token):
        print('PONS_CHECK_BAD_TARGET: expected 0x + 40 hex', file=sys.stderr)
        return 3
    try:
        r = check(token.lower())
    except (RpcError, ValueError) as e:
        print(f'PONS_CHECK_RPC_DOWN: {e}', file=sys.stderr)
        return 2
    print(json.dumps(r, indent=1, ensure_ascii=False) if a.json else to_markdown(r))
    return 0


if __name__ == '__main__':
    sys.exit(main())
