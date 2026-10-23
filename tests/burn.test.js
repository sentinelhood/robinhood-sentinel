import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateBurn, validateCopies, validateGuards, guardCalldata, tokenAmount, burnPercent, SNTL } from '../src/burn.ts';

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
const TOKEN = '0x57c140bfe79001d29c3d1108f461bd977198480f';
const guard = {token: TOKEN, deployer: '0x45cde31e37365c5cd378135e93bea0d0f89cb9d5', symbol: 'RUSH', name: 'Rush',
  burnedRaw: '1000000000000000000000000', burns: 1, since: '2026-10-22T15:00:00Z', expiresAt: '2026-11-21T15:00:00Z',
  active: true, lastTx: '0x' + 'a'.repeat(64), copyCount: 1,
  copies: [{token: '0x' + '3'.repeat(40), deployer: '0x' + '4'.repeat(40), block: 10, symbol: 'RUSH', name: null}]};
const guards = {chainId: 4663, token: SNTL, block: 100, generatedAt: '2026-10-22T15:30:00Z', minBurnRaw: '1000000000000000000000000',
  periodDays: 30, windowHours: 24, launches: 1700, guards: [guard]};
test('published guards snapshot validates', () => {
  validateGuards(JSON.parse(readFileSync(new URL('../public/guards.json', import.meta.url))));
  assert.equal(validateGuards(guards), guards);
});
test('guards: reject wrong token, under-minimum burns, SNTL as guarded, bad copies and HTML', () => {
  for (const patch of [{chainId: 1}, {token: TOKEN}, {minBurnRaw: '0'}, {guards: 'x'}]) assert.throws(() => validateGuards({...guards, ...patch}));
  for (const g of [{burnedRaw: '1'}, {token: SNTL}, {symbol: '<img src=x onerror=alert(1)>'.repeat(8)}, {lastTx: 'javascript:alert(1)'},
    {expiresAt: '2026-10-01T00:00:00Z'}, {copyCount: 0}, {copies: [{...guard.copies[0], token: TOKEN}]},
    {copies: [{...guard.copies[0], block: 101}]}, {active: 'yes'}]) {
    assert.throws(() => validateGuards({...guards, guards: [{...guard, ...g}]}));
  }
});
test('guard calldata = burn(amount) + token word, matching the snapshot parser', () => {
  const d = guardCalldata(TOKEN.toUpperCase().replace('0X', '0x'), 1_000_000n);
  assert.equal(d, '0x42966c68' + (10n ** 24n).toString(16).padStart(64, '0') + TOKEN.slice(2).padStart(64, '0'));
  assert.equal(d.length, 2 + 8 + 128);
  assert.throws(() => guardCalldata(SNTL, 1n));
  assert.throws(() => guardCalldata('0x123', 1n));
  assert.throws(() => guardCalldata(TOKEN, 0n));
});
test('quantity formatting preserves all 18 decimals without Number rounding', () => {
  assert.equal(tokenAmount('24860397533712448875904953'), '24,860,397.533712448875904953');
  assert.equal(tokenAmount('24860397533712448875904953', 4), '24,860,397.5337');
  assert.equal(tokenAmount('1'), '0.000000000000000001');
  assert.equal(burnPercent({...snapshot, mintedRaw: '1000000000000000000000000000', burnedRaw: '24860397533712448875904953'}), '2.4860');
});
const copies = JSON.parse(readFileSync(new URL('../public/copies.json', import.meta.url)));
test('published copies snapshot names the official token and lists no official address', () => {
  assert.equal(validateCopies(copies, SNTL), copies);
});
test('copies snapshot: wrong identity, official listed as a copy, bad counts and unsafe fields are rejected', () => {
  const copy = { token: '0x' + 'a'.repeat(40), deployer: '0x' + 'b'.repeat(40), block: copies.block - 1, symbol: 'SNTL', name: 'Sentinel' };
  const ok = { ...copies, copyCount: 1, copies: [copy] };
  assert.equal(validateCopies(ok, SNTL), ok);
  for (const patch of [{ official: '0x' + '1'.repeat(40) }, { chainId: 1 }, { copyCount: 0 }, { copyCount: 1, copies: [] },
    { copies: [{ ...copy, token: SNTL }] }, { copies: [{ ...copy, token: '" onmouseover="x' }] },
    { copies: [{ ...copy, block: copies.block + 1 }] }, { copies: [{ ...copy, symbol: 'x'.repeat(65) }] },
    { generatedAt: 'nope' }, { copyCount: copies.launches + 1 }]) {
    assert.throws(() => validateCopies({ ...ok, ...patch }, SNTL), undefined, JSON.stringify(patch));
  }
  assert.throws(() => validateCopies(copies, '0x' + '1'.repeat(40)));
  assert.throws(() => validateCopies(null, SNTL));
});
