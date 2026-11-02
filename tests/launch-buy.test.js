import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { launchBuy, deployerHolds, deployerExit, CURVE_BUY, TRANSFER, V4_POOL_MANAGER } from '../api/service.js';

// Real launch receipt from Robinhood Chain, read-only capture (see fixture tx/block).
const FX = JSON.parse(readFileSync(new URL('./fixtures/launch-receipt.json', import.meta.url)));

test('launchBuy reads the real launch receipt: share of supply and deployer', () => {
  const r = launchBuy(FX.receipt, FX.curve, FX.deployer);
  assert.equal(r.buys, FX.expect.buys);
  assert.equal(r.wallets, 1);
  assert.equal(r.byDeployer, true);
  assert.equal(r.supplyPercent, '3.9231');
  assert.equal(r.deployerTokens, FX.expect.tokensRaw);
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
  assert.deepEqual(r, { buys: 3, wallets: 2, byDeployer: true, supplyPercent: '11.0000', deployerTokens: (5n * 10n ** 25n).toString() });
});

test('launchBuy ignores other contracts, other events and malformed logs', () => {
  const logs = [
    buy(DEP, 10n ** 26n, OTHER),                                    // same event, wrong curve
    { ...buy(DEP, 10n ** 26n), topics: ['0x' + 'ab'.repeat(32), addrTopic(OTHER), addrTopic(DEP)] }, // other event
    { ...buy(DEP, 10n ** 26n), data: '0x' + pad(1) },              // short data
    { ...buy(DEP, 10n ** 26n), topics: [CURVE_BUY, addrTopic(DEP)] }, // missing recipient
    null,
  ];
  assert.deepEqual(launchBuy({ logs }, CURVE, DEP), { buys: 0, wallets: 0, byDeployer: false, supplyPercent: '0.0000', deployerTokens: '0' });
});

test('launchBuy: buyer that is not the deployer', () => {
  assert.equal(launchBuy({ logs: [buy(OTHER, 10n ** 25n)] }, CURVE, DEP).byDeployer, false);
});

test('launchBuy returns null without a receipt', () => {
  assert.equal(launchBuy(null, CURVE, DEP), null);
  assert.equal(launchBuy({}, CURVE, DEP), null);
});

const bal = (n) => '0x' + pad(n);
test('deployerHolds: share of the launch buy still in the deployer wallet', () => {
  const bought = (4n * 10n ** 25n).toString();
  assert.equal(deployerHolds(bought, bal(4n * 10n ** 25n)), '100.0000');
  assert.equal(deployerHolds(bought, bal(10n ** 25n)), '25.0000');
  assert.equal(deployerHolds(bought, bal(0n)), '0.0000');
});

test('deployerHolds caps at 100 when the deployer bought more later', () => {
  assert.equal(deployerHolds('1000', bal(5000n)), '100.0000');
});

test('deployerHolds returns null on bad input instead of guessing', () => {
  assert.equal(deployerHolds('0', bal(1n)), null);
  assert.equal(deployerHolds('1000', null), null);
  assert.equal(deployerHolds('1000', '0x'), null);
  assert.equal(deployerHolds('1000', '0x' + pad(1n) + pad(2n)), null);
  assert.equal(deployerHolds('-5', bal(1n)), null);
  assert.equal(deployerHolds('abc', bal(1n)), null);
});

const TOKEN = '0x' + '5'.repeat(40);
const xfer = (from, to, amt, extra = {}) => ({ address: TOKEN, topics: [TRANSFER, addrTopic(from), addrTopic(to)], data: '0x' + pad(amt), ...extra });

test('deployerExit splits outflow into sold, burned and sent', () => {
  const logs = [xfer(DEP, CURVE, 50n), xfer(DEP, V4_POOL_MANAGER, 10n), xfer(DEP, '0x' + '0'.repeat(40), 20n),
    xfer(DEP, '0x000000000000000000000000000000000000dEaD', 10n), xfer(DEP, OTHER, 5n), xfer(DEP, '0x' + '6'.repeat(40), 5n)];
  assert.deepEqual(deployerExit(logs, TOKEN, CURVE, DEP), { soldPercent: '60.0000', burnedPercent: '30.0000', sentPercent: '10.0000', sentTo: 2 });
});

test('deployerExit counts a router sell as sold when the same tx moved the token into the curve', () => {
  const ROUTER = '0x' + '7'.repeat(40);
  const logs = [xfer(DEP, ROUTER, 80n, { transactionHash: '0xAA' }), xfer(DEP, OTHER, 20n, { transactionHash: '0xbb' })];
  assert.deepEqual(deployerExit(logs, TOKEN, CURVE, DEP, new Set(['0xaa'])), { soldPercent: '80.0000', burnedPercent: '0.0000', sentPercent: '20.0000', sentTo: 1 });
  assert.equal(deployerExit(logs, TOKEN, CURVE, DEP).sentPercent, '100.0000');
});

test('deployerExit: all burned, like $SNTL', () => {
  assert.deepEqual(deployerExit([xfer(DEP, '0x' + '0'.repeat(40), 7n)], TOKEN, CURVE, DEP), { soldPercent: '0.0000', burnedPercent: '100.0000', sentPercent: '0.0000', sentTo: 0 });
});

test('deployerExit ignores other tokens, other senders, removed and malformed logs', () => {
  const logs = [{ ...xfer(DEP, CURVE, 9n), address: OTHER }, xfer(OTHER, CURVE, 9n), xfer(DEP, CURVE, 9n, { removed: true }),
    { ...xfer(DEP, CURVE, 9n), data: '0x' }, { ...xfer(DEP, CURVE, 9n), topics: [TRANSFER, addrTopic(DEP)] }, null];
  assert.deepEqual(deployerExit(logs, TOKEN, CURVE, DEP), { soldPercent: null, burnedPercent: null, sentPercent: null, sentTo: 0 });
  assert.equal(deployerExit(null, TOKEN, CURVE, DEP), null);
});
