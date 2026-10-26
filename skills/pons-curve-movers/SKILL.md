---
name: pons-curve-movers
description: The most active Pons v2 bonding curves on Robinhood Chain in the last few hours - buys, sells, distinct traders, volume, net flow and progress toward graduation, for tokens DEX scanners cannot see yet - keyless, read-only
metadata:
  title: Pons Curve Movers
  category: crypto
  var: "Window in hours, 1-24. Empty = 6."
  tags:
    - crypto
    - robinhood-chain
    - pons
    - market
  requires: []
  capabilities:
    - read_only
    - sends_notifications
---

> **${var}** - Window in hours, from 1 to 24. Empty = 6.

A Pons v2 token trades on its own bonding curve until the curve fills. Until then it has no DEX pair, so market scanners that read DEX pools do not list it: on 2026-10-26 DexScreener returned no pair for an actively traded curve token, and GeckoTerminal does not list Robinhood Chain. About 99 in 100 Pons launches never leave the curve. Aeon's `token-movers` reads CoinGecko and GeckoTerminal, so this activity is invisible to it. This skill reads every curve trade on chain and ranks the busiest curves.

## Network note

Public, unauthenticated reads only. `./secretcurl` is not needed because no secret is involved.

- `https://rpc.mainnet.chain.robinhood.com` - the official RPC, called only with `eth_chainId`, `eth_blockNumber`, `eth_getLogs` (curve Buy and Sell events) and `eth_call` (`token()` and `getReserves()` on curves, `getLaunchedToken` on the Pons v2 factory `0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e`, from docs.ponsfamily.com/v2#contracts; `totalSupply()`, `name()`, `symbol()`, `decimals()`).
- Curve events: Buy `0xec36bf57…c455` (quote in, tokens out, fee 1, fee 2) and Sell `0x8113d738…59df` (tokens in, quote out, fee 1, fee 2). Checked on 2026-10-26: summing buys minus sells and fees over every trade on a curve equals its real quote reserve, and two graduated curves reached their factory threshold in the buy that graduated them.
- Any contract can emit the same events. Before a curve is ranked, the helper asks it for its `token()` and keeps it only if the Pons factory records that exact curve for that token. Skipped emitters are counted in the output.

The helper `skills/pons-curve-movers/pons_curve_movers.py` uses the Python standard library only. The RPC allows 30,000 blocks per log request without an address filter, so a 6-hour window takes about 15 requests per event and a few seconds to half a minute. It halves ranges that hit the log cap, batches `eth_call`s by 50, pins them to one block, and backs off on 429s.

## Steps

1. **Run the helper:**
   ```bash
   python3 skills/pons-curve-movers/pons_curve_movers.py --hours "${var:-6}" --top 10 > .pons-curve-movers.md
   ```
   - Exit code `2` (stderr `PONS_MOVERS_RPC_DOWN`) means the RPC was unreachable or reported the wrong chain. Log it and stop without notifying.
   - Exit code `3` (stderr `PONS_MOVERS_BAD_INPUT`) means the window was outside 1-24 hours. Log it and stop.
2. **Notify** with `./notify -f .pons-curve-movers.md` when it lists at least one curve. Never call a channel API directly.
3. **Log** to `memory/logs/YYYY-MM-DD.md` under `### pons-curve-movers`: the summary line (`<trades> curve trades on <curves> curves`) and the top three symbols.

## Reading the output

- **buys / sells** - curve trades in the window. The list is ranked by trade count, then distinct traders, so curves priced in different pair tokens compare fairly.
- **traders** - distinct recipient addresses. One person can use many wallets, so this is an upper bound on people, not a count of them.
- **traded / net** - quote moved by trades before fees, and the change in the curve's real quote reserve. A large volume with a net near zero means trades mostly offset each other.
- **% to graduation** - quote raised so far divided by the threshold the factory records for that curve. Graduated curves show their phase instead.

## Hard limits

- Read-only on chain. Never sign, never broadcast, never ask for or store a key.
- Never call a token a scam, rug, honeypot or gem, and never tell anyone to buy or sell. Activity is a fact about the curve, not a quality signal.
- Only Pons v2 curves are covered.
