import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validate, CACHE, parseInitialize, classifyPools, MEME_HOOK, V4_INITIALIZE } from '../api/service.js';

// TACKLE, graduated 2026-11-04. Official pool id recomputed with keccak256(abi.encode(PoolKey)) and matched on chain.
const TOKEN = '0x775f392231ac4f95b2ab9d21a4a7e50576e05b71';
const OFFICIAL = '0x387e6f164a59d063ce9826345e840902e9a44b24f69f6f70bc714d9d682d557d';
const ZERO = '0x' + '0'.repeat(40);
const pad = (a) => '0x' + a.slice(2).padStart(64, '0');
const word = (n) => BigInt.asUintN(256, BigInt(n)).toString(16).padStart(64, '0');
const log = (id, c0, c1, fee, spacing, hooks) => ({topics: [V4_INITIALIZE, id, pad(c0), pad(c1)],
  data: '0x' + word(fee) + word(spacing) + hooks.slice(2).padStart(64, '0') + word(1) + word(0)});
const rec = {token: TOKEN, pairToken: ZERO, poolFee: 0, tickSpacing: 200, phase: 2};

test('pools action requires a plain address and is edge-cached', () => {
  validate('pools', TOKEN);
  for (const v of [undefined, '0x12', [TOKEN]]) assert.throws(() => validate('pools', v));
  assert.match(CACHE.pools, /s-maxage=\d+/);
});

test('parseInitialize reads the PoolKey, including a negative tick spacing', () => {
  const p = parseInitialize(log(OFFICIAL, ZERO, TOKEN, 0, 200, MEME_HOOK));
  assert.deepEqual(p, {poolId: OFFICIAL, currency0: ZERO, currency1: TOKEN, fee: 0, tickSpacing: 200, hooks: MEME_HOOK});
  assert.equal(parseInitialize(log(OFFICIAL, ZERO, TOKEN, 0, -60, ZERO)).tickSpacing, -60);
  assert.equal(parseInitialize({topics: [V4_INITIALIZE], data: '0x'}), null);
  assert.equal(parseInitialize({...log(OFFICIAL, ZERO, TOKEN, 0, 200, MEME_HOOK), removed: true}), null);
});

test('classifyPools names the official pool and counts the rest', () => {
  const logs = [log(OFFICIAL, ZERO, TOKEN, 0, 200, MEME_HOOK),
    log('0x' + '1'.repeat(64), ZERO, TOKEN, 790000, 60, ZERO),   // 79%, no hook (live pattern)
    log('0x' + '2'.repeat(64), ZERO, TOKEN, 18000, 180, ZERO),   // 1.8%, no hook
    log('0x' + '3'.repeat(64), ZERO, TOKEN, 0x800000, 60, '0x' + 'e'.repeat(40)),  // dynamic fee, other hook
    log('0x' + '1'.repeat(64), ZERO, TOKEN, 790000, 60, ZERO)];  // same pool seen twice: counted once
  assert.deepEqual(classifyPools(logs, rec), {official: OFFICIAL, others: 3, othersNoHook: 2, othersHalfFee: 1});
});

test('a pool is official only if every PoolKey field matches the record', () => {
  for (const [c0, c1, fee, spacing, hooks] of [[ZERO, TOKEN, 0, 200, ZERO], [ZERO, TOKEN, 3000, 200, MEME_HOOK],
    [ZERO, TOKEN, 0, 60, MEME_HOOK], ['0x' + '5f'.repeat(20), TOKEN, 0, 200, MEME_HOOK]]) {
    assert.equal(classifyPools([log(OFFICIAL, c0, c1, fee, spacing, hooks)], rec).official, null, `${fee} ${spacing} ${hooks}`);
  }
  assert.deepEqual(classifyPools([], rec), {official: null, others: 0, othersNoHook: 0, othersHalfFee: 0});
});
