"""Offline tests for skills/pons-graduation-watch. No network.

Run: python3 tests/test_pons_graduation_watch.py
"""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills' / 'pons-graduation-watch'))
import pons_graduation_watch as pgw  # noqa: E402

TOKEN = '0xa3b6b325f7937f97b3df9f7ee654d7463c2382da'
DEP = '0x45cde31e37365c5cd378135e93bea0d0f89cb9d5'
USDG = '0x5fc5360d0400a0fd4f2af552add042d716f1d168'
# Graduation log data at block 95,625,802 (tx 0x8033…69bb): 4.2 ETH + 185 wei, 285,714,285.714… tokens.
GRAD_DATA = '0x' + format(4200000000000000185, '064x') + format(0xec565a76cddb7f1db6db6d, '064x')


def grad_log(token=TOKEN, block=95_625_802, **over):
    return {'address': pgw.FACTORY, 'removed': False, 'blockNumber': hex(block), 'transactionHash': '0x' + '8' * 64,
            'topics': [pgw.GRADUATED, '0x' + token[2:].rjust(64, '0')], 'data': GRAD_DATA, **over}


def launch_log(token):
    return {'address': pgw.FACTORY, 'removed': False, 'blockNumber': '0x1',
            'topics': [pgw.TOKEN_LAUNCHED, '0x' + token[2:].rjust(64, '0'), '0x' + '1' * 64, '0x' + DEP[2:].rjust(64, '0')]}


def record(deployer=DEP, pair=pgw.ZERO, phase=2, exists=1):
    w = ['0' * 64] * 15
    w[2] = '0' * 24 + deployer[2:]
    w[4] = '0' * 24 + pair[2:]
    w[10] = format(phase, '064x')
    w[14] = format(exists, '064x')
    return '0x' + ''.join(w)


