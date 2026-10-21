import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validate, reviewState, toContribution, CACHE } from '../api/service.js';

test('contributions action is accepted and edge-cached', () => {
  validate('contributions');
  assert.ok(CACHE.contributions.includes('s-maxage=900'));
});

test('latest review per reviewer wins; any open change request blocks approval', () => {
  const r = (login, state) => ({ user: { login }, state });
  assert.equal(reviewState([]), 'review');
  assert.equal(reviewState(null), 'review');
  assert.equal(reviewState([r('a', 'COMMENTED')]), 'review');
  assert.equal(reviewState([r('a', 'APPROVED')]), 'approved');
  assert.equal(reviewState([r('a', 'CHANGES_REQUESTED')]), 'changes_requested');
  assert.equal(reviewState([r('a', 'CHANGES_REQUESTED'), r('a', 'APPROVED')]), 'approved');
  assert.equal(reviewState([r('a', 'APPROVED'), r('b', 'CHANGES_REQUESTED')]), 'changes_requested');
  assert.equal(reviewState([r('a', 'CHANGES_REQUESTED'), r('a', 'COMMENTED')]), 'changes_requested');
  assert.equal(reviewState([r('a', 'CHANGES_REQUESTED'), r('a', 'DISMISSED')]), 'review');
});

test('search items map to merged / open / closed with a date', () => {
  const base = { number: 7, title: 't', state: 'open', created_at: '2026-10-20T19:35:00Z', pull_request: { merged_at: null } };
  assert.deepEqual(toContribution(base), { pr: 7, title: 't', state: 'open', when: '2026-10-20' });
  assert.equal(toContribution({ ...base, state: 'closed', pull_request: { merged_at: '2026-10-21T01:00:00Z' } }).state, 'merged');
  assert.equal(toContribution({ ...base, state: 'closed', closed_at: '2026-10-22T00:00:00Z' }).when, '2026-10-22');
  assert.equal(toContribution({ ...base, state: 'closed' }).state, 'closed');
});

test('malformed search items are dropped', () => {
  for (const bad of [null, {}, { number: -1, title: 't', pull_request: {} }, { number: 1, title: 5, pull_request: {} }, { number: 1, title: 't' }]) {
    assert.equal(toContribution(bad), null);
  }
  assert.equal(toContribution({ number: 1, title: 'x'.repeat(500), pull_request: {}, created_at: 'nope' }).title.length, 160);
  assert.equal(toContribution({ number: 1, title: 't', pull_request: {}, created_at: 'nope' }).when, '');
});
