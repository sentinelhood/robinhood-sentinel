---
name: pons-launch-watch
description: Alert when a new Pons v2 launch on Robinhood Chain copies your token's ticker or name, plus a daily read of launch volume, repeated tickers and the busiest deployers - keyless, read-only
metadata:
  title: Pons Launch Watch
  category: crypto
  var: ""
  tags:
    - crypto
    - robinhood-chain
    - pons
    - scam-watch
  requires: []
  capabilities:
    - read_only
    - sends_notifications
---

> **${var}** - Comma-separated tickers or names to guard, e.g. `SNTL,Sentinel`. Empty = summary only, no lookalike alerts.

Pons v2 is the busiest launchpad on Robinhood Chain: about 1,700 launches a day, and roughly half of them reuse a ticker another launch already took. Anyone can launch with any name and symbol, so a project's ticker is copied within minutes of it trending. This skill reads every new launch from the Pons v2 factory and alerts when one matches a ticker or name you guard, so you can warn your community before someone buys the copy.

## Config

Optional `memory/state/pons-launch-watch.yml`:

```yaml
watch: [SNTL, Sentinel]          # used when ${var} is empty
official:                        # your real token address(es), never flagged
  - 0x2da80b9D1bc1B323693C80C76eb4a321ec08CbD0
```

Without `official`, your own token is reported as a lookalike on the first run. Add it.

## Network note

Public, unauthenticated reads only. `./secretcurl` is not needed because no secret is involved.

- `https://rpc.mainnet.chain.robinhood.com` - the official RPC, called only with `eth_chainId`, `eth_blockNumber`, `eth_getLogs` on the Pons v2 factory (`0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e`, from docs.ponsfamily.com/v2#contracts) and `eth_call` for `name()` / `symbol()` on each new token.

The helper `skills/pons-launch-watch/pons_launch_watch.py` uses the Python standard library only. It sends `eth_call`s in JSON-RPC batches of 50, halves log ranges that hit the 10k-log cap, and backs off on 429s.

## Steps

1. **Resolve inputs.** Watch terms = `${var}` if set, otherwise `watch` from the config. Official addresses = `official` from the config. Each official address must be `0x` + 40 hex.
2. **Run the helper:**
   ```bash
   python3 skills/pons-launch-watch/pons_launch_watch.py --watch "SNTL,Sentinel" \
     --official 0x2da80b9D1bc1B323693C80C76eb4a321ec08CbD0 \
     --state memory/state/pons-launch-watch.json --hours 24 > .pons-launch-watch.md
   ```
   - The first run reads every launch in the last 24 hours (about 1,700 tokens, roughly one minute). Later runs read only launches after the last scanned block and finish in a few seconds.
   - Matching is case-insensitive and ignores `$`, spaces, punctuation and full-width characters, so `$sntl`, `S.N.T.L` and `ＳＮＴＬ` all match `SNTL`. It is an exact match after that: `SNTL2` does not match.
   - Exit code `2` (stderr `PONS_WATCH_RPC_DOWN`) means the RPC was unreachable or reported the wrong chain. Log it and stop without notifying. The state file is left untouched, so the next run catches up.
   - Stderr `PONS_WATCH_BAD_OFFICIAL` means an official address was malformed. Log it and stop.
3. **Notify** with `./notify -f .pons-launch-watch.md` only when the output starts with `LOOKALIKE LAUNCHES`. Each lookalike is reported once: the state file remembers what was sent. On a quiet run, do not notify. Never call a channel API directly.
4. **Log** to `memory/logs/YYYY-MM-DD.md` under `### pons-launch-watch`, as bullet points: `PONS_WATCH_LOOKALIKE <n>` or `PONS_WATCH_QUIET`, then the summary line (`<launches> launches · <distinct> distinct tickers · <shared> share a ticker`).

## Reading the output

- **LOOKALIKE** - a Pons v2 token whose symbol or name equals a guarded term and whose address is not official. It is a copy of the name, not proof of a scam: someone else may simply have picked the same ticker.
- **share a ticker** - launches in the window whose symbol is also used by at least one other launch in the window.
- **Busiest deployers** - addresses with at least 10 launches in the window. Many launches is not proof of bad intent.

## Hard limits

- Read-only on chain. Never sign, never broadcast, never ask for or store a key.
- Never call a token a scam, rug or honeypot, and never tell anyone to buy or sell. Report the match, the address and the deployer.
- Only Pons v2 launches are covered. Tokens deployed any other way are not seen.
