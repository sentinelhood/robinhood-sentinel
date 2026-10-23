#!/usr/bin/env python3
"""Sentinel Guard snapshot for public/guards.json. Read-only and keyless.

A Pons v2 deployer guards one of its tokens by burning SNTL from the deployer wallet with the
token address appended to the calldata:

    to:   SNTL 0x2da80b9D1bc1B323693C80C76eb4a321ec08CbD0
    data: 0x42966c68 <uint256 amount> <token address, left-padded to 32 bytes>

burn(uint256) ignores the trailing word, so the tokens are simply destroyed: nobody, including
Sentinel, receives them. Each qualifying burn of at least MIN_BURN SNTL adds PERIOD_DAYS of
guard. A burn counts only when the transaction sender is the deployer recorded by the Pons
factory for that token. Guarded tokens are checked for ticker or name copies in the last 24h
of launches, using the pons-launch-watch skill's cache.

Run: python3 scripts/snapshot-guards.py [state-file]
Only replaces public/guards.json after every read succeeds.
"""
import json, os, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills' / 'pons-launch-watch'))
import pons_launch_watch as plw  # noqa: E402

SNTL = '0x2da80b9d1bc1b323693c80c76eb4a321ec08cbd0'
FROM_BLOCK = 95_225_000          # program start; earlier burns never count
MIN_BURN = 1_000_000 * 10 ** 18  # per period
PERIOD = 30 * 86400
HOURS = 24
TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
ZERO_WORD = '0x' + '0' * 64
BURN_SEL = '0x42966c68'
GET_LAUNCHED = '0x3cf28b5a'
WINDOW = 10_000_000


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace('+00:00', 'Z')


def parse_guard_call(tx):
    """(amount, token) when tx is burn(amount) on SNTL with exactly one appended address word."""
    data = (tx.get('input') or '').lower()
    if (tx.get('to') or '').lower() != SNTL or not data.startswith(BURN_SEL) or len(data) != 10 + 128:
        return None
    word = data[74:]
    if word[:24] != '0' * 24 or word[24:] == '0' * 40:
        return None
    return int(data[10:74], 16), '0x' + word[24:]


def decide(burns, deployers, now):
    """Fold qualifying burns into guards. burns: dicts with tx, from, token, amount, ts, block (time order).
    deployers: token -> factory deployer (None = not a Pons token). Returns (guards, rejected)."""
    guards, rejected = {}, []
    for b in sorted(burns, key=lambda b: (b['block'], b['tx'])):
        dep = deployers.get(b['token'])
        reason = ('official token is always watched' if b['token'] == SNTL else
                  'not a Pons v2 token' if not dep else
                  'sender is not the token deployer' if dep != b['from'] else
                  'below the 1,000,000 SNTL minimum' if b['amount'] < MIN_BURN else None)
        if reason:
            rejected.append({'tx': b['tx'], 'token': b['token'], 'reason': reason})
            continue
        g = guards.setdefault(b['token'], {'token': b['token'], 'deployer': dep, 'burnedRaw': 0, 'burns': 0,
                                           'since': iso(b['ts']), 'expiresTs': 0, 'lastTx': None})
        # Each burn adds one period, starting from now or from the current expiry, whichever is later.
        g['expiresTs'] = max(g['expiresTs'], b['ts']) + PERIOD
        g['burnedRaw'] += b['amount']
        g['burns'] += 1
        g['lastTx'] = b['tx']
    out = []
    for g in guards.values():
        out.append({**g, 'burnedRaw': str(g['burnedRaw']), 'expiresAt': iso(g['expiresTs']), 'active': g['expiresTs'] > now})
        del out[-1]['expiresTs']
    return sorted(out, key=lambda g: (not g['active'], g['since'])), rejected[-10:]


