import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateRegistry } from '../src/registry.ts';

const published = JSON.parse(readFileSync(new URL('../public/registry.json', import.meta.url)));
const entry = (chain, status = 'code', flagsOk = true) => ({ chain, address: '0x' + 'a'.repeat(38) + 'c4', status, flagsOk });
const snap = () => ({
  generatedAt: '2026-10-29T10:00:00+00:00',
  summary: { addresses: 3, hooks: 2, chains: 2, withCode: 2, noCode: 0, unchecked: 1, flagMismatch: 0 },
  chains: [{ chain: 'robinhood', chainId: 4663, addresses: 2, block: 100, checked: true },
    { chain: 'monad', chainId: 143, addresses: 1, block: null, checked: false }],
  hooks: [{ hook: 'NoOp', stage: 'template', chains: [entry('robinhood'), entry('monad', 'no-rpc')], builds: 1, selectorsMatch: true },
    { hook: 'Twigpine Wrap Hook', stage: 'deployed', chains: [entry('robinhood')], builds: 1, selectorsMatch: true }],
  problems: ['NoOp@monad: chain not in deploy-uni-hook chains.tsv, cannot be checked'],
});

test('published registry snapshot validates and matches its rows', () => {
  assert.equal(validateRegistry(published), published);
  assert.equal(validateRegistry(snap()).hooks.length, 2);
});

test('registry: a summary that disagrees with its rows is rejected', () => {
  for (const patch of [{ withCode: 3, unchecked: 0 }, { noCode: 1, unchecked: 0 }, { flagMismatch: 1 }, { addresses: 4, unchecked: 2 }]) {
    const s = snap();
    Object.assign(s.summary, patch);
    assert.throws(() => validateRegistry(s), undefined, JSON.stringify(patch));
  }
  const s = snap();
  s.chains[0].addresses = 5;
  assert.throws(() => validateRegistry(s), undefined, 'per-chain count drift');
});

test('registry: bad shapes, unknown chains, unsafe names and bad addresses are rejected', () => {
  const cases = [
    (s) => { s.generatedAt = 'nope'; },
    (s) => { s.hooks[0].hook = '<img src=x onerror=alert(1)>'; },
    (s) => { s.hooks[1].hook = s.hooks[0].hook; },
    (s) => { s.hooks[0].chains[0].chain = 'solana'; },
    (s) => { s.hooks[0].chains[0].address = '0xABC'; },
    (s) => { s.hooks[0].chains[0].address = '0x' + 'A'.repeat(40); },
    (s) => { s.hooks[0].chains[0].status = 'safe'; },
    (s) => { s.hooks[0].chains[0].flagsOk = 'yes'; },
    (s) => { s.hooks[0].chains = []; },
    (s) => { s.chains[1].checked = true; },
    (s) => { s.chains.push(s.chains[0]); s.summary.chains = 3; },
    (s) => { s.problems = ['x'.repeat(201)]; },
    (s) => { s.hooks = 'x'; },
  ];
  for (const [i, mutate] of cases.entries()) {
    const s = snap();
    mutate(s);
    assert.throws(() => validateRegistry(s), undefined, `case ${i}`);
  }
  assert.throws(() => validateRegistry(null));
});