def abi_string(s):
    b = s.encode()
    return '0x' + format(32, '064x') + format(len(b), '064x') + b.hex().ljust(64 * max(1, -(-len(b) // 32)), '0')


class Parse(unittest.TestCase):
    def test_graduation_log(self):
        g = pgw.parse_graduation(grad_log())
        self.assertEqual((g['token'], g['block'], g['quoteRaw']), (TOKEN, 95_625_802, 4200000000000000185))
        self.assertEqual(g['tokensRaw'] // 10 ** 18, 285_714_285)

    def test_spoofed_removed_malformed(self):
        for bad in (grad_log(address='0x' + '2' * 40), grad_log(removed=True), grad_log(data='0x1234'),
                    grad_log(data='0x' + '0' * 64), {**grad_log(), 'topics': [pgw.GRADUATED]},
                    {**grad_log(), 'topics': [pgw.TOKEN_LAUNCHED, '0x' + '1' * 64]}, {**grad_log(), 'blockNumber': 'zz'}, {}):
            self.assertIsNone(pgw.parse_graduation(bad))

    def test_count_launches_dedupes_and_ignores_spoofs(self):
        a, b = '0x' + 'a' * 40, '0x' + 'b' * 40
        logs = [launch_log(a), launch_log(a), launch_log(b), {**launch_log(b), 'address': '0x' + '3' * 40},
                {**launch_log('0x' + 'c' * 40), 'removed': True}]
        self.assertEqual(pgw.count_launches(logs), 2)

    def test_record(self):
        self.assertEqual(pgw.decode_record(record(pair=USDG, phase=2)), {'deployer': DEP, 'pairToken': USDG, 'phase': 2})
        self.assertIsNone(pgw.decode_record(record(exists=0)))
        for bad in (None, '0x', '0x12', record()[:-64]):
            self.assertIsNone(pgw.decode_record(bad))

    def test_strings_and_decimals(self):
        self.assertEqual(pgw.decode_string(abi_string('NUTZ')), 'NUTZ')
        self.assertEqual(pgw.decode_string(abi_string('a\u0007b')), 'ab')
        self.assertIsNone(pgw.decode_string('0x'))
        self.assertEqual(pgw.decode_uint8('0x' + format(6, '064x')), 6)
        self.assertIsNone(pgw.decode_uint8('0x' + format(255, '064x')))
        self.assertIsNone(pgw.decode_uint8(None))

    def test_amounts(self):
        self.assertEqual(pgw.amount(4200000000000000185, 18), '4.2')
        self.assertEqual(pgw.amount(8090000005, 6), '8,090')
        self.assertEqual(pgw.amount(917162201643832986618, 18), '917.1622')
        self.assertIsNone(pgw.amount(1, None))


class Select(unittest.TestCase):
    def grads(self):
        a, b, c = ('0x' + ch * 40 for ch in 'abc')
        return [{'token': a, 'block': 100, 'deployer': DEP}, {'token': b, 'block': 200, 'deployer': DEP},
                {'token': c, 'block': 300, 'deployer': '0x' + '9' * 40}]

    def test_all_when_no_watch(self):
        self.assertEqual([g['token'][2] for g in pgw.select_new(self.grads(), [], 0, set())], ['a', 'b', 'c'])

    def test_after_block_and_unreported(self):
        self.assertEqual([g['token'][2] for g in pgw.select_new(self.grads(), [], 150, {'0x' + 'c' * 40})], ['b'])

    def test_watch_by_token_or_deployer(self):
        self.assertEqual([g['token'][2] for g in pgw.select_new(self.grads(), [DEP], 0, set())], ['a', 'b'])
        self.assertEqual([g['token'][2] for g in pgw.select_new(self.grads(), ['0x' + 'c' * 40], 0, set())], ['c'])

    def test_report_and_markdown(self):
        new = [{'token': TOKEN, 'block': 990, 'deployer': DEP, 'quoteRaw': 8090000005, 'pairSymbol': 'USDG',
                'pairDecimals': 6, 'symbol': 'GF', 'name': 'Good Fellow', 'phaseLabel': pgw.PHASE[2]}]
        r = pgw.build_report(new, new, 200, [], 1000, 24)
        self.assertEqual(r['rate'], 0.5)
        md = pgw.to_markdown(r)
        self.assertTrue(md.startswith('NEW PONS GRADUATIONS · 1'))
        self.assertIn('GF (Good Fellow) · 8,090 USDG into the pool', md)
        self.assertIn('now: Uniswap v4 pool, liquidity locked', md)
        self.assertIn('1 graduated · 200 launched (0.5% of launches)', md)
        for word in ('scam', 'rug', 'honeypot', 'buy now', 'moon', 'sell'):
            self.assertNotIn(word, md.lower())
        quiet = pgw.to_markdown(pgw.build_report([], [], 0, [], 1000, 24))
        self.assertTrue(quiet.startswith('Pons v2 graduations'))
        self.assertIn('0 graduated · 0 launched', quiet)


class Main(unittest.TestCase):
    def test_bad_watch_exits_3_without_network(self):
        with mock.patch.object(pgw, 'post', side_effect=AssertionError('no network expected')):
            self.assertEqual(pgw.main(['--watch', 'NUTZ', '--state', '/nonexistent/x.json']), 3)

    def test_rpc_down_exits_2_and_keeps_state(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 's.json'
            p.write_text('{"lastBlock": 7}')
            with mock.patch.object(pgw, 'post', side_effect=pgw.RpcError('gave up after retries')):
                self.assertEqual(pgw.main(['--state', str(p)]), 2)
            self.assertEqual(json.loads(p.read_text()), {'lastBlock': 7})

    def test_wrong_chain_exits_2(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(pgw, 'post', return_value={'result': '0x1'}):
            self.assertEqual(pgw.main(['--state', str(Path(d) / 's.json')]), 2)

    def test_reports_once_then_quiet(self):
        """Two runs against a fake chain: the first reports the graduation with USDG pricing, the second does not."""
        head = 1_000_000

        def fake_post(body):
            if isinstance(body, list):
                out = []
                for b in body:
                    to, data = b['params'][0]['to'], b['params'][0]['data']
                    if to == pgw.FACTORY:
                        res = record(pair=USDG)
                    elif to == USDG:
                        res = abi_string('USDG') if data == pgw.SYMBOL else '0x' + format(6, '064x')
                    else:
                        res = abi_string('GF') if data == pgw.SYMBOL else abi_string('Good Fellow')
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
                if not lo <= head - 10 <= hi:
                    return {'result': []}
                if f['topics'] == [pgw.GRADUATED]:
                    return {'result': [{**grad_log(block=head - 10), 'data': '0x' + format(8090000005, '064x') + format(1, '064x')}]}
                return {'result': [launch_log('0x' + 'e' * 40), launch_log(TOKEN)]}
            raise AssertionError(m)

        with tempfile.TemporaryDirectory() as d, mock.patch.object(pgw, 'post', side_effect=fake_post):
            state = str(Path(d) / 's.json')
            out = []
            with mock.patch('builtins.print', side_effect=lambda s, **k: out.append(s)):
                self.assertEqual(pgw.main(['--state', state, '--hours', '1']), 0)
                self.assertEqual(pgw.main(['--state', state, '--hours', '1']), 0)
            self.assertTrue(out[0].startswith('NEW PONS GRADUATIONS · 1'), out[0])
            self.assertIn('GF (Good Fellow) · 8,090 USDG into the pool', out[0])
            self.assertIn('1 graduated · 2 launched (50% of launches)', out[0])
            self.assertTrue(out[1].startswith('Pons v2 graduations'), out[1])
            self.assertEqual(json.loads(Path(state).read_text())['reported'], [TOKEN])


if __name__ == '__main__':
    unittest.main()
