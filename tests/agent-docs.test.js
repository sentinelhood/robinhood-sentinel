import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const root = new URL('..', import.meta.url);
const read = (p) => readFileSync(new URL(p, root), 'utf8');
const pack = JSON.parse(read('skills-pack.json'));

test('llms.txt and sitemap.xml are regenerated from skills-pack.json', () => {
  const r = spawnSync('python3', ['scripts/gen-agent-docs.py', '--check'], { cwd: root, encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
});

test('every pack skill is linked from llms.txt and the sitemap, and shipped by the build', () => {
  const llms = read('public/llms.txt'), sitemap = read('public/sitemap.xml'), build = JSON.parse(read('package.json')).scripts.build;
  for (const s of pack.skills) {
    assert.ok(llms.includes(`/skills/${s.slug}.md`), `llms.txt misses ${s.slug}`);
    assert.ok(sitemap.includes(`/skills/${s.slug}.md`), `sitemap misses ${s.slug}`);
    assert.ok(build.includes(`skills/${s.slug}/SKILL.md`), `build does not copy ${s.slug}`);
    assert.ok(existsSync(new URL(`skills/${s.slug}/SKILL.md`, root)), `missing skills/${s.slug}/SKILL.md`);
  }
});

test('the hero and llms.txt state the real skill count', () => {
  const words = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'];
  const n = pack.skills.length;
  const word = words[n][0].toUpperCase() + words[n].slice(1);
  assert.ok(read('src/app.ts').includes(`${word} keyless Aeon skills`), `hero should say "${word} keyless Aeon skills"`);
  assert.ok(read('public/llms.txt').includes(`${n} skills`));
});

test('llms.txt does not repeat the outdated onchain-monitor claim', () => {
  assert.ok(!/not covered by Aeon/i.test(read('public/llms.txt')));
});
