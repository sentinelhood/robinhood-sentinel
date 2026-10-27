"""Offline tests for skills/pons-curve-movers. No network.

Run: python3 tests/test_pons_curve_movers.py
"""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills' / 'pons-curve-movers'))
import pons_curve_movers as pcm  # noqa: E402

CURVE = '0xbe14b44540fb02d432f753e9dda84eea65fae6a2'
TOKEN = '0xf7c031dbe2683119167e5571b827fa7db9b41bbe'
DEP = '0x45cde31e37365c5cd378135e93bea0d0f89cb9d5'
E18 = 10 ** 18
SUPPLY = 10 ** 9 * E18
PHANTOM = 168 * 10 ** 16  # 1.68 ETH


def word(n):
    return format(n, '064x')


def trade_log(buy, data, trader='0x' + 'a' * 40, curve=CURVE, block=100, **over):
    return {'address': curve, 'removed': False, 'blockNumber': hex(block),
            'topics': [pcm.BUY if buy else pcm.SELL, '0x' + '0' * 24 + 'e33e9e479df8802cb0866d5d05258bec4cf62948', '0x' + trader[2:].rjust(64, '0')],
            'data': '0x' + ''.join(word(x) for x in data), **over}


# Real trades on curve 0xbe14…a6e2 (token 0xf7c0…1bbe), blocks 98,319,504-98,343,662, read 2026-10-26.
REAL = [
    (True, [30000000000000000, 17285250504518732999912257, 300000000000000, 150000000000000]),
    (True, [1371000000000000, 774416563255000000000000, 16000000000000, 7000000000000]),
    (False, [17285250504518730000000000, 30991314010394017, 314632629547147, 157316314773573]),
]


def record(curve=CURVE, deployer=DEP, pair=pcm.ZERO, threshold=42 * 10 ** 17, phase=0, exists=1):
    w = ['0' * 64] * 15
    w[1], w[2], w[4] = '0' * 24 + curve[2:], '0' * 24 + deployer[2:], '0' * 24 + pair[2:]
    w[5], w[10], w[14] = word(threshold), word(phase), word(exists)
    return '0x' + ''.join(w)


