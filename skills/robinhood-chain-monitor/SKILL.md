---
name: robinhood-chain-monitor
description: Watch Robinhood Chain (chainId 4663) addresses for balance, nonce and bytecode changes - keyless, read-only, block-stamped
metadata:
  title: Robinhood Chain Monitor
  category: crypto
  var: ""
  tags:
    - crypto
    - robinhood-chain
  requires: []
  capabilities:
    - read_only
    - sends_notifications
---

> **${var}** - Watch label to check. Empty = all watches.

Fills a gap in `onchain-monitor`, which does not support Robinhood Chain. Reads each watched address at one block, diffs it against the last run, and alerts only when something changed. Keyless. Never signs or broadcasts.

## Network note

One data source: the official public RPC `https://rpc.mainnet.chain.robinhood.com`, called with plain `curl`. `./secretcurl` is not needed because no secret is involved. The watch list is sent to that RPC and nowhere else.

Use only these read methods: `eth_chainId`, `eth_blockNumber`, `eth_getBalance`, `eth_getTransactionCount` and `eth_getCode`. Never call a method that sends or signs anything.

```bash
rpc() { curl -sf -X POST https://rpc.mainnet.chain.robinhood.com -H 'Content-Type: application/json' \
  --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}"; }
```

## Config

Reads `memory/robinhood-watches.yml`. If it is missing or `watches: []`, log `RH_NO_CONFIG` and exit cleanly. An empty config is not an error, so do not send an alert.

```yaml
# memory/robinhood-watches.yml
watches:
  - label: Treasury
    address: "0x1234...abcd"
    min_change_eth: 0.01     # alert only when |balance delta| >= this (default 0.01)
```

Skip any watch whose `address` does not match `^0x[0-9a-fA-F]{40}$` and name it in the log.

## Steps

1. **Pin the block.** Run `rpc eth_chainId '[]'` and `rpc eth_blockNumber '[]'`.
   - If either call fails, or the chain ID is not `0x1237` (4663), log `RH_RPC_DOWN` and exit without alerting. A broken RPC must never look like "no activity".
   - Keep the returned block number as `<blockHex>`. Every read below uses it, so that all watches are compared at the same block.
2. **Snapshot each watch** (apply the `${var}` filter if set):
   - `rpc eth_getBalance '["<address>","<blockHex>"]'` → `balanceWei`
   - `rpc eth_getTransactionCount '["<address>","<blockHex>"]'` → `nonce`
   - `rpc eth_getCode '["<address>","<blockHex>"]'` → `codeBytes` = `(len(code) - 2) / 2`
   - Values come back as hex; convert them to integers. A response with an `error` field counts as a failed read for that watch.
   - Wait at least 1 second between addresses, because the RPC is shared.
3. **Diff** each snapshot against `memory/robinhood-state.json` (keyed by lowercase address):
   - `nonce` increased → the address sent that many transactions.
   - `|balanceWei delta| >= min_change_eth` → the balance moved. Report the delta in ETH with 6 decimals.
   - `codeBytes` changed → **high priority**: bytecode appeared, disappeared or changed size.
   - On the first sighting, store a baseline only. Do not alert.
4. **Persist** the new snapshots, including `block` and `checkedAt` (from `date -u +%FT%TZ`), to `memory/robinhood-state.json`, but only for watches that were read successfully. Write a tempfile first and then `mv` it into place, so that a failed run cannot corrupt state.
5. **Notify** through `./notify` only when at least one watch changed. Never call a channel API directly. Format:
   ```
   Robinhood Chain · block <n>
   • <label>: sent <k> tx · balance <+/-x.xxxxxx> ETH
     https://robinhoodchain.blockscout.com/address/<address>
   ```
   If nothing changed, do not notify.
6. **Log** to `memory/logs/YYYY-MM-DD.md` under `### robinhood-chain-monitor`, as bullet points: the outcome (`RH_CHANGED`, `RH_QUIET`, `RH_NO_CONFIG` or `RH_RPC_DOWN`), followed by `block <n> · <ok>/<total> watches read`.

## Hard limits

- Read-only on chain. Never sign, never broadcast, never ask for or store a key.
- Native ETH only. Do not report token balances or USD values: these RPC reads do not provide them.
- Never describe an address or contract as "safe". Bytecode presence is not an audit.
- Every reported number carries the block it was read at.
