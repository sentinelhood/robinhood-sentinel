import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateMovers, quoteAmount } from '../src/movers.ts';

const published = JSON.parse(readFileSync(new URL('../public/movers.json', import.meta.url)));
const mover = {token: '0x5fea0f4e7239907602bb779c52a559279f542f45', symbol: 'CHARLIE', name: 'Charlie', buys: 351, sells: 6, traders: 110,
  topTraderTrades: 12, topRecipientKind: 'wallet', topTraderShare: 3.4,
  volumeRaw: '706800000000000000', netRaw: '679500000000000000', pairSymbol: 'ETH', pairDecimals: 18, phase: 0, progress: 63.8};
const snap = {chainId: 4663, block: 98367569, windowHours: 6, generatedAt: '2026-10-26T12:00:00+00:00', trades: 9627, curves: 540, skipped: 0,
  movers: [mover, {...mover, token: '0x' + 'd'.repeat(40), symbol: 'REACHY', buys: 300, sells: 20, netRaw: '-41600000000000000170',
    pairSymbol: 'NVDA', phase: 2, progress: null, topTraderTrades: 160, topRecipientKind: 'contract', topTraderShare: null}]};

test('published movers snapshot validates', () => {
  assert.equal(validateMovers(published), published);
  assert.equal(validateMovers(snap), snap);
});

test('movers: reject wrong chain, bad shapes, unsafe text and impossible numbers', () => {
  for (const patch of [{chainId: 1}, {block: -1}, {windowHours: 0}, {windowHours: 48}, {generatedAt: 'bad'}, {trades: 1.5},
    {curves: 10000000}, {movers: 'x'}, {movers: Array(26).fill(mover)}]) {
    assert.throws(() => validateMovers({...snap, ...patch}), undefined, JSON.stringify(patch).slice(0, 60));
  }
  for (const m of [{token: '0xABC'}, {token: '0x' + 'A'.repeat(40)}, {symbol: '<img src=x onerror=alert(1)>'.repeat(4)}, {symbol: ''},
    {buys: 0, sells: 0}, {traders: 0}, {traders: 999}, {volumeRaw: '1e18'}, {volumeRaw: '-1'}, {netRaw: '1.5'}, {netRaw: '-0'},
    {pairDecimals: 255}, {phase: 4}, {progress: 101}, {progress: -1}, {phase: 2, progress: 50},
    {topTraderTrades: 0}, {topTraderTrades: 400}, {topTraderTrades: 1}, {topTraderShare: 50}, {topTraderShare: '3.4'}, {topTraderShare: undefined},
    {topTraderShare: null}, {topRecipientKind: 'router'}, {topRecipientKind: undefined}]) {
    assert.throws(() => validateMovers({...snap, movers: [{...mover, ...m}]}), undefined, JSON.stringify(m).slice(0, 60));
  }
  assert.throws(() => validateMovers({...snap, movers: [mover, mover]}), undefined, 'duplicate token');
  assert.throws(() => validateMovers({...snap, movers: [{...mover, buys: 1, sells: 0, traders: 1}, mover]}), undefined, 'not ranked');
  const fewTraders = {...mover, token: '0x' + 'e'.repeat(40), buys: 1076, sells: 0, traders: 1, topTraderTrades: 1076, topRecipientKind: 'wallet', topTraderShare: 100};
  assert.throws(() => validateMovers({...snap, movers: [fewTraders, mover]}), undefined, 'one-wallet spam above more traders');
  assert.throws(() => validateMovers({...snap, movers: [{...mover, buys: 10}, {...mover, token: fewTraders.token}]}), undefined, 'tie on traders, fewer trades first');
  assert.throws(() => validateMovers(null));
});

test('movers: one-wallet curve must report 100% from that wallet', () => {
  const solo = {...mover, buys: 50, sells: 0, traders: 1, topTraderTrades: 50, topRecipientKind: 'wallet', topTraderShare: 100};
  assert.equal(validateMovers({...snap, movers: [solo]}).movers[0].topTraderShare, 100);
  assert.throws(() => validateMovers({...snap, movers: [{...solo, topTraderTrades: 40, topTraderShare: 80}]}));
});

test('movers: a contract recipient must not carry a share', () => {
  const router = snap.movers[1];
  assert.equal(validateMovers({...snap, movers: [router]}).movers[0].topTraderShare, null);
  assert.throws(() => validateMovers({...snap, movers: [{...router, topTraderShare: 49.7}]}), undefined, 'contract with a %');
  assert.equal(validateMovers({...snap, movers: [{...router, topRecipientKind: null}]}).movers[0].topRecipientKind, null);
});

test('quoteAmount formats with BigInt, any decimals, sign kept', () => {
  assert.equal(quoteAmount('54900102780323002913', 18), '54.9001');
  assert.equal(quoteAmount('-41600000000000000170', 18), '-41.6');
  assert.equal(quoteAmount('8090000005', 6), '8,090');
  assert.equal(quoteAmount('193502872457166550000000', 18, 2), '193,502.87');
  assert.equal(quoteAmount('0', 18), '0');
  assert.equal(quoteAmount('123', 0), '123');
});
