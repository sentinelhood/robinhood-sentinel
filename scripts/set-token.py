#!/usr/bin/env python3
"""Switch the site's official-token panel on (or off), after checking the contract on chain.

  python3 scripts/set-token.py 0xCA --symbol BOW --name Sentinel \
      --announcement https://x.com/sentinelhood/status/123 [--launchpad https://...]
  python3 scripts/set-token.py --unset

It only writes public/token.json. Publishing is a normal `git push` (Vercel deploys it).
It refuses to write unless: the address is well formed, the RPC reports chain 4663, the
address has contract bytecode, and the announcement is a @sentinelhood status URL.
"""
import argparse, json, re, sys, urllib.request
from pathlib import Path

RPC = 'https://rpc.mainnet.chain.robinhood.com'
OUT = Path(__file__).resolve().parents[1] / 'public' / 'token.json'


def rpc(method, params):
    req = urllib.request.Request(RPC, json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode(),
                                 {'Content-Type': 'application/json', 'User-Agent': 'sentinel-set-token/1.0'})
    body = json.load(urllib.request.urlopen(req, timeout=30))
    if 'error' in body:
        raise SystemExit(f"RPC error on {method}: {body['error']}")
    return body['result']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('address', nargs='?')
    ap.add_argument('--symbol')
    ap.add_argument('--name', default='Sentinel')
    ap.add_argument('--announcement', help='https://x.com/sentinelhood/status/<id> that names this address')
    ap.add_argument('--launchpad', help='optional https link to the launchpad page')
    ap.add_argument('--unset', action='store_true', help='switch the panel back to "Not live yet"')
    a = ap.parse_args()

    if a.unset:
        OUT.write_text(json.dumps({'live': False}, indent=2) + '\n')
        return print(f'{OUT.name}: live=false')

    if not a.address or not re.fullmatch(r'0x[0-9a-fA-F]{40}', a.address):
        raise SystemExit('address must be 0x + 40 hex characters')
    if not a.symbol or not re.fullmatch(r'[A-Z0-9]{2,10}', a.symbol):
        raise SystemExit('--symbol must be 2-10 uppercase letters or digits')
    if not a.announcement or not re.fullmatch(r'https://(x|twitter)\.com/sentinelhood/status/\d+', a.announcement):
        raise SystemExit('--announcement must be an https://x.com/sentinelhood/status/<id> link')
    if a.launchpad and not a.launchpad.startswith('https://'):
        raise SystemExit('--launchpad must be an https link')

    chain = int(rpc('eth_chainId', []), 16)
    if chain != 4663:
        raise SystemExit(f'RPC reports chain {chain}, expected 4663')
    block = rpc('eth_blockNumber', [])
    code = rpc('eth_getCode', [a.address, block])
    if len(code) <= 2:
        raise SystemExit(f'{a.address} has no contract bytecode on Robinhood Chain at block {int(block, 16):,}. Not writing.')

    data = {'live': True, 'name': a.name, 'symbol': a.symbol, 'address': a.address, 'chainId': 4663,
            'announcement': a.announcement, 'verifiedAtBlock': int(block, 16), 'codeBytes': (len(code) - 2) // 2}
    if a.launchpad:
        data['launchpad'] = a.launchpad
    OUT.write_text(json.dumps(data, indent=2) + '\n')
    print(f"{OUT.name}: live=true {a.symbol} {a.address} · {data['codeBytes']} bytes at block {data['verifiedAtBlock']:,}")
    print('Next: git add public/token.json && git commit -m "token: go live" && git push')


if __name__ == '__main__':
    main()
