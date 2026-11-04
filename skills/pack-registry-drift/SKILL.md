---
name: pack-registry-drift
description: Compare every pack in Aeon's community skill-pack registry with the pack's own skills-pack.json - skills shipped but not listed, listed but gone, missing SKILL.md, capabilities the listing hides - and report only what changed, keyless, read-only
metadata:
  title: Pack Registry Drift
  category: dev
  var: ""
  tags:
    - dev
    - aeon
    - skill-packs
  requires: []
  capabilities:
    - read_only
    - sends_notifications
---

Aeon's community skill packs are listed in `catalog/skill-packs.json`. An entry is written by hand, once, when the pack is listed; the pack itself keeps shipping. `scripts/validate-skill-packs.mjs` checks the registry's shape and its parity with the docs table, but never opens the pack repos. This skill does: it reads each listed pack's own `skills-pack.json` and reports where the registry and the repo disagree.

What `bin/install-skill-pack --list` shows comes from the registry, so a stale entry shows the wrong skill count, and a pack whose registry entry has no `capabilities` shows no `[caps: ...]` marker even when its skills write on chain. Installing still reads the pack's own manifest, so nothing breaks, but the person choosing what to install sees less than is there.

For each pack it reports:

- skills the repo ships that the registry does not list, and listed skills the repo no longer ships,
- skills whose `SKILL.md` is not where the manifest says (resolved with `bin/install-skill-pack`'s rules: default `skills/<slug>`, a path ending in `/SKILL.md` means its directory),
- capabilities declared by the pack's skills that the registry entry omits,
- skills declaring capabilities outside the installer's taxonomy, and skills that write but are `default_enabled: true`.

## Network note

Public, unauthenticated reads only. `./secretcurl` is not needed because no secret is involved.

- `catalog/skill-packs.json` from this checkout, or `https://raw.githubusercontent.com/aeonfun/aeon/main/catalog/skill-packs.json` when it is not here.
- `https://raw.githubusercontent.com/<repo>/<main|master>/<path>/skills-pack.json` and each skill's `SKILL.md` for every listed pack.

Only `raw.githubusercontent.com` is fetched, never `api.github.com`, so the run uses no GitHub API quota. The helper `skills/pack-registry-drift/pack_registry_drift.py` uses the Python standard library only. On 2026-11-04 a full run read 15 packs in about 30 seconds.

## Steps

1. **Run the helper:**
   ```bash
   python3 skills/pack-registry-drift/pack_registry_drift.py \
     --state memory/state/pack-registry-drift.json > .pack-registry-drift.md
   ```
   - Exit code `2` (stderr `PACK_DRIFT_REGISTRY_DOWN`) means the registry could not be read. Log it and stop without notifying.
   - A pack repo that cannot be fetched is counted under `unreachable`, never as a finding, so a flaky fetch does not raise an alert.
2. **Notify** with `./notify -f .pack-registry-drift.md` only when the output starts with `PACK REGISTRY: CHANGES` (the first run, or a finding appeared or cleared since the last run). Never call a channel API directly.
3. **Log** to `memory/logs/YYYY-MM-DD.md` under `### pack-registry-drift`: `PACK_DRIFT_CHANGED` or `PACK_DRIFT_QUIET`, then the second line of the output (`<n> in sync · <n> drifted · <n> unreachable · <n> skill(s) shipped but not listed`).

## Reading the output

- **repo ships N skill(s) the registry does not list** - the pack grew after it was listed. `--list` undercounts it.
- **registry lists skills the repo no longer ships** - a listed skill was removed or renamed in the pack.
- **SKILL.md not found** - the manifest points at a file that is not in the repo on that branch. The installer will skip that skill.
- **registry capabilities omit ...** - the pack's skills declare these, but the registry entry does not, so `--list` does not show them.
- **writes ... and is default_enabled: true** - against the registry's rule that write, on-chain and bet skills ship disabled.

## Hard limits

- Read-only. Never open issues or PRs, on Aeon or on any pack repo. A human decides what to do with a finding.
- Never call a pack safe, unsafe or abandoned. Report what the registry lists and what the repo ships.
