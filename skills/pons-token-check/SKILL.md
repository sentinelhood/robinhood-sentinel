---
name: pons-token-check
description: One-shot check of any token on Robinhood Chain - Pons v2 launch record, real trading cost (base fee + creator tax), phase, deployer's full launch history and what the deployer holds - keyless, read-only, block-stamped
metadata:
  title: Pons Token Check
  category: crypto
  var: "Token contract address on Robinhood Chain (0x + 40 hex). Required."
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

> **${var}** - Token contract address on Robinhood Chain (`0x` + 40 hex). Required. If empty or malformed, log `PONS_CHECK_BAD_TARGET` and exit without notifying.

Aeon's token skills (`investigation-report`, `tx-explain`, `token-movers`) read Base and other major chains. None of them reads Robinhood Chain or the Pons v2 launchpad, where most of the chain's new tokens are created. This skill answers the questions people ask before buying a fresh Robinhood Chain token, straight from the chain, in one run:

- Was it launched through Pons v2, and is it still on the bonding curve or in a locked Uniswap v4 pool?
- What does a trade really cost (Pons base fee + the creator tax set at launch)?
- Who deployed it, how many Pons tokens has that address launched, and is this one of many?
- How much of the supply do the deployer and fee recipient hold right now?

## Network note

Public, unauthenticated reads only. `./secretcurl` is not needed because no secret is involved.

- `https://rpc.mainnet.chain.robinhood.com` - the official RPC, called only with `eth_chainId`, `eth_blockNumber`, `eth_getCode`, `eth_call` (`name`, `symbol`, `decimals`, `totalSupply`, `balanceOf`, the Pons factory's `getLaunchedToken`, the curve's fee) and `eth_getLogs` (`TokenLaunched` on the Pons v2 factory `0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e`, from docs.ponsfamily.com/v2#contracts, filtered by deployer).

The helper `skills/pons-token-check/pons_token_check.py` uses the Python standard library only. Every read is pinned to one block number, and that block is printed in the report.

## Steps

1. **Validate** `${var}`: `0x` + 40 hex. Otherwise log `PONS_CHECK_BAD_TARGET` and stop.
2. **Run the helper:**
   ```bash
   python3 skills/pons-token-check/pons_token_check.py "${var}" > .pons-token-check.md
   ```
   - Takes a few seconds: one batch of `eth_call`s and one batched `eth_getLogs` over the Pons history.
   - Exit code `2` (stderr `PONS_CHECK_RPC_DOWN`) means the RPC was unreachable or reported the wrong chain. Log it and stop without notifying.
   - Exit code `3` (stderr `PONS_CHECK_BAD_TARGET`) means the address was malformed.
   - `--json` prints the same facts as JSON for other skills to read.
3. **Notify** with `./notify -f .pons-token-check.md`. This skill runs on demand, so every successful run notifies once. Never call a channel API directly.
4. **Log** to `memory/logs/YYYY-MM-DD.md` under `### pons-token-check`: `PONS_CHECK <token> <symbol> phase=<n> tax=<bps> deployer_launches=<n>`.

## Reading the output

- **Phase** - `bonding curve` (0), `swept, pool pending` (1), `Uniswap v4 pool, liquidity locked` (2), `rescued` (3), as the Pons factory records it.
- **Trading cost** - Pons base fee read from the token's curve, plus the creator tax fixed at launch. Pons does not let the creator raise the tax later.
- **Deployer** - `wallet`, `wallet, EIP-7702 delegated` or `contract`, from the code at that address. Launch count covers every Pons v2 launch since the factory went live.
- **Facts worth a look** - plain facts only: creator tax, still on the curve, the deployer or fee recipient holding 5% or more, a deployer with 10 or more launches, no Pons record, not an ERC-20.

## Hard limits

- Read-only on chain. Never sign, never broadcast, never ask for or store a key.
- Never call a token a scam, rug or honeypot, and never tell anyone to buy or sell. Report the facts and the block they were read at.
- No Pons record does not mean unsafe, and a Pons record does not mean safe. Holdings are current balances only.
