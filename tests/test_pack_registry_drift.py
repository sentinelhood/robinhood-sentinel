"""Offline tests for skills/pack-registry-drift. No network.

Run: python3 tests/test_pack_registry_drift.py
"""
import io, json, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills' / 'pack-registry-drift'))
import pack_registry_drift as prd  # noqa: E402

LISTING = {'repo': 'owner/pack', 'skills': ['a', 'b'], 'capabilities': ['read_only']}


def manifest(*skills):
    return {'version': '1.0', 'skills': list(skills)}


def skill(slug, **kw):
    return {'slug': slug, **kw}


class SkillDir(unittest.TestCase):
    def test_installer_path_rules(self):
        self.assertEqual(prd.skill_dir({}, 'a'), 'skills/a')
        self.assertEqual(prd.skill_dir({'path': 'skills/x/SKILL.md'}, 'a'), 'skills/x')  # file form = its directory
        self.assertEqual(prd.skill_dir({'path': '/skills/x/'}, 'a'), 'skills/x')
        self.assertIsNone(prd.skill_dir({'path': 'SKILL.md'}, 'a'))  # root SKILL.md is rejected by the installer
        self.assertIsNone(prd.skill_dir({'path': 'skills/../../etc'}, 'a'))


class Compare(unittest.TestCase):
    def test_in_sync(self):
        m = manifest(skill('a', capabilities=['read_only']), skill('b'))
        self.assertEqual(prd.compare(LISTING, m, {'a': True, 'b': True}), [])

    def test_unlisted_and_gone_skills(self):
        # Live 2026-11-04: a pack listed with 1 skill shipped 8.
        m = manifest(skill('a'), skill('c'), skill('d'))
        f = prd.compare(LISTING, m, {})
        self.assertIn('owner/pack: repo ships 2 skill(s) the registry does not list: c, d', f)
        self.assertIn('owner/pack: registry lists skills the repo no longer ships: b', f)

    def test_missing_skill_md_and_unchecked(self):
        m = manifest(skill('a'), skill('b'))
        f = prd.compare(LISTING, m, {'a': False, 'b': None})
        self.assertEqual(f, ['owner/pack: a SKILL.md not found at skills/a/SKILL.md'])

    def test_registry_hides_write_capabilities(self):
        # Live 2026-11-04: registry entry with no capabilities, pack skills declaring onchain_writes.
        listing = {'repo': 'owner/pack', 'skills': ['a']}
        m = manifest(skill('a', capabilities=['external_api', 'onchain_writes']))
        self.assertEqual(prd.compare(listing, m, {'a': True}),
                         ['owner/pack: registry capabilities omit external_api, onchain_writes, declared by the pack'])

    def test_bad_capability_and_enabled_writer(self):
        m = manifest(skill('a', capabilities=['read_only', 'teleport']), skill('b', capabilities=['onchain_writes'], default_enabled=True))
        f = prd.compare(LISTING, m, {'a': True, 'b': True})
        self.assertIn('owner/pack: a declares capabilities the installer rejects: teleport', f)
        self.assertIn('owner/pack: b writes (onchain_writes) and is default_enabled: true', f)

    def test_malformed_manifests(self):
        self.assertEqual(prd.compare(LISTING, {'skills': 'x'}, {}), ['owner/pack: skills-pack.json has no skills list'])
        f = prd.compare(LISTING, manifest(skill('../x'), skill('a'), skill('a'), skill('b', path='SKILL.md')), {})
        self.assertIn("owner/pack: manifest has an invalid slug '../x'", f)
        self.assertIn('owner/pack: manifest declares a twice', f)
        self.assertIn("owner/pack: b path is not installable ('SKILL.md')", f)


