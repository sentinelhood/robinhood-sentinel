#!/usr/bin/env python3
"""Compare every pack in Aeon's community skill-pack registry with the pack's own skills-pack.json.

The registry (aeonfun/aeon catalog/skill-packs.json) is written once, by hand, when a pack is listed. Packs keep
shipping. This reads each pack repo's manifest and reports where the listing and the repo disagree, using the same
path rules as Aeon's bin/install-skill-pack.

Read-only and keyless. Only raw.githubusercontent.com is fetched, so no GitHub API quota is used.

Usage:
  python3 pack_registry_drift.py [--state memory/state/pack-registry-drift.json] [--registry FILE] [--json]

Exit codes: 0 ok (drift is reported, not an error), 2 registry unreachable or malformed (PACK_DRIFT_REGISTRY_DOWN).
"""
import argparse, json, os, re, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

REGISTRY_URL = 'https://raw.githubusercontent.com/aeonfun/aeon/main/catalog/skill-packs.json'
REGISTRY_LOCAL = Path(__file__).resolve().parents[2] / 'catalog/skill-packs.json'
RAW = 'https://raw.githubusercontent.com/{repo}/{branch}/{path}'
HEADERS = {'User-Agent': 'aeon-pack-registry-drift/1.0'}
# bin/install-skill-pack ALLOWED_CAPABILITIES, read on 2026-11-04.
CAPABILITIES = {'read_only', 'external_api', 'writes_external_host', 'onchain_writes', 'agent_messaging', 'sends_notifications'}
# PR template: "Write / onchain / bet skills are default_enabled: false".
WRITES = {'writes_external_host', 'onchain_writes'}
REPO = re.compile(r'^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$')
SLUG = re.compile(r'^[A-Za-z0-9_-]+$')
BRANCHES = ('main', 'master')


class FetchError(RuntimeError):
    pass


