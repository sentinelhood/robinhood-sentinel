---
name: pons-deployer-watch
description: Alert when a deployer you watch launches a new token on Pons v2 (Robinhood Chain), plus the busiest deployers of the day - watch by deployer or by any token they made, keyless, read-only
metadata:
  title: Pons Deployer Watch
  category: crypto
  var: "Comma-separated deployer or token addresses to watch (a token address watches the wallet that deployed it). Empty = busiest-deployers summary only."
  tags:
    - crypto
    - robinhood-chain
    - pons
    - due-diligence
  requires: []
  capabilities:
    - read_only
    - sends_notifications
---

> **${var}** - Comma-separated deployer or token addresses to watch. A token address is resolved to the deployer the Pons factory records for it. Empty = busiest-deployers summary only, no alerts.

On Pons v2, one wallet can launch hundreds of tokens: the busiest deployers ship a new one every few minutes. If you hold a token, the next thing its deployer launches is worth knowing. Aeon's `onchain-monitor` watches balances and transfers, not launches, so a new token from the same wallet goes unnoticed. This skill reads every Pons v2 launch in the window and alerts when one comes from a deployer you watch.

## Config

Optional `memory/state/pons-deployer-watch.yml`, used when `${var}` is empty:

```yaml
watch:
  - 0x57c140bfe79001d29c3d1108f461bd977198480f   # a token: watches its deployer
  - 0x45cde31e37365c5cd378135e93bea0d0f89cb9d5   # or a deployer directly
```

## Network note

Public, unauthenticated reads only. `./secretcurl` is not needed because no secret is involved.

- `https://rpc.mainnet.chain.robinhood.com` - the official RPC, called only with `eth_chainId`, `eth_blockNumber`, `eth_getLogs` (`TokenLaunched` on the Pons v2 factory `0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e`, from docs.ponsfamily.com/v2#contracts) and `eth_call` (`getLaunchedToken` on the factory to resolve a token to its deployer, `name()` / `symbol()` on matched launches).

The helper `skills/pons-deployer-watch/pons_deployer_watch.py` uses the Python standard library only. It halves log ranges that hit the 10k-log cap, sends `eth_call`s in batches of 50, and backs off on 429s.

## Steps

1. **Resolve inputs.** Watch list = `${var}` if set, otherwise `watch` from the config. Every entry must be `0x` + 40 hex.
2. **Run the helper:**
   ```bash
   python3 skills/pons-deployer-watch/pons_deployer_watch.py --watch "0x57c1...480f,0x45cd...b9d5" \
     --state memory/state/pons-deployer-watch.json --hours 24 > .pons-deployer-watch.md
   ```
   - One run reads about a day of launches (roughly 1,500 logs) in a few seconds.
   - The first run, or a run with a changed watch list, reports launches by watched deployers in the whole window. Later runs report only launches after the last scanned block. Each launch is reported once.
   - Exit code `2` (stderr `PONS_DEPLOYER_RPC_DOWN`) means the RPC was unreachable or reported the wrong chain. Log it and stop without notifying. The state file is left untouched.
   - Exit code `3` (stderr `PONS_DEPLOYER_BAD_WATCH`) means a watch entry was malformed. Log it and stop.
3. **Notify** with `./notify -f .pons-deployer-watch.md` only when the output starts with `NEW LAUNCHES BY WATCHED DEPLOYERS`. On a quiet run, do not notify. Never call a channel API directly.
4. **Log** to `memory/logs/YYYY-MM-DD.md` under `### pons-deployer-watch`: `PONS_DEPLOYER_NEW <n>` or `PONS_DEPLOYER_QUIET`, then the summary line (`<launches> launches from <deployers> deployers`).

## Reading the output

- **NEW LAUNCHES BY WATCHED DEPLOYERS** - tokens created through the Pons v2 factory by a wallet you watch, newest first, with an explorer link each.
- **Watching** - each watched deployer, the token it was resolved from (if you gave a token), and its launches in the window.
- **Busiest** - the deployers with the most launches in the window. Many launches is not proof of bad intent.

## Hard limits

- Read-only on chain. Never sign, never broadcast, never ask for or store a key.
- Never call a deployer or token a scam, rug or honeypot, and never tell anyone to buy or sell. Report the launch, the address and the deployer.
- Only Pons v2 launches are covered. Tokens deployed any other way are not seen.
