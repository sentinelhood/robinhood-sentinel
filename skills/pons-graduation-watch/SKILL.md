---
name: pons-graduation-watch
description: Alert when a Pons v2 token on Robinhood Chain graduates from its bonding curve to a locked Uniswap v4 pool, with the amount moved into the pool and the day's graduation rate - all tokens or only ones you watch, keyless, read-only
metadata:
  title: Pons Graduation Watch
  category: crypto
  var: "Comma-separated token or deployer addresses to watch. Empty = report every graduation."
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

> **${var}** - Comma-separated token or deployer addresses. A token entry alerts when that token graduates; a deployer entry alerts when any token it made graduates. Empty = every graduation is reported.

Every Pons v2 token starts on a bonding curve. When the curve fills, the factory moves the raised quote and the reserved tokens into a Uniswap v4 pool with locked liquidity. That moment changes how the token trades, and it is rare: about 1 in 100 launches gets there. `pons-token-check` shows the phase of one token on demand, and `pons-deployer-watch` reports new launches, but neither tells you when a curve fills. This skill reads the factory's graduation events and reports each one once.

## Config

Optional `memory/state/pons-graduation-watch.yml`, used when `${var}` is empty:

```yaml
watch:
  - 0x57c140bfe79001d29c3d1108f461bd977198480f   # a token
  - 0x45cde31e37365c5cd378135e93bea0d0f89cb9d5   # or a deployer
```

## Network note

Public, unauthenticated reads only. `./secretcurl` is not needed because no secret is involved.

- `https://rpc.mainnet.chain.robinhood.com` - the official RPC, called only with `eth_chainId`, `eth_blockNumber`, `eth_getLogs` on the Pons v2 factory `0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e` (from docs.ponsfamily.com/v2#contracts) and `eth_call` (`getLaunchedToken` on the factory; `name()`, `symbol()`, `decimals()` on the token and its pair).
- Graduation event topic `0xcdb72f157fd3666758a6ce201387ffb52038c7562e4fff352828da1096c4b6b4`: topic 1 is the token, data is the quote amount and the token amount moved into the pool. Checked on 2026-10-25: every token that emitted it in the previous 2.8 days (21 of 21) read phase 2, `Uniswap v4 pool, liquidity locked`, from the factory.

The helper `skills/pons-graduation-watch/pons_graduation_watch.py` uses the Python standard library only. It halves log ranges that hit the 10k-log cap, sends `eth_call`s in batches of 50, pins every call to one block, and backs off on 429s.

## Steps

1. **Resolve inputs.** Watch list = `${var}` if set, otherwise `watch` from the config. Every entry must be `0x` + 40 hex. An empty list reports every graduation.
2. **Run the helper:**
   ```bash
   python3 skills/pons-graduation-watch/pons_graduation_watch.py --watch "${var}" \
     --state memory/state/pons-graduation-watch.json --hours 24 > .pons-graduation-watch.md
   ```
   - One run reads a day of graduation and launch logs in a few seconds.
   - The first run, or a run with a changed watch list, reports graduations in the whole window. Later runs report only graduations after the last scanned block. Each graduation is reported once.
   - Exit code `2` (stderr `PONS_GRAD_RPC_DOWN`) means the RPC was unreachable or reported the wrong chain. Log it and stop without notifying. The state file is left untouched.
   - Exit code `3` (stderr `PONS_GRAD_BAD_WATCH`) means a watch entry was malformed. Log it and stop.
3. **Notify** with `./notify -f .pons-graduation-watch.md` only when the output starts with `NEW PONS GRADUATIONS`. On a quiet run, do not notify. Never call a channel API directly.
4. **Log** to `memory/logs/YYYY-MM-DD.md` under `### pons-graduation-watch`: `PONS_GRAD_NEW <n>` or `PONS_GRAD_QUIET`, then the summary line (`<graduated> graduated · <launched> launched`).

## Reading the output

- **NEW PONS GRADUATIONS** - each token that graduated since the last run, newest first: symbol and name, how much quote went into the pool (ETH, USDG or another approved pair, with its own decimals), the deployer, the phase the factory reports now, and an explorer link.
- **graduated · launched** - graduations and launches in the window, and the share of launches that graduated. Launches in the window are not the same tokens as graduations in the window; the share is a rate, not a cohort.

## Hard limits

- Read-only on chain. Never sign, never broadcast, never ask for or store a key.
- Never call a token a scam, rug or honeypot, and never tell anyone to buy or sell. Graduation is a fact about the curve, not a quality signal.
- Only Pons v2 graduations are covered. Tokens deployed any other way are not seen.