def reserves(raised):
    """Reserves after `raised` real quote came in, on the 1.68 ETH / 1e9 token constant-product curve."""
    q = PHANTOM + raised
    return '0x' + word(q) + word(PHANTOM * SUPPLY // q)


def abi_string(s):
    b = s.encode()
    return '0x' + word(32) + word(len(b)) + b.hex().ljust(64 * max(1, -(-len(b) // 32)), '0')


class Parse(unittest.TestCase):
    def test_buy_and_sell(self):
        b = pcm.parse_trade(trade_log(*REAL[0]))
        self.assertEqual((b['buy'], b['curve'], b['volume'], b['net']), (True, CURVE, 30000000000000000, 30000000000000000 - 450000000000000))
        s = pcm.parse_trade(trade_log(*REAL[2]))
        self.assertEqual(s['buy'], False)
        self.assertEqual(s['net'], -(30991314010394017 + 314632629547147 + 157316314773573))
        self.assertEqual(s['volume'], -s['net'])

    def test_rejects_malformed_and_removed(self):
        good = trade_log(*REAL[0])
        for bad in ({**good, 'removed': True}, {**good, 'data': '0x1234'}, {**good, 'data': '0x' + word(1) * 3},
                    {**good, 'topics': good['topics'][:2]}, {**good, 'topics': ['0x' + '1' * 64] + good['topics'][1:]},
                    {**good, 'blockNumber': 'zz'}, {}):
            self.assertIsNone(pcm.parse_trade(bad))

    def test_record_address_uint(self):
        r = pcm.decode_record(record(threshold=8090000000, pair='0x5fc5360d0400a0fd4f2af552add042d716f1d168'))
        self.assertEqual((r['curve'], r['threshold'], r['phase']), (CURVE, 8090000000, 0))
        self.assertIsNone(pcm.decode_record(record(exists=0)))
        self.assertIsNone(pcm.decode_record('0x12'))
        self.assertEqual(pcm.address_of('0x' + '0' * 24 + TOKEN[2:]), TOKEN)
        self.assertIsNone(pcm.address_of('0x' + 'f' * 64))
        self.assertIsNone(pcm.address_of(None))
        self.assertEqual(pcm.uint('0x' + word(6)), 6)


class Maths(unittest.TestCase):
    def test_net_matches_real_reserve(self):
        """Buys (quote - fees) minus sells (quote + fees) over the curve's 17 real trades left exactly 94956536187781 wei.
        The 3 trades here are a prefix, so check the same identity on them against the formula."""
        trades = [pcm.parse_trade(trade_log(*t)) for t in REAL]
        expected = (30000000000000000 - 450000000000000) + (1371000000000000 - 23000000000000) - (30991314010394017 + 471948944320720)
        self.assertEqual(sum(t['net'] for t in trades), expected)

    def test_progress(self):
        th = 42 * 10 ** 17
        self.assertEqual(pcm.progress(reserves(0), SUPPLY, th), 0.0)
        self.assertAlmostEqual(pcm.progress(reserves(2679424940719175500), SUPPLY, th), 63.8, places=1)  # CHARLIE, verified two ways
        self.assertEqual(pcm.progress(reserves(th), SUPPLY, th), 100.0)
        self.assertEqual(pcm.progress(reserves(2 * th), SUPPLY, th), 100.0)
        for bad in (('0x', SUPPLY, th), (reserves(1), 0, th), (reserves(1), SUPPLY, 0)):
            self.assertIsNone(pcm.progress(*bad))

    def test_aggregate_and_rank(self):
        other = '0x' + 'c' * 40
        ts = [pcm.parse_trade(trade_log(*REAL[0], trader='0x' + 'a' * 40)), pcm.parse_trade(trade_log(*REAL[1], trader='0x' + 'b' * 40)),
              pcm.parse_trade(trade_log(*REAL[2], trader='0x' + 'a' * 40)),
              pcm.parse_trade(trade_log(*REAL[0], curve=other)), pcm.parse_trade(trade_log(*REAL[0], curve=other, block=200))]
        per = pcm.aggregate(ts)
        a = per[CURVE]
        self.assertEqual((a['buys'], a['sells'], len(a['traders'])), (2, 1, 2))
        self.assertEqual(per[other]['lastBlock'], 200)
        self.assertEqual(pcm.rank(per), [CURVE, other])  # 2 traders beats 1

    def test_rank_one_wallet_dust_does_not_lead(self):
        # Live pattern 2026-10-27: one sender, one 100-wei buy per block, hundreds of times.
        spam, busy = '0x' + 'e' * 40, '0x' + 'f' * 40
        dust = trade_log(*REAL[0], curve=spam, trader='0x' + 'd' * 40)
        ts = [pcm.parse_trade(dust) for _ in range(500)]
        ts += [pcm.parse_trade(trade_log(*REAL[0], curve=busy, trader=f'0x{i:040x}')) for i in range(1, 31)]
        per = pcm.aggregate(ts)
        self.assertEqual(pcm.rank(per), [busy, spam])
        self.assertEqual((per[spam]['buys'], len(per[spam]['traders'])), (500, 1))

    def test_rank_ties_on_traders_break_by_trades(self):
        a, b = '0x' + '1' * 40, '0x' + '2' * 40
        ts = [pcm.parse_trade(trade_log(*REAL[0], curve=a, trader='0x' + 'a' * 40)) for _ in range(2)]
        ts += [pcm.parse_trade(trade_log(*REAL[0], curve=b, trader='0x' + 'a' * 40)) for _ in range(5)]
        self.assertEqual(pcm.rank(pcm.aggregate(ts)), [b, a])

    def test_amount(self):
        self.assertEqual(pcm.amount(26343100000000000000, 18), '26.3431')
        self.assertEqual(pcm.amount(8090000005, 6), '8,090')
        self.assertIsNone(pcm.amount(1, None))


class Markdown(unittest.TestCase):
    def test_facts_only(self):
        movers = [{'token': TOKEN, 'symbol': 'CHARLIE', 'name': 'Charlie', 'buys': 351, 'sells': 6, 'traders': 110,
                   'volume': 706800000000000000, 'net': 679500000000000000, 'pairSymbol': 'ETH', 'pairDecimals': 18, 'phase': 0, 'progress': 63.8},
                  {'token': '0x' + 'd' * 40, 'symbol': 'REACHY', 'name': 'Reachy Mini', 'buys': 543, 'sells': 244, 'traders': 186,
                   'volume': 216 * E18, 'net': -41 * E18, 'pairSymbol': 'NVDA', 'pairDecimals': 18, 'phase': 2,
                   'phaseLabel': pcm.PHASE[2], 'progress': None}]
        md = pcm.to_markdown({'block': 98367569, 'windowHours': 6, 'trades': 9627, 'curves': 540, 'skipped': 1, 'movers': movers})
        self.assertTrue(md.startswith('Pons v2 curve movers · last 6h · block 98,367,569'))
        self.assertIn('1. CHARLIE (Charlie) · 351 buys / 6 sells · 110 traders · 0.7068 ETH traded, net +0.6795 ETH · 63.8% to graduation', md)
        self.assertIn('net -41 NVDA · now: Uniswap v4 pool, liquidity locked', md)
        self.assertIn('1 busy emitter(s) skipped', md)
        for word_ in ('scam', 'rug', 'honeypot', 'buy now', 'moon', 'gem', 'ape'):
            self.assertNotIn(word_, md.lower())
        empty = pcm.to_markdown({'block': 1, 'windowHours': 1, 'trades': 0, 'curves': 0, 'skipped': 0, 'movers': []})
        self.assertIn('No curve trades in the window.', empty)


class Main(unittest.TestCase):
    def test_bad_input_exits_3_without_network(self):
        with mock.patch.object(pcm, 'post', side_effect=AssertionError('no network expected')):
            for args in (['--hours', '0'], ['--hours', '25'], ['--top', '0'], ['--top', '26']):
                self.assertEqual(pcm.main(args), 3)

    def test_rpc_down_and_wrong_chain_exit_2(self):
        with mock.patch.object(pcm, 'post', side_effect=pcm.RpcError('gave up after retries')):
            self.assertEqual(pcm.main([]), 2)
        with mock.patch.object(pcm, 'post', return_value={'result': '0x1'}):
            self.assertEqual(pcm.main([]), 2)

    def test_end_to_end_skips_spoofed_curve(self):
        """A fake chain with one real curve and one busier spoof that emits the same events. Only the real curve is listed."""
        head = 1_000_000
        spoof = '0x' + '5' * 40
        raised = 2679424940719175500

        def fake_post(body):
            if isinstance(body, list):
                out = []
                for b in body:
                    to, data = b['params'][0]['to'], b['params'][0]['data']
                    if data == pcm.TOKEN:
                        res = '0x' + '0' * 24 + TOKEN[2:]  # the spoof claims the real token too
                    elif to == pcm.FACTORY:
                        res = record()
                    elif data == pcm.RESERVES:
                        res = reserves(raised)
                    elif data == pcm.SUPPLY:
                        res = '0x' + word(SUPPLY)
                    else:
                        res = abi_string('CHARLIE') if data == pcm.SYMBOL else abi_string('Charlie')
                    out.append({'id': b['id'], 'result': res})
                return out
            m = body['method']
            if m == 'eth_chainId':
                return {'result': hex(4663)}
            if m == 'eth_blockNumber':
                return {'result': hex(head)}
            if m == 'eth_getLogs':
                f = body['params'][0]
                lo, hi = int(f['fromBlock'], 16), int(f['toBlock'], 16)
                self.assertLessEqual(hi - lo + 1, pcm.LOG_STEP)
                self.assertNotIn('address', f)
                if not lo <= head - 5 <= hi:
                    return {'result': []}
                if f['topics'] == [pcm.BUY]:
                    return {'result': [trade_log(*REAL[0], block=head - 5), trade_log(*REAL[1], block=head - 5)] +
                            [trade_log(*REAL[0], curve=spoof, block=head - 5, trader='0x' + format(i, '040x')) for i in range(5)]}
                return {'result': [trade_log(*REAL[2], block=head - 5)]}
            raise AssertionError(m)

        out = []
        with mock.patch.object(pcm, 'post', side_effect=fake_post), mock.patch('builtins.print', side_effect=lambda s, **k: out.append(s)):
            self.assertEqual(pcm.main(['--hours', '1', '--json']), 0)
        r = json.loads(out[0])
        self.assertEqual((r['trades'], r['curves'], r['skipped']), (8, 2, 1))
        self.assertEqual([m['curve'] for m in r['movers']], [CURVE])
        m = r['movers'][0]
        self.assertEqual((m['symbol'], m['buys'], m['sells'], m['traders'], m['pairSymbol']), ('CHARLIE', 2, 1, 1, 'ETH'))
        self.assertAlmostEqual(m['progress'], 63.8, places=1)


if __name__ == '__main__':
    unittest.main()
