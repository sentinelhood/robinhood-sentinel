#!/usr/bin/env python3
"""Regenerate public/llms.txt and public/sitemap.xml from skills-pack.json, so agent-facing docs never lag the pack.

Run: python3 scripts/gen-agent-docs.py          # write both files
     python3 scripts/gen-agent-docs.py --check  # exit 1 if either is stale (used by tests)
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = 'https://sentinelhood.com'
# Public snapshots the site serves; each is refreshed by the server cron and validated by the page before display.
SNAPSHOTS = [
    ('burn.json', 'SNTL burned through the token\'s own burn(), with the latest burns.'),
    ('copies.json', 'Pons v2 launches that copy the official SNTL ticker or name.'),
    ('guards.json', 'Tokens guarded by a Sentinel Guard burn, and the copies each guard lists.'),
    ('movers.json', 'Busiest Pons v2 bonding curves in the last hours, ranked by distinct traders (pons-curve-movers).'),
    ('hook-usage.json', 'Pools and swaps per Aeon univ4-hooks hook on Robinhood Chain (hook-usage).'),
    ('registry.json', 'Every aeonfun/univ4-hooks address read on its own chain: code present, flag bits (hook-registry-check).'),
    ('token.json', 'The official Sentinel token, if live; the page only shows it when it has code on chain 4663.'),
]


def render():
    pack = json.loads((ROOT / 'skills-pack.json').read_text())
    skills = pack['skills']
    lines = [
        '# Sentinel', '',
        '> Keyless, read-only Robinhood Chain (chainId 4663) reader for agents and humans. GET-only, block-stamped, never signs or broadcasts.', '',
        '## API',
        f'- [OpenAPI 3.1 spec]({SITE}/openapi.json): one operation, `GET /api/service?action=network|address|transaction|aeon|contributions|token|launches|shiplog|deployer&value=...`. '
        f'Share links: `{SITE}/?ca=0x...` opens the token check for that address.', '',
        '## Snapshots',
        'Static JSON, refreshed by a server cron from the official RPC. Each carries the block it was read at.',
    ]
    lines += [f'- [{name}]({SITE}/{name}): {what}' for name, what in SNAPSHOTS]
    lines += ['', f'## Aeon skills ({pack["name"]} {pack["version"]}, {len(skills)} skills)',
              f'Install all: `bin/install-skill-pack sentinelhood/robinhood-sentinel` from an Aeon checkout. Every skill is read-only, needs no keys and ships `default_enabled: false`.']
    lines += [f'- [{s["slug"]}]({SITE}/skills/{s["slug"]}.md): {s["description"]}' for s in skills]
    lines += ['', '## Limits',
              '- Read-only: no signing, no broadcasting, no keys.',
              '- Historical reads, not pre-sign simulation. No result is a safety guarantee or a buy/sell signal.',
              '- Counts are of addresses and events, not people: routers and one person with many wallets both distort them.', '']
    llms = '\n'.join(lines)
    urls = [f'{SITE}/', f'{SITE}/llms.txt', f'{SITE}/openapi.json'] + [f'{SITE}/skills/{s["slug"]}.md' for s in skills]
    sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' \
              + ''.join(f'  <url><loc>{u}</loc></url>\n' for u in urls) + '</urlset>\n'
    return {'public/llms.txt': llms, 'public/sitemap.xml': sitemap}


def main():
    out = render()
    stale = [p for p, text in out.items() if (ROOT / p).read_text() != text]
    missing = [name for name, _ in SNAPSHOTS if not (ROOT / 'public' / name).is_file()]
    if missing:
        print(f'snapshot listed but missing in public/: {missing}', file=sys.stderr)
        return 1
    if '--check' in sys.argv:
        if stale:
            print(f'stale: {stale}. Run: python3 scripts/gen-agent-docs.py', file=sys.stderr)
            return 1
        print('agent docs up to date')
        return 0
    for p, text in out.items():
        (ROOT / p).write_text(text)
    print(f'wrote {", ".join(out)}' + ('' if stale else ' (no change)'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
