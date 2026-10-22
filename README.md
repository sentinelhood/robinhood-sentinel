# Sentinel

A read-only, block-stamped reader for Robinhood Chain (chain ID 4663), and an [Aeon](https://www.aeon.fun) skill pack that extends Aeon's on-chain monitoring to that chain.

Live: https://sentinelhood.com · X: [@sentinelhood](https://x.com/sentinelhood)

Sentinel never connects a wallet, never signs, never broadcasts, and never asks for a key. Every value it returns says which block it was read at.

## Aeon skill pack

Aeon's `onchain-monitor` covers ethereum, base, arbitrum, optimism and polygon. It does not cover Robinhood Chain. This repo is an Aeon community skill pack that adds that coverage.

```bash
bin/install-skill-pack sentinelhood/robinhood-sentinel
```

| Skill | What it does | Secrets | Capabilities | Default schedule |
|---|---|---|---|---|
| `robinhood-chain-monitor` | Diffs nonce, native balance and bytecode for watched addresses against `memory/robinhood-state.json`. Alerts only on change, through `./notify`. | none | `read_only`, `sends_notifications` | `0 */6 * * *`, disabled until you enable it |
| `hook-usage` | For every hook in `aeonfun/univ4-hooks` with a Robinhood Chain address, counts the v4 pools created with it and the swaps through them in the last N days. Incremental. Ships `hook_usage.py` (standard library only). | none | `read_only`, `sends_notifications` | `0 9 * * 1`, disabled until you enable it |
| `pons-launch-watch` | Reads every new Pons v2 launch from the factory and alerts when one copies a ticker or name you guard (case, `$`, punctuation and full-width characters ignored), excluding your official address. Each lookalike is reported once. Also summarises launch volume, repeated tickers and the busiest deployers. Incremental. Ships `pons_launch_watch.py` (standard library only). | none | `read_only`, `sends_notifications` | `*/30 * * * *`, disabled until you enable it |

Configure it with `memory/robinhood-watches.yml` (see the skill file). The skill reads only from the official RPC, `rpc.mainnet.chain.robinhood.com`, so your watch list is never sent to sentinelhood.com or any other third party. The pack passes Aeon's `scripts/validate-pack.sh` and `scripts/skill-scan.sh`.

## Web app

- **Inspector:** paste an address (balance, bytecode size, nonce) or a transaction hash (status, from/to, value, gas used, raw receipt). This is a historical lookup, not a pre-sign simulation.
- **Watchlist:** stored in your browser only. Native ETH balances refresh on request.
- **Aeon skill search:** queries Aeon's public `/ask` endpoint.
- **Monitoring brief export:** downloads your watchlist as Markdown for an Aeon operator.

## API

`GET /api/service?action=<action>&value=<value>`

| Action | Value | Returns |
|---|---|---|
| `network` | none | `chainId`, `block`, `gasPriceWei` |
| `address` | `0x` + 40 hex | `balanceWei`, `codeBytes`, `nonce`, `block` |
| `transaction` | `0x` + 64 hex | transaction and receipt, or `null` if not found |
| `aeon` | 2–200 chars | matching Aeon docs and skills |

Only GET is accepted. Input is validated before any upstream call, the chain ID is checked as 4663 on every read, and there is no arbitrary RPC passthrough. Errors are JSON (`400` invalid input, `405` non-GET, `502` upstream failure). Machine-readable: [`/openapi.json`](https://sentinelhood.com/openapi.json), [`/llms.txt`](https://sentinelhood.com/llms.txt).

## Limits

- Native ETH only. Token balances and USD values are not indexed.
- Bytecode presence is not an audit. Nothing here is a safety verdict.
- The Inspector reads past transactions. It does not simulate a transaction before you sign it.

## Run locally

```bash
npm install
npm test          # input validation and method gating
npx vercel dev    # UI + /api functions
npm run dev       # UI only (the /api calls will fail)
```

### RPC configuration

Set `ROBINHOOD_RPC_URL` (https only) as an environment variable. Without it the public RPC `https://rpc.mainnet.chain.robinhood.com` is used. The URL stays server-side and is never returned in responses: `source` reports only `private-rpc` or `public-rpc`.

## License

MIT
