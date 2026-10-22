"""Offline tests for skills/pons-launch-watch. No network: RPC calls are never made.

Run: python3 tests/test_pons_launch_watch.py
"""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills' / 'pons-launch-watch'))
import pons_launch_watch as plw  # noqa: E402

# Real TokenLaunched log from the Pons v2 factory on chain 4663.
LOG = {
    'address': '0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e', 'removed': False, 'blockNumber': '0x59edb3b',
    'topics': [plw.TOKEN_LAUNCHED,
               '0x00000000000000000000000057c140bfe79001d29c3d1108f461bd977198480f',
               '0x0000000000000000000000000092be1e96edd3d895571f671c367f7121e70057',
               '0x00000000000000000000000045cde31e37365c5cd378135e93bea0d0f89cb9d5'],
}
OFFICIAL = '0x2da80b9d1bc1b323693c80c76eb4a321ec08cbd0'


def abi_string(s):
    b = s.encode()
    return '0x' + (32).to_bytes(32, 'big').hex() + len(b).to_bytes(32, 'big').hex() + b.ljust(max(32, -(-len(b) // 32) * 32), b'\0').hex()


def launch(token, symbol, name='', deployer='0x' + 'd' * 40, block=1):
    return {'token': token, 'symbol': symbol, 'name': name, 'deployer': deployer, 'block': block}


class ParseLaunch(unittest.TestCase):
    def test_real_log(self):
        self.assertEqual(plw.parse_launch(LOG), {'token': '0x57c140bfe79001d29c3d1108f461bd977198480f',
                                                 'deployer': '0x45cde31e37365c5cd378135e93bea0d0f89cb9d5', 'block': 94296891})

    def test_rejects_spoofed_and_malformed(self):
        for patch in ({'address': '0x' + '1' * 40}, {'removed': True}, {'topics': LOG['topics'][:3]},
                      {'topics': ['0x' + 'a' * 64] + LOG['topics'][1:]}, {'blockNumber': 'zz'}):
            self.assertIsNone(plw.parse_launch({**LOG, **patch}), patch)


class Strings(unittest.TestCase):
    def test_abi_bytes32_and_junk(self):
        self.assertEqual(plw.decode_string(abi_string('Sentinel')), 'Sentinel')
        self.assertEqual(plw.decode_string('0x' + b'MKR'.ljust(32, b'\0').hex()), 'MKR')
        self.assertEqual(plw.decode_string(abi_string('a\x00b\x1b[31mc')), 'ab[31mc')
        self.assertEqual(len(plw.decode_string(abi_string('x' * 200))), 64)
        for bad in (None, '', '0x', '0xzz', '0x1234'):
            self.assertEqual(plw.decode_string(bad), '')

    def test_normalise_catches_disguises(self):
        for s in ('SNTL', 'sntl', '$SNTL', 'S.N.T.L', ' Sntl ', 'ＳＮＴＬ'):  # last one is full-width
            self.assertEqual(plw.normalise(s), 'sntl', s)
        self.assertNotEqual(plw.normalise('SNTL2'), 'sntl')


class Lookalikes(unittest.TestCase):
    def test_matches_symbol_or_name_and_skips_official(self):
        ls = [launch(OFFICIAL, 'SNTL', 'Sentinel'), launch('0x' + 'a' * 40, '$sntl'), launch('0x' + 'b' * 40, 'SENT', 'Sentinel'),
              launch('0x' + 'c' * 40, 'SNTLX', 'Sentinel X'), launch('0x' + 'e' * 40, 'PEPE')]
        hits = plw.find_lookalikes(ls, ['SNTL', 'Sentinel'], {OFFICIAL})
        self.assertEqual([(h['token'][:4], h['field'], h['matched']) for h in hits],
                         [('0xaa', 'symbol', 'SNTL'), ('0xbb', 'name', 'Sentinel')])

    def test_empty_watch_matches_nothing(self):
        self.assertEqual(plw.find_lookalikes([launch('0x' + 'a' * 40, 'SNTL')], [], set()), [])
        self.assertEqual(plw.find_lookalikes([launch('0x' + 'a' * 40, '')], ['$'], set()), [])


class Report(unittest.TestCase):
    def test_counts_and_markdown(self):
        ls = [launch('0x%040x' % i, s, deployer='0x' + ('9' if i < 12 else '8') * 40) for i, s in enumerate(['RUSH'] * 3 + ['rush'] + ['A', 'B'] + list('CDEFGHIJ'))]
        r = plw.build_report(ls, [], head=100, hours=24)
        self.assertEqual(r['launches'], 14)
        self.assertEqual(r['sharedTickerLaunches'], 4)  # RUSH x3 + rush, case-insensitive
        self.assertEqual(r['topRepeated'], [{'symbol': 'RUSH', 'launches': 4}])
        self.assertEqual(r['serialDeployers'], [{'deployer': '0x' + '9' * 40, 'launches': 12}])
        md = plw.to_markdown(r)
        self.assertNotIn('LOOKALIKE', md)
        self.assertIn('4 (29%) share a ticker', md)

    def test_lookalikes_capped_newest_first(self):
        hits = [{**launch('0x%040x' % i, 'SNTL', block=i), 'matched': 'SNTL', 'field': 'symbol'} for i in range(14)]
        md = plw.to_markdown(plw.build_report([], hits, head=100, hours=24))
        bullets = [l for l in md.splitlines() if l.startswith('• SNTL')]
        self.assertEqual(len(bullets), plw.MAX_LISTED)
        self.assertIn('0x' + '0' * 39 + 'd', bullets[0])  # block 13, newest, first
        self.assertIn('+4 more', md)


class Main(unittest.TestCase):
    """End to end with the RPC stubbed: cold run, incremental run, no repeated alerts, failure path."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.state = Path(self.dir.name) / 'state.json'
        self.head = 1_000_000

    def tearDown(self):
        self.dir.cleanup()

    def fake(self, launches):
        def rpc(method, params):
            if method == 'eth_chainId':
                return hex(plw.CHAIN_ID)
            if method == 'eth_blockNumber':
                return hex(self.head)
            lo, hi = int(params[0]['fromBlock'], 16), int(params[0]['toBlock'], 16)
            return [{**LOG, 'blockNumber': hex(b), 'topics': [plw.TOKEN_LAUNCHED, '0x' + '0' * 24 + t[2:], LOG['topics'][2], LOG['topics'][3]]}
                    for t, b, _ in launches if lo <= b <= hi]

        def post(body):
            names = {t: s for t, _, s in launches}
            return [{'id': c['id'], 'result': abi_string(names[c['params'][0]['to']])} for c in body]
        return rpc, post

    def run_main(self, launches, watch='SNTL'):
        rpc, post = self.fake(launches)
        out = []
        with mock.patch.object(plw, 'rpc', rpc), mock.patch.object(plw, 'post', post), mock.patch.object(plw.time, 'sleep'), \
             mock.patch('builtins.print', lambda *a, **k: out.append(a[0]) if not k.get('file') else None):
            code = plw.main(['--watch', watch, '--official', OFFICIAL, '--state', str(self.state), '--hours', '1', '--json'])
        return code, json.loads(out[0]) if out else None

    def test_cold_then_incremental(self):
        fake = '0x' + 'f' * 40
        base = [(OFFICIAL, self.head - 100, 'SNTL'), (fake, self.head - 50, 'SNTL'), ('0x' + 'a' * 40, self.head - 10, 'PEPE')]
        code, r = self.run_main(base)
        self.assertEqual(code, 0)
        self.assertEqual(r['launches'], 3)
        self.assertEqual([h['token'] for h in r['lookalikes']], [fake])
        st = json.loads(self.state.read_text())
        self.assertEqual(st['lastBlock'], self.head)
        self.assertEqual(st['reported'], [fake])
        self.assertTrue(all(isinstance(row, list) for row in st['seen']))

        self.head += 100
        late = '0x' + 'e' * 40
        code, r = self.run_main(base + [(late, self.head - 5, 'sntl')])
        self.assertEqual(r['launches'], 4)
        self.assertEqual([h['token'] for h in r['lookalikes']], [late])  # the first fake is not reported again

    def test_new_watch_term_catches_cached_launch(self):
        base = [('0x' + 'a' * 40, self.head - 10, 'PEPE')]
        self.run_main(base, watch='SNTL')
        self.head += 1
        _, r = self.run_main(base, watch='SNTL,PEPE')
        self.assertEqual([h['token'] for h in r['lookalikes']], ['0x' + 'a' * 40])

    def test_wrong_chain_and_rpc_down_exit_2_without_touching_state(self):
        self.state.write_text('{"lastBlock": 5}')
        with mock.patch.object(plw, 'rpc', lambda m, p: '0x1'):
            self.assertEqual(plw.main(['--state', str(self.state)]), 2)
        def down(m, p):
            raise plw.RpcError('HTTP 503')
        with mock.patch.object(plw, 'rpc', down):
            self.assertEqual(plw.main(['--state', str(self.state)]), 2)
        self.assertEqual(self.state.read_text(), '{"lastBlock": 5}')

    def test_bad_official_address(self):
        self.assertEqual(plw.main(['--official', '0x123', '--state', str(self.state)]), 2)


if __name__ == '__main__':
    unittest.main(verbosity=1)
