---
name: pons-pool-check
description: For any Pons v2 token on Robinhood Chain, find its official Uniswap v4 pool from the factory record and the Pons hook, and list every other v4 pool made for the same token by anyone - fee, hook, liquidity and recent swaps - keyless, read-only
metadata:
  title: Pons Pool Check
  category: crypto
  var: "A Pons v2 token address (0x + 40 hex). Required."
  tags:
    - crypto
    - robinhood-chain
    - pons
    - uniswap-v4
    - due-diligence
  requires: []
  capabilities:
    - read_only
    - sends_notifications
---

> **${var}** - A Pons v2 token address. Required.

When a Pons v2 token graduates, its liquidity moves into one Uniswap v4 pool and is locked there for good. Uniswap v4 lets anyone create another pool for the same token, with any fee and any hook, and people do: on 2026-11-05, each of the 13 tokens that had graduated in the previous 24 hours also had other v4 pools, 137 between them. Most had no hook and a swap fee between 10% and 99.9%. A router or wallet that picks a pool by token pair alone can send a buyer into one of those.

This skill names the official pool from chain data, not from a list. It is the pool whose PoolKey uses the Pons meme hook, the `poolFee` and `tickSpacing` the factory recorded for the token, and the token with its recorded pair token, sorted. The same rule is in the Pons docs (docs.ponsfamily.com/v2#uniswap-v4). Every other v4 pool for the token is listed beside it.

`pons-token-check` reports the launch record, `pons-graduation-watch` reports the moment a token graduates, and nothing reported what happens after that. This does.

## Network note

Public, unauthenticated reads only. `./secretcurl` is not needed because no secret is involved.

- `https://rpc.mainnet.chain.robinhood.com` - the official RPC, called only with `eth_chainId`, `eth_blockNumber`, `eth_getLogs` and `eth_call`:
  - `getLaunchedToken` on the Pons v2 factory `0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e`, and the meme hook `0xE5e702641Ea86F4ae6cC3cDaeD2B886f976Be044`, both from docs.ponsfamily.com/v2#contracts;
  - `Initialize` and `Swap` events on the Uniswap v4 PoolManager `0x8366a39cc670b4001a1121b8f6a443a643e40951` and `getLiquidity(bytes32)` on the v4 StateView `0xf3334192d15450cdd385c8b70e03f9a6bd9e673b`, the same values as Aeon's `deploy-uni-hook/templates/chains.tsv`;
  - `symbol()` on the token and on each pair token.
- Event topics and selectors were checked against 4byte.directory on 2026-11-05. For two graduated tokens, the pool this skill picked was recomputed independently as `keccak256(abi.encode(currency0, currency1, fee, tickSpacing, hooks))` from the factory record, and matched.

The helper `skills/pons-pool-check/pons_pool_check.py` uses the Python standard library only. A check takes about 10 seconds.

## Steps

1. **Validate** that `${var}` is `0x` + 40 hex characters. If not, reply with the expected format and stop.
2. **Run the helper:**
   ```bash
   python3 skills/pons-pool-check/pons_pool_check.py "${var}" > .pons-pool-check.md
   ```
   - Exit code `2` (stderr `PONS_POOL_RPC_DOWN`) means the RPC was unreachable or reported the wrong chain. Log it and stop without notifying.
   - Exit code `3` (stderr `PONS_POOL_BAD_TARGET`) means the address is malformed or the Pons v2 factory has no record for it. Say so and stop.
3. **Notify** with `./notify -f .pons-pool-check.md`. Never call a channel API directly.
4. **Log** to `memory/logs/YYYY-MM-DD.md` under `### pons-pool-check`: the token address, the official pool id (or `none yet`), and the number of other v4 pools.

## Reading the output

- **Official Pons pool** - the pool id built from the factory record and the Pons hook. Its own fee field is 0% because the Pons hook charges the Pons fee, the same rate as on the curve. Its liquidity is locked.
- **No official pool yet** - the token is still on its bonding curve. Trading happens on the curve, not in any v4 pool.
- **Other Uniswap v4 pools** - pools anyone created for the same token. Each line shows the pool fee, the hook (or `none`), the pair, whether it holds liquidity now, and swaps in the last 24 hours. Most active first.
- A pool's existence or activity says nothing about who made it or why. Report what the chain shows.

## Hard limits

- Read-only on chain. Never sign, never broadcast, never ask for or store a key.
- Never call a pool or a token a scam, rug or honeypot, and never tell anyone to buy or sell. Say which pool is official and what the others charge.
- Only Pons v2 tokens are covered. For anything else the factory has no record, and the helper exits `3`.
