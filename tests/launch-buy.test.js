import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { launchBuy, CURVE_BUY } from '../api/service.js';

// Real launch receipt from Robinhood Chain, read-only capture (see fixture tx/block).
const FX = JSON.parse(readFileSync(new URL('./fixtures/launch-receipt.json', import.meta.url)));

test('launchBuy reads the real launch receipt: share of supply and deployer', () => {
  const r = launchBuy(FX.receipt, FX.curve, FX.deployer);
  assert.equal(r.buys, FX.expect.buys);
  assert.equal(r.wallets, 1);
  assert.equal(r.byDeployer, true);
  assert.equal(r.supplyPercent, '3.9231');
});

test('launchBuy is case-insensitive on curve and deployer', () => {
  assert.deepEqual(launchBuy(FX.receipt, FX.curve.toUpperCase().replace('0X', '0x'), FX.deployer.toUpperCase().replace('0X', '0x')),
    launchBuy(FX.receipt, FX.curve, FX.deployer));
});

const pad = (n) => BigInt(n).toString(16).padStart(64, '0');
const addrTopic = (a) => '0x' + a.slice(2).padStart(64, '0');
const CURVE = '0x' + '1'.repeat(40), DEP = '0x' + '2'.repeat(40), OTHER = '0x' + '3'.repeat(40);
const buy = (to, tokens, address = CURVE) => ({ address, topics: [CURVE_BUY, addrTopic(OTHER), addrTopic(to)], data: '0x' + pad(10n ** 15n) + pad(tokens) + pad(1) + pad(2) });

test('launchBuy sums several buys and counts distinct recipients', () => {
  const r = launchBuy({ logs: [buy(DEP, 5n * 10n ** 25n), buy(OTHER, 5n * 10n ** 25n), buy(OTHER, 10n ** 25n)] }, CURVE, DEP);
  assert.deepEqual(r, { buys: 3, wallets: 2, byDeployer: true, supplyPercent: '11.0000' });
});

test('launchBuy ignores other contracts, other events and malformed logs', () => {
  const logs = [
    buy(DEP, 10n ** 26n, OTHER),                                    // same event, wrong curve
    { ...buy(DEP, 10n ** 26n), topics: ['0x' + 'ab'.repeat(32), addrTopic(OTHER), addrTopic(DEP)] }, // other event
    { ...buy(DEP, 10n ** 26n), data: '0x' + pad(1) },              // short data
    { ...buy(DEP, 10n ** 26n), topics: [CURVE_BUY, addrTopic(DEP)] }, // missing recipient
    null,
  ];
  assert.deepEqual(launchBuy({ logs }, CURVE, DEP), { buys: 0, wallets: 0, byDeployer: false, supplyPercent: '0.0000' });
});

test('launchBuy: buyer that is not the deployer', () => {
  assert.equal(launchBuy({ logs: [buy(OTHER, 10n ** 25n)] }, CURVE, DEP).byDeployer, false);
});

test('launchBuy returns null without a receipt', () => {
  assert.equal(launchBuy(null, CURVE, DEP), null);
  assert.equal(launchBuy({}, CURVE, DEP), null);
});
