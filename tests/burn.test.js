import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateBurn, tokenAmount, burnPercent, SNTL } from '../src/burn.ts';

const snapshot = JSON.parse(readFileSync(new URL('../public/burn.json', import.meta.url)));
test('published snapshot identity and exact supply reconcile', () => {
  assert.equal(validateBurn(snapshot, SNTL), snapshot);
  assert.equal(BigInt(snapshot.mintedRaw) - BigInt(snapshot.burnedRaw), BigInt(snapshot.remainingRaw));
});
test('reject wrong identity, malformed quantities, metadata, supply and unsafe links', () => {
  for (const patch of [{chainId: 1}, {token: '0x' + '1'.repeat(40)}, {decimals: 6}, {burnedRaw: '1'},
    {remainingRaw: '-1'}, {mintedRaw: 1e27}, {mintedRaw: '0'}, {blockHash: 'bad'}, {timestamp: 'bad'},
    {block: 0}, {burnEventCount: -1}, {latestBurns: []},
    {latestBurns: [{...snapshot.latestBurns[0], tx: '" onmouseover="alert(1)'} , ...snapshot.latestBurns.slice(1)]}]) {
    assert.throws(() => validateBurn({...snapshot, ...patch}, SNTL));
  }
  assert.throws(() => validateBurn(snapshot, '0x' + '1'.repeat(40)));
  assert.throws(() => validateBurn(null, SNTL));
});
test('quantity formatting preserves all 18 decimals without Number rounding', () => {
  assert.equal(tokenAmount('24860397533712448875904953'), '24,860,397.533712448875904953');
  assert.equal(tokenAmount('24860397533712448875904953', 4), '24,860,397.5337');
  assert.equal(tokenAmount('1'), '0.000000000000000001');
  assert.equal(burnPercent({...snapshot, mintedRaw: '1000000000000000000000000000', burnedRaw: '24860397533712448875904953'}), '2.4860');
});