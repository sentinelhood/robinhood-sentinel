#!/usr/bin/env python3
"""Read-only, fixed-block SNTL burn snapshot. No credentials or transactions.

Run: python3 scripts/snapshot-burn.py
Only replaces public/burn.json after all checks pass.
"""
import json
import http.client
import os
from pathlib import Path
import tempfile
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RPC = 'https://rpc.mainnet.chain.robinhood.com'
TOKEN = '0x2da80b9D1bc1B323693C80C76eb4a321ec08CbD0'
START = 93500000
WINDOW = 10_000_000
TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
ZERO = '0x' + '0' * 64


def rpc(method, params):
    # The public RPC answers 429 to bursts; retry a few times before giving up on this run.
    for attempt in range(5):
        req = Request(RPC, json.dumps(dict(jsonrpc='2.0', id=1, method=method, params=params)).encode(),
                      {'Content-Type': 'application/json', 'User-Agent': 'Sentinel/1.0 (read-only snapshot)', 'Accept': 'application/json'})
        try:
            with urlopen(req, timeout=60) as response:
                result = json.load(response)
        except HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < 4:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except (URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            # Socket timeouts and dropped connections are transient on the public RPC too.
            if attempt < 4:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        if (result.get('error') or {}).get('code') == 429 and attempt < 4:
            time.sleep(2 * (attempt + 1))
            continue
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result['result']


def main():
    assert int(rpc('eth_chainId', []), 16) == 4663, 'Wrong chain'
    # A small confirmation buffer; all reads remain pinned to this block.
    block = int(rpc('eth_blockNumber', []), 16) - 20
    assert block >= START
    tag = hex(block)
    header = rpc('eth_getBlockByNumber', [tag, False])
    def call(data, at=tag):
        return int(rpc('eth_call', [{'to': TOKEN, 'data': data}, at]), 16)
    assert call('0x313ce567') == 18, 'Unexpected decimals'
    # START is the known prelaunch block; the public RPC prunes old contract state.
    # Log coverage and exact supply reconciliation are required below instead.
    remaining = call('0x18160ddd')
    minted = burned = mint_count = 0
    burns = []
    seen = set()
    # With an address + topic filter the public RPC accepts 10M-block ranges (it caps at 10k logs,
    # far above this token's mint/burn count), so one window covers ~12 days per call.
    for start in range(START, block + 1, WINDOW):
        end = min(start + WINDOW - 1, block)
        # Filter mint and burn separately to avoid a potentially truncated full transfer history.
        for kind, topics in [('mint', [TRANSFER, ZERO]), ('burn', [TRANSFER, None, ZERO])]:
            logs = rpc('eth_getLogs', [{'address': TOKEN, 'fromBlock': hex(start), 'toBlock': hex(end), 'topics': topics}])
            for log in logs:
                ts = log['topics']
                if len(ts) != 3:
                    continue
                assert not log.get('removed', False)
                assert log['address'].lower() == TOKEN.lower() and ts[0].lower() == TRANSFER
                assert start <= int(log['blockNumber'], 16) <= end
                assert len(log['data']) == 66
                assert ts[1 if kind == 'mint' else 2].lower() == ZERO
                key = (kind, log['transactionHash'], log['logIndex'])
                assert key not in seen, 'Duplicate log'
                seen.add(key)
                amount = int(log['data'], 16)
                if kind == 'mint':
                    minted += amount
                    mint_count += 1
                else:
                    burned += amount
                    burns.append(dict(tx=log['transactionHash'], block=int(log['blockNumber'], 16),
                                      logIndex=int(log['logIndex'], 16), amountRaw=str(amount)))
    assert minted > 0 and minted - burned == remaining, 'Supply reconciliation failed'
    assert rpc('eth_getBlockByNumber', [tag, False])['hash'] == header['hash'], 'Block changed during scan'
    snapshot = dict(chainId=4663, token=TOKEN, decimals=18, fromBlock=START, block=block,
                    blockHash=header['hash'], timestamp=datetime.fromtimestamp(int(header['timestamp'], 16), timezone.utc).isoformat(),
                    generatedAt=datetime.now(timezone.utc).isoformat(), mintedRaw=str(minted),
                    burnedRaw=str(burned), remainingRaw=str(remaining), mintEventCount=mint_count,
                    burnEventCount=len(burns), latestBurns=sorted(burns, key=lambda x: (x['block'], x['logIndex']), reverse=True)[:5])
    target = Path(__file__).resolve().parents[1] / 'public' / 'burn.json'
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, delete=False) as output:
            name = output.name
            json.dump(snapshot, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    print(json.dumps(snapshot, indent=2))


if __name__ == '__main__':
    main()