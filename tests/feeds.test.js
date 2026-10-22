import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validate, CACHE, parseLaunchLog, toCommit, summariseHistory, TOKEN_LAUNCHED, PONS_FACTORY } from '../api/service.js';

// Real TokenLaunched log captured from the Pons v2 factory on chain 4663.
const LOG = {
  address: '0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e',
  topics: [TOKEN_LAUNCHED,
    '0x00000000000000000000000057c140bfe79001d29c3d1108f461bd977198480f',
    '0x0000000000000000000000000092be1e96edd3d895571f671c367f7121e70057',
    '0x00000000000000000000000045cde31e37365c5cd378135e93bea0d0f89cb9d5'],
  data: '0x', blockNumber: '0x59edb3b', logIndex: '0xf', removed: false,
  transactionHash: '0x0914fbe9cac7f56dc0bb1dd4f7c53336677f74cf6169b985a03e440390e398c8',
};

test('launches and shiplog are known, value-free and edge-cached', () => {
  validate('launches'); validate('shiplog');
  assert.ok(CACHE.launches.includes('s-maxage=60'));
  assert.ok(CACHE.shiplog.includes('s-maxage=600'));
});

test('a real TokenLaunched log parses to token, curve, deployer, block', () => {
  assert.deepEqual(parseLaunchLog(LOG), {
    token: '0x57c140bfe79001d29c3d1108f461bd977198480f', curve: '0x0092be1e96edd3d895571f671c367f7121e70057',
    deployer: '0x45cde31e37365c5cd378135e93bea0d0f89cb9d5', block: 94296891, logIndex: 15, tx: LOG.transactionHash,
  });
  assert.equal(PONS_FACTORY.toLowerCase(), LOG.address);
});

test('spoofed, removed or malformed logs are dropped', () => {
  for (const patch of [{ address: '0x' + '1'.repeat(40) }, { removed: true }, { topics: LOG.topics.slice(0, 3) },
    { topics: ['0x' + 'a'.repeat(64), ...LOG.topics.slice(1)] }, { topics: [TOKEN_LAUNCHED, 'bad', ...LOG.topics.slice(2)] },
    { blockNumber: 'nope' }, { transactionHash: '0x12' }]) {
    assert.equal(parseLaunchLog({ ...LOG, ...patch }), null);
  }
  assert.equal(parseLaunchLog(null), null);
});

test('deployer action needs a token address and is edge-cached', () => {
  validate('deployer', '0x' + '1'.repeat(40));
  for (const v of [undefined, '0x12', ['0x' + '1'.repeat(40)]]) assert.throws(() => validate('deployer', v));
  assert.ok(CACHE.deployer.includes('s-maxage=300'));
});

test('deployer history: counts own launches only, dedupes, numbers the current token', () => {
  const dep = LOG.topics[3].replace(/^0x0{24}/, '0x');
  const mk = (n, block, deployer = LOG.topics[3]) => ({ ...LOG, blockNumber: '0x' + block.toString(16),
    topics: [TOKEN_LAUNCHED, '0x' + n.toString(16).padStart(64, '0'), LOG.topics[2], deployer] });
  const other = '0x' + '0'.repeat(24) + 'b'.repeat(40);
  const logs = [mk(1, 100), mk(2, 300), mk(3, 200), mk(3, 200), mk(4, 400, other), { ...mk(5, 500), removed: true }];
  const tok = (n) => '0x' + n.toString(16).padStart(40, '0');
  const s = summariseHistory(logs, dep, tok(3));
  assert.equal(s.deployer, dep);
  assert.equal(s.launches, 3); // own, deduped, other deployer + removed log dropped
  assert.equal(s.firstBlock, 100);
  assert.equal(s.latestBlock, 300);
  assert.equal(s.launchNumber, 2); // blocks 100, 200, 300 -> the token at 200 is the 2nd launch
  assert.deepEqual(s.recent.map((r) => r.block), [300, 200, 100]);
  assert.equal(summariseHistory([], dep, tok(3)).launches, 0);
  assert.equal(summariseHistory(logs, dep, tok(9)).launchNumber, null);
});

test('commits: conventional prefix stripped, type kept, junk dropped', () => {
  const c = (message, sha = 'a'.repeat(40), date = '2026-10-21T11:44:00Z') => toCommit({ sha, commit: { message, committer: { date } } });
  assert.deepEqual(c('feat(inspector): token check\n\nbody'), { sha: 'aaaaaaa', url: `https://github.com/sentinelhood/robinhood-sentinel/commit/${'a'.repeat(40)}`, title: 'token check', type: 'feat', date: '2026-10-21T11:44:00.000Z' });
  assert.equal(c('ui: tidy').type, 'ui');
  assert.equal(c('token panel: tweet link optional').type, 'other');
  assert.equal(c('Plain message').title, 'Plain message');
  assert.equal(c('x'.repeat(300)).title.length, 140);
  for (const bad of [c(''), c('ok', 'nothex'), c('ok', 'a'.repeat(40), 'not a date'), toCommit(null), toCommit({})]) assert.equal(bad, null);
});
