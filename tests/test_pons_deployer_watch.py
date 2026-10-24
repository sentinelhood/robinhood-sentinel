"""Offline tests for skills/pons-deployer-watch. No network.

Run: python3 tests/test_pons_deployer_watch.py
"""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills' / 'pons-deployer-watch'))
import pons_deployer_watch as pdw  # noqa: E402

DEP = '0x45cde31e37365c5cd378135e93bea0d0f89cb9d5'
OTHER = '0x' + '9' * 40
TOKEN = '0x57c140bfe79001d29c3d1108f461bd977198480f'
# getLaunchedToken(SNTL) read from the Pons v2 factory on 2026-10-23: deployer 0x53cc…1784.
SNTL_REC = '0x' + ''.join([
    '0' * 24 + '2da80b9d1bc1b323693c80c76eb4a321ec08cbd0', '0' * 24 + '369907394da08b8b07c9e2db623899c2d79a4b2a',
    '0' * 24 + '53cccdeba2714074d0702d2b6459cbcb19c61784', '0' * 24 + '53cccdeba2714074d0702d2b6459cbcb19c61784',
    '0' * 64, format(4200000000000000000, '064x'), '0' * 64, format(200, '064x'), format(300, '064x'),
    '0' * 64, format(2, '064x'), '0' * 64 * 3, format(1, '064x')])


def log(token, deployer, block, **over):
    return {'address': pdw.FACTORY, 'removed': False, 'blockNumber': hex(block), 'transactionHash': '0x' + 'a' * 64,
            'topics': [pdw.TOKEN_LAUNCHED, '0x' + token[2:].rjust(64, '0'), '0x' + '1' * 64, '0x' + deployer[2:].rjust(64, '0')], **over}


def launch(token, deployer, block):
    return {'token': token, 'deployer': deployer, 'block': block, 'tx': '0x' + 'a' * 64}


class Parse(unittest.TestCase):
    def test_launch_log(self):
        self.assertEqual(pdw.parse_launch(log(TOKEN, DEP, 100)), launch(TOKEN, DEP, 100))

    def test_spoofed_removed_malformed(self):
        for bad in (log(TOKEN, DEP, 1, address='0x' + '2' * 40), log(TOKEN, DEP, 1, removed=True),
                    {**log(TOKEN, DEP, 1), 'topics': [pdw.TOKEN_LAUNCHED]}, {**log(TOKEN, DEP, 1), 'blockNumber': 'zz'}, {}):
            self.assertIsNone(pdw.parse_launch(bad))

    def test_watch_list(self):
        self.assertEqual(pdw.parse_watch(f' {DEP.upper().replace("0X", "0x")}, {TOKEN} ,,{DEP}'), ([DEP, TOKEN], []))
        self.assertEqual(pdw.parse_watch('SNTL, 0x123')[1], ['SNTL', '0x123'])
        self.assertEqual(pdw.parse_watch(''), ([], []))

    def test_deployer_of_record(self):
        self.assertEqual(pdw.deployer_of(SNTL_REC), '0x53cccdeba2714074d0702d2b6459cbcb19c61784')
        self.assertIsNone(pdw.deployer_of('0x' + '0' * 64 * 15))   # unknown token: exists = false
        for bad in (None, '0x', '0x1234', SNTL_REC[:-64]):
            self.assertIsNone(pdw.deployer_of(bad))


