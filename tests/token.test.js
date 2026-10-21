import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validate, decodeLaunch, decodeString, formatUnits, percentOf, delegation } from '../api/service.js';

// Raw getLaunchedToken(SNTL) response captured from the Pons v2 factory on chain 4663.
const SNTL_LAUNCH = '0x' + [
  '0000000000000000000000002da80b9d1bc1b323693c80c76eb4a321ec08cbd0',
  '000000000000000000000000369907394da08b8b07c9e2db623899c2d79a4b2a',
  '00000000000000000000000053cccdeba2714074d0702d2b6459cbcb19c61784',
  '00000000000000000000000053cccdeba2714074d0702d2b6459cbcb19c61784',
  '0000000000000000000000000000000000000000000000000000000000000000',
  '0000000000000000000000000000000000000000000000003a4965bf58a40000',
  '0000000000000000000000000000000000000000000000000000000000000000',
  '00000000000000000000000000000000000000000000000000000000000000c8',
  '000000000000000000000000000000000000000000000000000000000000012c',
  '0000000000000000000000000000000000000000000000000000000000000000',
  '0000000000000000000000000000000000000000000000000000000000000002',
  '0000000000000000000000000000000000000000000000000000000000000000',
  '0000000000000000000000000000000000000000000000000000000000000000',
  '0000000000000000000000000000000000000000000000000000000000000000',
  '0000000000000000000000000000000000000000000000000000000000000001',
].join('');

test('token action requires an address', () => {
  validate('token', '0x' + '1'.repeat(40));
  for (const v of [undefined, '0x12', ['0x' + '1'.repeat(40)]]) assert.throws(() => validate('token', v));
});

test('decodes the real SNTL factory record', () => {
  const l = decodeLaunch(SNTL_LAUNCH);
  assert.equal(l.token, '0x2da80b9d1bc1b323693c80c76eb4a321ec08cbd0');
  assert.equal(l.curve, '0x369907394da08b8b07c9e2db623899c2d79a4b2a');
  assert.equal(l.deployer, '0x53cccdeba2714074d0702d2b6459cbcb19c61784');
  assert.equal(l.pairToken, '0x' + '0'.repeat(40));
  assert.equal(l.graduationThresholdWei, '4200000000000000000');
  assert.equal(l.tickSpacing, 200);
  assert.equal(l.creatorTaxBps, 300);
  assert.equal(l.buybackEnabled, false);
  assert.equal(l.phase, 2);
});

test('unknown token (all zeros) is no record; malformed responses throw', () => {
  assert.equal(decodeLaunch('0x' + '0'.repeat(64 * 15)), null);
  for (const bad of ['0x', '0x1234', SNTL_LAUNCH.slice(0, -64), null, 'nope']) assert.throws(() => decodeLaunch(bad));
});

test('negative tickSpacing decodes as int24', () => {
  const w = SNTL_LAUNCH.slice(2).match(/.{64}/g);
  w[7] = 'f'.repeat(64);
  assert.equal(decodeLaunch('0x' + w.join('')).tickSpacing, -1);
});

test('strings: ABI string, bytes32 fallback, control chars stripped, length capped', () => {
  const word = (n) => n.toString(16).padStart(64, '0');
  const abi = (s) => {
    const h = Buffer.from(s).toString('hex');
    return '0x' + word(32) + word(h.length / 2) + h.padEnd(Math.max(64, Math.ceil(h.length / 64) * 64), '0');
  };
  assert.equal(decodeString(abi('Sentinel')), 'Sentinel');
  assert.equal(decodeString('0x' + Buffer.from('MKR').toString('hex').padEnd(64, '0')), 'MKR');
  assert.equal(decodeString(abi('a\u0000b\u001b[31mc')), 'ab[31mc');
  assert.equal(decodeString(abi('x'.repeat(200))).length, 64);
  assert.equal(decodeString(null), null);
  assert.equal(decodeString('0x'), null);
});

test('formatUnits and percentOf use BigInt only', () => {
  assert.equal(formatUnits(969326066451500000000000000n, 18), '969,326,066.4515');
  assert.equal(formatUnits(0n, 18), '0');
  assert.equal(formatUnits(1234567n, 6, 2), '1.23');
  assert.equal(formatUnits(5n, 0), '5');
  assert.equal(percentOf(30000000n, 1000000000n), '3.0000');
  assert.equal(percentOf(1n, 0n), null);
});

test('EIP-7702 delegated wallets are detected, real contracts are not', () => {
  assert.equal(delegation('0xef010063c0c19a282a1b52b07dd5a65b58948a07dae32b'), '0x63c0c19a282a1b52b07dd5a65b58948a07dae32b');
  assert.equal(delegation('0x'), null);
  assert.equal(delegation('0x6080604052'), null);
  assert.equal(delegation('0xef0100' + '1'.repeat(42)), null);
});