def fetch(url):
    """Text body, None on 404, FetchError after retries on anything else."""
    reason = 'no response'
    for attempt in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30).read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            reason = f'HTTP {e.code}'
            if e.code not in (429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            reason = type(e).__name__
        time.sleep(2 * (attempt + 1))
    raise FetchError(reason)


# ---------- pure helpers (tested offline) ----------
def skill_dir(entry, slug):
    """bin/install-skill-pack path rules: default skills/<slug>; a path ending in /SKILL.md means its directory."""
    p = (entry.get('path') or f'skills/{slug}').strip('/')
    if p == 'SKILL.md':
        return None  # the installer rejects a root-level SKILL.md
    if p.endswith('/SKILL.md'):
        p = p[:-len('/SKILL.md')]
    return None if '..' in p.split('/') else p


def compare(listing, manifest, skill_md_present):
    """Findings for one pack. `skill_md_present` maps slug -> True/False/None (None = not checked)."""
    out = []
    repo = listing['repo']
    skills = manifest.get('skills') if isinstance(manifest, dict) else None
    if not isinstance(skills, list):
        return [f'{repo}: skills-pack.json has no skills list']
    slugs, seen = [], set()
    for s in skills:
        slug = s.get('slug') if isinstance(s, dict) else None
        if not isinstance(slug, str) or not SLUG.match(slug):
            out.append(f'{repo}: manifest has an invalid slug {slug!r}')
            continue
        if slug in seen:
            out.append(f'{repo}: manifest declares {slug} twice')
        seen.add(slug)
        slugs.append(slug)
        if skill_dir(s, slug) is None:
            out.append(f'{repo}: {slug} path is not installable ({s.get("path")!r})')
        elif skill_md_present.get(slug) is False:
            out.append(f'{repo}: {slug} SKILL.md not found at {skill_dir(s, slug)}/SKILL.md')
        caps = s.get('capabilities') or []
        bad = sorted(c for c in caps if c not in CAPABILITIES) if isinstance(caps, list) else ['(not a list)']
        if bad:
            out.append(f'{repo}: {slug} declares capabilities the installer rejects: {", ".join(map(str, bad))}')
        if isinstance(caps, list) and s.get('default_enabled') is True and WRITES & set(caps):
            out.append(f'{repo}: {slug} writes ({", ".join(sorted(WRITES & set(caps)))}) and is default_enabled: true')
    listed = listing.get('skills') or []
    gone = [x for x in listed if x not in seen]
    new = [x for x in slugs if x not in listed]
    if gone:
        out.append(f'{repo}: registry lists skills the repo no longer ships: {", ".join(gone)}')
    if new:
        out.append(f'{repo}: repo ships {len(new)} skill(s) the registry does not list: {", ".join(new)}')
    declared = {c for s in skills if isinstance(s, dict) and isinstance(s.get('capabilities'), list)
                for c in s['capabilities'] if c in CAPABILITIES}
    hidden = sorted(declared - set(listing.get('capabilities') or []))
    if hidden:
        out.append(f'{repo}: registry capabilities omit {", ".join(hidden)}, declared by the pack')
    return out


def to_markdown(rep):
    s = rep['summary']
    head = 'PACK REGISTRY: CHANGES' if rep['changed'] else 'Pack registry drift'
    lines = [f"{head} · {s['packs']} packs in Aeon's registry",
             f"{s['inSync']} in sync · {s['drifted']} drifted · {s['unreachable']} unreachable · "
             f"{s['unlisted']} skill(s) shipped but not listed", '']
    for name, key in (('New since last run', 'newSinceLast'), ('Resolved since last run', 'resolvedSinceLast')):
        if rep[key]:
            lines.append(f'{name}:')
            lines += [f'- {p}' for p in rep[key]]
            lines.append('')
    if rep['findings']:
        lines.append('All findings:')
        lines += [f'- {p}' for p in rep['findings']]
        lines.append('')
    for p in rep['packs']:
        state = p['state'] if p['state'] != 'ok' else 'in sync'
        lines.append(f"{p['repo']}: {state} · registry {p['listed']} · repo {p['shipped'] if p['shipped'] is not None else '?'}"
                     + (f" · v{p['version']}" if p.get('version') else ''))
    lines += ['', 'A finding is a difference between the registry entry and the pack repo, not a verdict on the pack.']
    return '\n'.join(lines)


# ---------- network ----------
def read_pack(listing):
    """Fetch the manifest and probe each SKILL.md. Returns (manifest|None, branch|None, skill_md_present, error|None)."""
    base = (listing.get('path') or '').strip('/')
    rel = lambda p: f'{base}/{p}' if base else p
    try:
        for branch in BRANCHES:
            text = fetch(RAW.format(repo=listing['repo'], branch=branch, path=rel('skills-pack.json')))
            if text is not None:
                break
        else:
            return None, None, {}, 'no skills-pack.json on main or master'
        manifest = json.loads(text)
        present = {}
        for s in manifest.get('skills') or []:
            slug = s.get('slug') if isinstance(s, dict) else None
            d = skill_dir(s, slug) if isinstance(slug, str) and SLUG.match(slug) else None
            if d:
                present[slug] = fetch(RAW.format(repo=listing['repo'], branch=branch, path=rel(f'{d}/SKILL.md'))) is not None
        return manifest, branch, present, None
    except FetchError as e:
        return None, None, {}, f'unreachable ({e})'
    except ValueError:
        return None, None, {}, 'skills-pack.json is not valid JSON'


def load_registry(path):
    if path:
        text = Path(path).read_text()
    elif REGISTRY_LOCAL.is_file():
        text = REGISTRY_LOCAL.read_text()
    else:
        text = fetch(REGISTRY_URL)
        if text is None:
            raise FetchError('registry not found')
    reg = json.loads(text)
    packs = reg.get('packs') if isinstance(reg, dict) else None
    if not isinstance(packs, list) or not packs:
        raise ValueError('no packs')
    return [p for p in packs if isinstance(p, dict) and isinstance(p.get('repo'), str) and REPO.match(p['repo'])]


def save_state(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=p.parent, delete=False) as f:
        json.dump(data, f, indent=1)
    os.replace(f.name, p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--state', help='JSON file holding the last findings; enables change detection')
    ap.add_argument('--registry', help='read skill-packs.json from this file instead of the checkout or GitHub')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    try:
        packs = load_registry(a.registry)
    except (OSError, ValueError, FetchError) as e:
        print(f'PACK_DRIFT_REGISTRY_DOWN: {type(e).__name__}: {e}'[:200], file=sys.stderr)
        return 2
    findings, rows = [], []
    for listing in packs:
        manifest, branch, present, err = read_pack(listing)
        if err:
            # Not a finding: a flaky fetch must not look like the pack changed.
            rows.append({'repo': listing['repo'], 'state': err, 'listed': len(listing.get('skills') or []), 'shipped': None, 'branch': None})
            continue
        f = compare(listing, manifest, present)
        findings += f
        shipped = [s.get('slug') for s in manifest.get('skills') or [] if isinstance(s, dict)]
        rows.append({'repo': listing['repo'], 'state': 'drifted' if f else 'ok', 'listed': len(listing.get('skills') or []),
                     'shipped': len(shipped), 'unlisted': len([x for x in shipped if x not in (listing.get('skills') or [])]),
                     'version': manifest.get('version'), 'branch': branch})
    findings = sorted(findings)
    prev = None
    if a.state:
        try:
            prev = json.loads(Path(a.state).read_text())
        except (OSError, ValueError):
            prev = None
    before = set(prev.get('findings', [])) if prev else set()
    rep = {
        'summary': {'packs': len(rows), 'inSync': sum(r['state'] == 'ok' for r in rows), 'drifted': sum(r['state'] == 'drifted' for r in rows),
                    'unreachable': sum(r['state'] not in ('ok', 'drifted') for r in rows), 'unlisted': sum(r.get('unlisted', 0) for r in rows)},
        'findings': findings, 'newSinceLast': sorted(set(findings) - before) if prev else [],
        'resolvedSinceLast': sorted(before - set(findings)) if prev else [], 'changed': prev is None or set(findings) != before,
        'packs': rows,
    }
    if a.state:
        save_state(a.state, {'findings': findings, 'checkedAt': int(time.time())})
    print(json.dumps(rep, indent=1) if a.json else to_markdown(rep))
    return 0


if __name__ == '__main__':
    sys.exit(main())
