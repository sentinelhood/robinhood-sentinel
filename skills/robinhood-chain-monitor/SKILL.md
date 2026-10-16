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

Fills a gap in `onchain-monitor`, which does not support Robinhood Chain. Uses the public Sentinel API (keyless, GET-only, no signing). Every value is read at a specific block, and that block number is reported with it.

## Network note

Public, unauthenticated GETs only. Use plain `curl` (or WebFetch). `./secretcurl` is not needed because no secret is involved. The API is open source at [sentinelhood/robinhood-sentinel](https://github.com/sentinelhood/robinhood-sentinel) (`api/service.js`). It rejects every non-GET method and every unknown action.

## Config

Reads `memory/robinhood-watches.yml`. If it is missing or `watches: []`, log `RH_NO_CONFIG` and exit cleanly. An empty config is not an error, so do not send an alert.

```yaml
# memory/robinhood-watches.yml
watches:
  - label: Treasury
    address: "0x1234...abcd"
    min_change_eth: 0.01     # alert only when |balance delta| >= this (default 0.01)
```

## Steps

1. **Network check.** `curl -sf "https://sentinelhood.com/api/service?action=network"`.
   If the call fails or `chainId != 4663`, log `RH_RPC_DOWN` and exit without alerting. A broken RPC must never look like "no activity".
2. **Snapshot each watch** (apply the `${var}` filter if set):
   `curl -sf "https://sentinelhood.com/api/service?action=address&value=<address>"`
   This returns `balanceWei`, `nonce`, `codeBytes` and `block`. Wait at least 1 second between calls, because the API is shared.
3. **Diff** each snapshot against `memory/robinhood-state.json` (keyed by lowercase address):
   - `nonce` increased → the address sent N transactions.
   - `|balanceWei delta| >= min_change_eth` → the balance moved. Report the delta in ETH with 6 decimals.
   - `codeBytes` changed → **high priority**: bytecode appeared, disappeared or changed.
   - On the first sighting, store a baseline only. Do not alert.
4. **Persist** the new snapshots to `memory/robinhood-state.json`, but only for watches that were read successfully.
5. **Notify** through `./notify` only when there is at least one change. Never call a channel API directly. Format:
   ```
   Robinhood Chain · block <n>
   • <label>: sent <k> tx · balance <+/-x.xxxxxx> ETH
     https://robinhoodchain.blockscout.com/address/<address>
   ```
   If nothing changed, log `RH_QUIET` and do not notify.

## Hard limits

- Read-only. Never sign, never broadcast, never ask for keys.
- Native ETH only. Do not report token balances or USD values: this API does not index them.
- Never describe a result as "safe". Bytecode presence is not an audit.
- Footer of every run log: `source: sentinel api · block <n> · <ok>/<total> watches read`.
