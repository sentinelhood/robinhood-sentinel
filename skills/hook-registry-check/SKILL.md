---
name: hook-registry-check
description: Check every address in Aeon's public Uniswap v4 hook registry against its chain - code present, flag bits match the address, same functions on every chain - and report only what changed, keyless, read-only
metadata:
  title: Hook Registry Check
  category: crypto
  var: ""
  tags:
    - crypto
    - uniswap-v4
    - dev
    - robinhood-chain
  requires: []
  capabilities:
    - read_only
    - sends_notifications
---

`deploy-uni-hook` ships hooks and `submit-hook` lists them in `aeonfun/univ4-hooks`, the registry behind aeon.fun/hooks. The registry's CI checks that each listed `flags` value equals the address's low 14 bits, but nothing reads the chain: a typo, a testnet address or a chain that drifted out of `chains.tsv` would still list. This skill reads every listed address on its own chain and reports what the registry says that the chain does not back up.

For each `(hook, chain, address)` in `hooklist.json`:

- the chain's RPC answers with the chain ID the registry gives for that chain,
- there is code at the address,
- the low 14 bits of the address equal the listed `flags`,
- a hook listed on several chains exposes the same function selectors on all of them.

It also groups each hook's chains by build: code with metadata stripped and the PoolManager and the hook's own address blanked. When the selectors match but the builds differ, that is a compiler-setting difference, reported for reference and not as a finding.

## Network note

Public, unauthenticated reads only. `./secretcurl` is not needed because no secret is involved.

- `https://raw.githubusercontent.com/aeonfun/univ4-hooks/main/hooklist.json` - the registry.
- `skills/deploy-uni-hook/templates/chains.tsv` from this checkout, or `https://raw.githubusercontent.com/aeonfun/aeon/main/skills/deploy-uni-hook/templates/chains.tsv` when it is not here - the RPC for each chain ID. No RPC URL is hard-coded in this skill.
- Each chain's public RPC from that table, called only with `eth_chainId`, `eth_blockNumber` and `eth_getCode`. All addresses on one chain are read at the same block.

The helper `skills/hook-registry-check/hook_registry_check.py` uses the Python standard library only. On 2026-10-28 a full run read 43 addresses on 6 chains in about 20 seconds.

## Steps

1. **Run the helper:**
   ```bash
   python3 skills/hook-registry-check/hook_registry_check.py \
     --state memory/state/hook-registry-check.json > .hook-registry-check.md
   ```
   - Exit code `2` (stderr `HOOK_REGISTRY_DOWN`) means the registry or the chain table could not be read. Log it and stop without notifying.
   - A single chain whose RPC fails is counted under `not checked`, never as a finding, so a flaky endpoint does not raise an alert.
2. **Notify** with `./notify -f .hook-registry-check.md` only when the output starts with `HOOK REGISTRY: CHANGES` (the first run, or a finding appeared or cleared since the last run). Never call a channel API directly.
3. **Log** to `memory/logs/YYYY-MM-DD.md` under `### hook-registry-check`: `HOOK_REGISTRY_CHANGED` or `HOOK_REGISTRY_QUIET`, then the second line of the output (`<n> have code · <n> no code · <n> not checked · <n> flag mismatch`).

## Reading the output

- **no code at <address>** - the chain has no contract there at the block read. The listed address cannot be the hook it describes on that chain.
- **flags do not match** - v4 routes callbacks by the address's low 14 bits, so the listing describes callbacks the contract will not receive.
- **RPC answered for another chain** - the RPC in `chains.tsv` for that chain ID returned a different chain ID. The check did not run.
- **chain not in deploy-uni-hook chains.tsv** - the registry lists a chain Aeon's own chain table has no RPC for (on 2026-10-28: `monad`, 10 addresses). Those addresses are not checked.
- **function selectors differ** - the same hook name lists contracts with different external functions on different chains.
- **builds** - for reference only. Same selectors, different build output.

## Hard limits

- Read-only on chain. Never sign, never broadcast, never ask for or store a key.
- Never call a hook safe, unsafe, malicious or abandoned. Report what the registry lists and what the chain returned, and the block it was read at.
- Do not open issues or PRs on `aeonfun/univ4-hooks` from this skill. A human decides what to do with a finding.