class Select(unittest.TestCase):
    def test_only_watched_new_unreported(self):
        a, b, c, d = ('0x' + ch * 40 for ch in 'abcd')
        ls = [launch(a, DEP, 100), launch(b, DEP, 200), launch(c, OTHER, 300), launch(d, DEP, 300)]
        self.assertEqual([l['token'] for l in pdw.select_new(ls, {DEP}, 150, {d})], [b])
        self.assertEqual([l['token'] for l in pdw.select_new(ls, {DEP}, 0, set())], [a, b, d])
        self.assertEqual(pdw.select_new(ls, set(), 0, set()), [])

    def test_report_and_markdown(self):
        ls = [launch('0x' + 'a' * 40, DEP, 1), launch('0x' + 'b' * 40, DEP, 2), launch('0x' + 'c' * 40, OTHER, 3)]
        new = [{**ls[1], 'name': 'Agile One', 'symbol': 'AGILE'}]
        r = pdw.build_report(ls, new, [DEP], {DEP: TOKEN}, 500, 24)
        self.assertEqual((r['launches'], r['deployers']), (3, 2))
        self.assertEqual(r['watched'], [{'deployer': DEP, 'via': TOKEN, 'launchesInWindow': 2}])
        self.assertEqual(r['busiest'][0], {'deployer': DEP, 'launches': 2})
        md = pdw.to_markdown(r)
        self.assertTrue(md.startswith('NEW LAUNCHES BY WATCHED DEPLOYERS · 1'))
        self.assertIn('AGILE (Agile One)', md)
        self.assertIn('via token 0x57c1…480f', md)
        for word in ('scam', 'rug', 'honeypot', 'buy now', 'sell'):
            self.assertNotIn(word, md.lower())
        quiet = pdw.to_markdown(pdw.build_report(ls, [], [], {}, 500, 24))
        self.assertTrue(quiet.startswith('Pons v2 deployers'))


class Main(unittest.TestCase):
    def test_bad_watch_exits_3_without_network(self):
        with mock.patch.object(pdw, 'post', side_effect=AssertionError('no network expected')):
            self.assertEqual(pdw.main(['--watch', 'SNTL', '--state', '/nonexistent/x.json']), 3)

    def test_rpc_down_exits_2_and_keeps_state(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 's.json'
            p.write_text('{"lastBlock": 7}')
            with mock.patch.object(pdw, 'post', side_effect=pdw.RpcError('gave up after retries')):
                self.assertEqual(pdw.main(['--watch', DEP, '--state', str(p)]), 2)
            self.assertEqual(json.loads(p.read_text()), {'lastBlock': 7})

    def test_reports_once_then_quiet(self):
        """Two runs against a fake chain: the first reports the watched launch, the second does not."""
        head = 1_000_000
        tok = '0x' + 'e' * 40

        def fake_post(body):
            if isinstance(body, list):  # eth_call batches: watch resolution, then name/symbol
                return [{'id': b['id'], 'result': '0x' + '0' * 64 * 15 if b['params'][0]['to'] == pdw.FACTORY else
                         '0x' + (32).to_bytes(32, 'big').hex() + (4).to_bytes(32, 'big').hex() + b'TEST'.hex().ljust(64, '0')}
                        for b in body]
            m = body['method']
            if m == 'eth_chainId':
                return {'result': hex(4663)}
            if m == 'eth_blockNumber':
                return {'result': hex(head)}
            if m == 'eth_getLogs':
                lo, hi = int(body['params'][0]['fromBlock'], 16), int(body['params'][0]['toBlock'], 16)
                return {'result': [log(tok, DEP, head - 10)] if lo <= head - 10 <= hi else []}
            raise AssertionError(m)

        with tempfile.TemporaryDirectory() as d, mock.patch.object(pdw, 'post', side_effect=fake_post):
            state = str(Path(d) / 's.json')
            out = []
            with mock.patch('builtins.print', side_effect=lambda s, **k: out.append(s)):
                self.assertEqual(pdw.main(['--watch', DEP, '--state', state, '--hours', '1']), 0)
                self.assertEqual(pdw.main(['--watch', DEP, '--state', state, '--hours', '1']), 0)
            self.assertTrue(out[0].startswith('NEW LAUNCHES BY WATCHED DEPLOYERS · 1'))
            self.assertIn('TEST', out[0])
            self.assertTrue(out[1].startswith('Pons v2 deployers'))


if __name__ == '__main__':
    unittest.main()