class EndToEnd(unittest.TestCase):
    def run_main(self, packs, files, state=None):
        def fake_fetch(url):
            if url in files and isinstance(files[url], Exception):
                raise files[url]
            return files.get(url)
        with tempfile.TemporaryDirectory() as d:
            reg = Path(d) / 'skill-packs.json'
            reg.write_text(json.dumps({'packs': packs}))
            args = ['--registry', str(reg), '--json'] + (['--state', state] if state else [])
            out = io.StringIO()
            with mock.patch.object(prd, 'fetch', side_effect=fake_fetch), redirect_stdout(out):
                code = prd.main(args)
        return code, json.loads(out.getvalue())

    RAW = 'https://raw.githubusercontent.com/owner/pack/{}/{}'

    def files(self, branch='main', man=None, skill_mds=('a', 'b')):
        f = {self.RAW.format(branch, 'skills-pack.json'): json.dumps(man or manifest(skill('a'), skill('b')))}
        for s in skill_mds:
            f[self.RAW.format(branch, f'skills/{s}/SKILL.md')] = '---'
        return f

    def test_master_branch_and_in_sync(self):
        code, rep = self.run_main([LISTING], self.files(branch='master'))
        self.assertEqual(code, 0)
        self.assertEqual(rep['findings'], [])
        self.assertEqual((rep['packs'][0]['state'], rep['packs'][0]['branch']), ('ok', 'master'))

    def test_subpath_is_respected(self):
        listing = dict(LISTING, path='aeon')
        files = {self.RAW.format('main', 'aeon/skills-pack.json'): json.dumps(manifest(skill('a'), skill('b'))),
                 self.RAW.format('main', 'aeon/skills/a/SKILL.md'): '---', self.RAW.format('main', 'aeon/skills/b/SKILL.md'): '---'}
        _, rep = self.run_main([listing], files)
        self.assertEqual(rep['summary']['inSync'], 1)

    def test_unreachable_pack_is_not_a_finding(self):
        files = {self.RAW.format('main', 'skills-pack.json'): prd.FetchError('HTTP 503')}
        _, rep = self.run_main([LISTING], files)
        self.assertEqual(rep['findings'], [])
        self.assertEqual(rep['summary']['unreachable'], 1)

    def test_no_manifest_and_bad_json(self):
        _, rep = self.run_main([LISTING], {})
        self.assertEqual(rep['packs'][0]['state'], 'no skills-pack.json on main or master')
        _, rep = self.run_main([LISTING], {self.RAW.format('main', 'skills-pack.json'): '{nope'})
        self.assertEqual(rep['packs'][0]['state'], 'skills-pack.json is not valid JSON')

    def test_state_reports_only_changes(self):
        with tempfile.TemporaryDirectory() as d:
            state = str(Path(d) / 's.json')
            grown = self.files(man=manifest(skill('a'), skill('b'), skill('c')), skill_mds=('a', 'b', 'c'))
            _, first = self.run_main([LISTING], grown, state)
            self.assertTrue(first['changed'])
            _, second = self.run_main([LISTING], grown, state)
            self.assertFalse(second['changed'])
            _, third = self.run_main([LISTING], self.files(), state)
            self.assertTrue(third['changed'])
            self.assertEqual(third['resolvedSinceLast'], ['owner/pack: repo ships 1 skill(s) the registry does not list: c'])

    def test_bad_registry_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            for body in ('{nope', '{"packs": []}', '[]'):
                p = Path(d) / 'r.json'
                p.write_text(body)
                self.assertEqual(prd.main(['--registry', str(p)]), 2, body)
            self.assertEqual(prd.main(['--registry', str(Path(d) / 'missing.json')]), 2)

    def test_unsafe_repo_names_are_skipped(self):
        _, rep = self.run_main([LISTING, {'repo': '../../etc', 'skills': []}, {'repo': 'a/b/c', 'skills': []}], self.files())
        self.assertEqual([p['repo'] for p in rep['packs']], ['owner/pack'])

    def test_markdown_states_facts_only(self):
        _, rep = self.run_main([LISTING], self.files(man=manifest(skill('a'), skill('b'), skill('c')), skill_mds=('a', 'b', 'c')))
        md = prd.to_markdown(rep)
        self.assertTrue(md.startswith('PACK REGISTRY: CHANGES'))
        self.assertIn('not a verdict on the pack', md)
        for word in ('scam', 'malicious', 'unsafe', 'abandoned'):
            self.assertNotIn(word, md.lower())


if __name__ == '__main__':
    unittest.main()