def read_burns(head):
    logs = []
    for lo in range(FROM_BLOCK, head + 1, WINDOW):
        logs += plw.rpc('eth_getLogs', [{'address': SNTL, 'topics': [TRANSFER, None, ZERO_WORD],
                                         'fromBlock': hex(lo), 'toBlock': hex(min(lo + WINDOW - 1, head))}])
    logs = [l for l in logs if len(l['topics']) == 3 and not l.get('removed')]
    hashes = sorted({l['transactionHash'] for l in logs})
    txs = {}
    for i in range(0, len(hashes), plw.BATCH):
        chunk = hashes[i:i + plw.BATCH]
        res = plw.post([{'jsonrpc': '2.0', 'id': j, 'method': 'eth_getTransactionByHash', 'params': [h]} for j, h in enumerate(chunk)])
        if not isinstance(res, list) or any('result' not in r or not r['result'] for r in res):
            raise plw.RpcError('transaction batch refused')
        for r in res:
            txs[chunk[r['id']]] = r['result']
    burns = []
    for l in logs:
        tx = txs[l['transactionHash']]
        call = parse_guard_call(tx)
        sender = '0x' + l['topics'][1][26:].lower()
        # burn() destroys msg.sender's tokens, so the burned-from address must be the tx sender.
        if not call or sender != tx['from'].lower():
            continue
        ts = int(l.get('blockTimestamp') or plw.rpc('eth_getBlockByNumber', [l['blockNumber'], False])['timestamp'], 16)
        burns.append({'tx': l['transactionHash'].lower(), 'from': sender, 'token': call[1], 'amount': int(l['data'], 16),
                      'ts': ts, 'block': int(l['blockNumber'], 16)})
    return burns


def read_deployers(tokens):
    out = {}
    for t in tokens:
        rec = plw.rpc('eth_call', [{'to': plw.FACTORY, 'data': GET_LAUNCHED + t[2:].rjust(64, '0')}, 'latest'])[2:]
        words = [rec[i:i + 64] for i in range(0, len(rec), 64)]
        out[t] = ('0x' + words[2][24:]) if len(words) >= 3 and int(words[0], 16) else None
    return out


def main():
    state = Path(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/.cache/sentinel/pons-launch-watch.json'))
    state.parent.mkdir(parents=True, exist_ok=True)
    assert int(plw.rpc('eth_chainId', []), 16) == 4663, 'wrong chain'
    head = int(plw.rpc('eth_blockNumber', []), 16) - 20
    burns = read_burns(head)
    tokens = sorted({b['token'] for b in burns})
    guards, rejected = decide(burns, read_deployers(tokens), datetime.now(timezone.utc).timestamp())

    launches, window = 0, None
    if any(g['active'] for g in guards):
        run = subprocess.run([sys.executable, str(ROOT / 'skills/pons-launch-watch/pons_launch_watch.py'),
                              '--state', str(state), '--hours', str(HOURS), '--json'], capture_output=True, text=True)
        if run.returncode != 0:
            sys.stderr.write(run.stderr)
            return run.returncode or 1
        report = json.loads(run.stdout)
        launches = report['launches']
        window = [dict(zip(plw.SEEN_KEYS, r)) for r in json.loads(state.read_text())['seen']]
    meta = plw.read_metadata([g['token'] for g in guards]) if guards else {}
    for g in guards:
        g['symbol'] = meta.get(g['token'], {}).get('symbol') or None
        g['name'] = meta.get(g['token'], {}).get('name') or None
        if g['active']:
            terms = [t for t in (g['symbol'], g['name']) if t and plw.normalise(t)]
            hits = sorted(plw.find_lookalikes(window, terms, {g['token']}), key=lambda h: -h['block']) if terms else []
            g['copyCount'] = len(hits)
            g['copies'] = [{k: h[k] for k in ('token', 'deployer', 'block', 'symbol', 'name')} for h in hits[:5]]
        else:
            g['copyCount'], g['copies'] = 0, []

    out = {
        'chainId': 4663, 'token': SNTL, 'fromBlock': FROM_BLOCK, 'block': head,
        'generatedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'minBurnRaw': str(MIN_BURN), 'periodDays': PERIOD // 86400, 'windowHours': HOURS, 'launches': launches,
        'guards': guards, 'rejected': rejected,
        'source': 'SNTL burn logs + Pons v2 factory via rpc.mainnet.chain.robinhood.com',
    }
    target = ROOT / 'public' / 'guards.json'
    with tempfile.NamedTemporaryFile('w', dir=target.parent, delete=False) as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write('\n')
    os.replace(f.name, target)
    active = sum(g['active'] for g in guards)
    print(f"public/guards.json · block {head:,} · {active} active guard(s), {len(rejected)} rejected burn(s)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
