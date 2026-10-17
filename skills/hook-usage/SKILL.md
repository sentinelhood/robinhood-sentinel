---
name: hook-usage
description: Measure real usage of Aeon's Uniswap v4 hooks on Robinhood Chain - pools created per hook and swaps in the last N days, read keyless from the official RPC
metadata:
  title: Hook Usage
  category: crypto
  var: ""
  tags:
    - crypto
    - robinhood-chain
    - uniswap-v4
  requires: []
  capabilities:
    - read_only
    - sends_notifications
---

> **${var}** - Window in days for the swap count. Empty = `7`.

`deploy-uni-hook` and `submit-hook` ship hooks to Robinhood Chain and list them in `aeonfun/univ4-hooks`, but nothing reports whether anyone uses them afterwards. This skill answers that: for every hook in the registry that has a Robinhood Chain address, it counts the Uniswap v4 pools created with that hook and the swaps through those pools in the window.

## Network note

Public, unauthenticated reads only. `./secretcurl` is not needed because no secret is involved.

- `https://raw.githubusercontent.com/aeonfun/univ4-hooks/main/hooklist.json` - which hooks exist and their Robinhood Chain addresses.
- `https://rpc.mainnet.chain.robinhood.com` - the official RPC, called only with `eth_chainId`, `eth_blockNumber` and `eth_getLogs` on the v4 PoolManager (`0x8366a39cc670b4001a1121b8f6a443a643e40951`, the same value as `deploy-uni-hook/templates/chains.tsv`).

The helper `skills/hook-usage/hook_usage.py` uses the Python standard library only. It splits log queries to stay under the RPC limits (10k logs per query, 100k blocks per OR-list query) and backs off on 429s.

## Steps

1. **Run the helper.** Use `${var}` as the window if it is a positive number, otherwise use 7:
   ```bash
   python3 skills/hook-usage/hook_usage.py --state memory/state/hook-usage.json --days 7 > .hook-usage.md
   ```
   - The first run backfills every pool since the earliest registry hook (about 70 log queries, roughly 7 minutes). Later runs scan only new blocks and finish in about a minute.
   - The state file holds the pools found and the last block scanned. The helper writes it via a tempfile and a rename, so a failed run cannot corrupt it.
   - Exit code `2` (or stderr `HOOK_USAGE_RPC_DOWN`) means the RPC was unreachable or reported the wrong chain. Log `HOOK_USAGE_RPC_DOWN` and stop without notifying. A broken RPC must never look like "no usage".
   - Stderr `HOOK_USAGE_NO_HOOKS` means the registry has no Robinhood Chain hooks. Log it and stop without notifying.
2. **Compare with the last report.** Read `memory/state/hook-usage-last.md` if it exists. Note any hook whose pool count went from 0 to at least 1 (first adoption) and any hook whose swap count changed.
3. **Notify** with `./notify -f .hook-usage.md`, but only on the first run or when step 2 found a change. Never call a channel API directly. If nothing changed, do not notify.
4. **Persist** by copying `.hook-usage.md` to `memory/state/hook-usage-last.md`.
5. **Log** to `memory/logs/YYYY-MM-DD.md` under `### hook-usage`, as bullet points: `HOOK_USAGE_CHANGED` or `HOOK_USAGE_QUIET`, followed by `block <n> · <hooksWithPools>/<hooks> hooks have pools · <pools> pools · <swaps> swaps in <days>d`.

## Reading the numbers

- **pools** - v4 pools whose `Initialize` event names this hook. Creating a pool is not the same as using it.
- **active** - pools with at least one swap in the window.
- **callers** - distinct `sender` addresses on `Swap` events. This is usually a router contract, not an end user, so it is a lower bound on activity and never a count of people.
- A `(!) flag bits mismatch` line means the registry's flags do not match the address's low 14 bits. Report it, because v4 routes callbacks by those bits.

## Hard limits

- Read-only on chain. Never sign, never broadcast, never ask for or store a key.
- Do not estimate volume, fees or USD from these counts. They are event counts only.
- Never describe a hook as safe, unsafe or abandoned. Report the numbers and the block they were read at.
