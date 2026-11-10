"""Offline tests for skills/pons-pool-check. No network.

Run: python3 tests/test_pons_pool_check.py
"""
import io, json, sys, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills' / 'pons-pool-check'))
import pons_pool_check as ppc  # noqa: E402

TOKEN = '0x775f392231ac4f95b2ab9d21a4a7e50576e05b71'  # TACKLE, graduated 2026-11-04
OFFICIAL_ID = '0x387e6f164a59d063ce9826345e840902e9a44b24f69f6f70bc714d9d682d557d'  # recomputed with keccak256, matches chain
PAIR = '0x' + '5f' * 20  # stand-in ERC-20 pair token
W = lambda v: format(v, '064x')
A = lambda a: a[2:].rjust(64, '0')


def record(phase=2, fee=0, spacing=200, pair=ppc.ZERO, exists=1):
    words = [A(TOKEN), A('0x' + 'c' * 40), A('0x' + 'd' * 40), A('0x' + 'd' * 40), A(pair), W(42 * 10 ** 17),
             W(fee), W(spacing & 0xFFFFFF), W(0), W(0), W(phase), W(0), W(0), W(0), W(exists)]
    return '0x' + ''.join(words)


def init_log(pool_id, c0, c1, fee, spacing, hooks, block=29_000_000, tx='0x' + 'a' * 64):
    return {'topics': [ppc.INITIALIZE, pool_id, '0x' + A(c0), '0x' + A(c1)], 'blockNumber': hex(block), 'transactionHash': tx,
            'data': '0x' + W(fee) + W(spacing & 0xFFFFFF) + A(hooks) + W(1) + W(0)}


class Pure(unittest.TestCase):
    def test_decode_record_and_signed_spacing(self):
        r = ppc.decode_record(record())
        self.assertEqual((r['token'], r['pairToken'], r['poolFee'], r['tickSpacing'], r['phase']), (TOKEN, ppc.ZERO, 0, 200, 2))
        self.assertEqual(ppc.decode_record(record(spacing=-60))['tickSpacing'], -60)
        self.assertIsNone(ppc.decode_record(record(exists=0)))
        self.assertIsNone(ppc.decode_record('0x1234'))

    def test_parse_initialize(self):
        p = ppc.parse_initialize(init_log(OFFICIAL_ID, ppc.ZERO, TOKEN, 0, 200, ppc.MEME_HOOK))
        self.assertEqual((p['poolId'], p['currency1'], p['hooks'], p['fee'], p['tickSpacing']), (OFFICIAL_ID, TOKEN, ppc.MEME_HOOK, 0, 200))
        self.assertIsNone(ppc.parse_initialize({'topics': ['0x' + '1' * 64], 'data': '0x'}))
        self.assertIsNone(ppc.parse_initialize(dict(init_log(OFFICIAL_ID, ppc.ZERO, TOKEN, 0, 200, ppc.MEME_HOOK), removed=True)))

    def test_official_needs_every_field(self):
        rec = ppc.decode_record(record())
        good = ppc.parse_initialize(init_log(OFFICIAL_ID, ppc.ZERO, TOKEN, 0, 200, ppc.MEME_HOOK))
        self.assertTrue(ppc.is_official(good, rec))
        # Live 2026-11-05: copies differ in hook, fee or pair. Each one alone must disqualify a pool.
        for change in ({'hooks': ppc.ZERO}, {'fee': 18000}, {'tickSpacing': 60}, {'currency0': PAIR}, {'hooks': '0x' + 'e' * 40}):
            self.assertFalse(ppc.is_official(dict(good, **change), rec), change)

    def test_custom_pair_sorting(self):
        rec = ppc.decode_record(record(pair=PAIR))
        lo, hi = sorted([TOKEN, PAIR])
        p = ppc.parse_initialize(init_log('0x' + '9' * 64, lo, hi, 0, 200, ppc.MEME_HOOK))
        self.assertTrue(ppc.is_official(p, rec))

    def test_classify_orders_others_by_activity(self):
        rec = ppc.decode_record(record())
        official = dict(ppc.parse_initialize(init_log(OFFICIAL_ID, ppc.ZERO, TOKEN, 0, 200, ppc.MEME_HOOK)), swaps=1168)
        a = dict(ppc.parse_initialize(init_log('0x' + '1' * 64, ppc.ZERO, TOKEN, 790000, 60, ppc.ZERO, block=5)), swaps=5)
        b = dict(ppc.parse_initialize(init_log('0x' + '2' * 64, ppc.ZERO, TOKEN, 18000, 180, ppc.ZERO, block=9)), swaps=137)
        o, others = ppc.classify([a, official, b], rec)
        self.assertEqual([x['poolId'] for x in o], [OFFICIAL_ID])
        self.assertEqual([x['poolId'] for x in others], [b['poolId'], a['poolId']])

    def test_fee_label(self):
        self.assertEqual(ppc.fee_label(18000), '1.8%')
        self.assertEqual(ppc.fee_label(999000), '99.9%')
        self.assertEqual(ppc.fee_label(0x800000), 'dynamic (set by its hook)')


