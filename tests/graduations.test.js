import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateGraduations } from '../src/graduations.ts';

const published = JSON.parse(readFileSync(new URL('../public/graduations.json', import.meta.url)));
const g = {token: '0x' + 'a'.repeat(40), symbol: 'ZKBLAST', name: 'ZK Blast', deployer: '0x' + 'b'.repeat(40), block: 103208666,
  tx: '0x' + 'c'.repeat(64), quoteRaw: '4200000000000000352', pairSymbol: 'ETH', pairDecimals: 18, phase: 2};
const snap = {chainId: 4663, block: 103325648, windowHours: 24, generatedAt: '2026-11-01T11:00:00+00:00', launches: 777, graduations: 2,
  graduated: [g, {...g, token: '0x' + 'd'.repeat(40), block: 103136495, quoteRaw: '369000000000000000034', pairSymbol: 'GME'}]};

test('published graduations snapshot validates', () => {
  assert.equal(validateGraduations(published), published);
  assert.equal(validateGraduations(snap), snap);
});

test('graduations: an empty day is valid', () => {
  assert.equal(validateGraduations({...snap, graduations: 0, graduated: []}).graduated.length, 0);
});

test('graduations: reject wrong chain, bad shapes, unsafe text and impossible numbers', () => {
  for (const patch of [{chainId: 1}, {block: -1}, {windowHours: 0}, {windowHours: 100}, {generatedAt: 'bad'}, {launches: 1.5},
    {graduated: 'x'}, {graduated: Array(21).fill(g)}, {graduations: 1}, {graduations: 3, graduated: []}]) {
    assert.throws(() => validateGraduations({...snap, ...patch}), undefined, JSON.stringify(patch).slice(0, 60));
  }
  for (const e of [{token: '0xABC'}, {token: '0x' + 'A'.repeat(40)}, {symbol: '<img src=x onerror=alert(1)>'.repeat(4)}, {symbol: ''},
    {deployer: 'nope'}, {block: 103325649}, {tx: '0x12'}, {tx: 'javascript:alert(1)'}, {quoteRaw: '4.2e18'}, {quoteRaw: '-1'},
    {pairDecimals: 255}, {phase: 4}, {phase: '2'}]) {
    assert.throws(() => validateGraduations({...snap, graduated: [{...g, ...e}], graduations: 1}), undefined, JSON.stringify(e).slice(0, 60));
  }
  assert.throws(() => validateGraduations({...snap, graduated: [g, g]}), undefined, 'duplicate token');
  assert.throws(() => validateGraduations({...snap, graduated: [snap.graduated[1], g]}), undefined, 'not newest first');
});