class EndToEnd(unittest.TestCase):
    def run_main(self, rec, logs, swaps=None, liquidity=1, args=()):
        swaps = swaps or {}

        def fake_rpc(method, params):
            if method == 'eth_chainId':
                return hex(4663)
            if method == 'eth_blockNumber':
                return hex(30_000_000)
            if method == 'eth_call':
                to, data = params[0]['to'], params[0]['data']
                if to == ppc.FACTORY:
                    return rec
                if to == ppc.STATE_VIEW:
                    return '0x' + W(liquidity)
                return '0x' + W(32) + W(3) + '544b4c'.ljust(64, '0')  # symbol "TKL"
            if method == 'eth_getLogs':
                f = params[0]
                if f['topics'][0] == ppc.INITIALIZE:
                    slot = 2 if f['topics'][2] else 3
                    lo, hi = int(f['fromBlock'], 16), int(f['toBlock'], 16)
                    return [l for l in logs if l['topics'][slot] == f['topics'][slot] and lo <= int(l['blockNumber'], 16) <= hi]
                return [{'topics': [ppc.SWAP, pid]} for pid in f['topics'][1] for _ in range(swaps.get(pid, 0))
                        if int(f['fromBlock'], 16) <= 30_000_000 < int(f['fromBlock'], 16) + ppc.SWAP_STEP]
            raise AssertionError(method)

        out = io.StringIO()
        with mock.patch.object(ppc, 'rpc', side_effect=fake_rpc), redirect_stdout(out):
            code = ppc.main([TOKEN, '--json', *args])
        return code, (json.loads(out.getvalue()) if out.getvalue() else None)

    def test_graduated_token_with_copies(self):
        logs = [init_log(OFFICIAL_ID, ppc.ZERO, TOKEN, 0, 200, ppc.MEME_HOOK),
                init_log('0x' + '1' * 64, ppc.ZERO, TOKEN, 790000, 60, ppc.ZERO)]
        code, r = self.run_main(record(), logs, swaps={OFFICIAL_ID: 3})
        self.assertEqual(code, 0)
        self.assertEqual(r['official']['poolId'], OFFICIAL_ID)
        self.assertEqual(r['official']['swaps'], 3)
        self.assertEqual(len(r['others']), 1)
        md = ppc.to_markdown(r)
        self.assertIn('Official Pons pool', md)
        self.assertIn('1 with no hook · 1 with a pool fee of 10% or more', md)

    def test_logs_seen_from_both_slots_are_not_double_counted(self):
        log = init_log('0x' + '3' * 64, ppc.ZERO, TOKEN, 500000, 60, ppc.ZERO)
        _, r = self.run_main(record(), [log, log])
        self.assertEqual(len(r['others']), 1)

    def test_curve_token_points_to_the_curve(self):
        _, r = self.run_main(record(phase=0), [])
        self.assertIsNone(r['official'])
        self.assertIn('still trades on its Pons bonding curve', ppc.to_markdown(r))
        self.assertNotIn('made by someone else', ppc.to_markdown(r))

    def test_pools_before_graduation_are_never_official(self):
        # Live 2026-11-10: 5 of the 9 busiest curves already had v4 pools, most at a 50%+ fee.
        logs = [init_log('0x' + '4' * 64, ppc.ZERO, TOKEN, 990000, 60, ppc.ZERO)]
        _, r = self.run_main(record(phase=0), logs)
        self.assertIsNone(r['official'])
        self.assertEqual(len(r['others']), 1)
        self.assertIn('every v4 pool below was made by someone else', ppc.to_markdown(r))

    def test_graduated_but_no_matching_pool_is_said_plainly(self):
        _, r = self.run_main(record(), [init_log('0x' + '1' * 64, ppc.ZERO, TOKEN, 790000, 60, ppc.ZERO)])
        self.assertIsNone(r['official'])
        self.assertIn('No pool matches the factory record', ppc.to_markdown(r))

    def test_not_a_pons_token_exits_3(self):
        code, _ = self.run_main(record(exists=0), [])
        self.assertEqual(code, 3)

    def test_bad_input_exits_3_without_network(self):
        with mock.patch.object(ppc, 'rpc', side_effect=AssertionError('no network')):
            self.assertEqual(ppc.main(['0x1234']), 3)
            self.assertEqual(ppc.main([TOKEN, '--top', '0']), 3)

    def test_rpc_down_and_wrong_chain_exit_2(self):
        with mock.patch.object(ppc, 'rpc', side_effect=ppc.RpcError('HTTP 503')):
            self.assertEqual(ppc.main([TOKEN]), 2)
        with mock.patch.object(ppc, 'rpc', return_value=hex(1)):
            self.assertEqual(ppc.main([TOKEN]), 2)

    def test_markdown_states_facts_only(self):
        _, r = self.run_main(record(), [init_log(OFFICIAL_ID, ppc.ZERO, TOKEN, 0, 200, ppc.MEME_HOOK),
                                        init_log('0x' + '1' * 64, ppc.ZERO, TOKEN, 990000, 60, ppc.ZERO)])
        md = ppc.to_markdown(r).lower()
        self.assertIn('not a price signal or a safety verdict', md)
        for word in ('scam', 'rug', 'honeypot', 'malicious', 'buy now', 'sell now'):
            self.assertNotIn(word, md)


if __name__ == '__main__':
    unittest.main()
