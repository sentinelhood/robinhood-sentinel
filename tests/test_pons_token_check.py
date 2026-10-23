"""Offline tests for skills/pons-token-check. No network: fixtures are real factory records
captured from the Pons v2 factory on chain 4663.

Run: python3 tests/test_pons_token_check.py
"""
import json, sys, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills' / 'pons-token-check'))
import pons_token_check as ptc  # noqa: E402

SNTL = '0x2da80b9d1bc1b323693c80c76eb4a321ec08cbd0'
DEP = '0x53cccdeba2714074d0702d2b6459cbcb19c61784'
# getLaunchedToken(SNTL), read verbatim from the Pons v2 factory on 2026-10-23.
SNTL_REC = '0x' + ''.join([
    '0' * 24 + SNTL[2:],                                   # token
    '0' * 24 + '369907394da08b8b07c9e2db623899c2d79a4b2a',  # curve
    '0' * 24 + DEP[2:],                                    # deployer
    '0' * 24 + DEP[2:],                                    # creator fee recipient
    '0' * 64,                                              # pair token = native ETH
    format(4200000000000000000, '064x'),                   # graduation threshold, 4.2 ETH
    '0' * 64,                                              # pool fee
    format(200, '064x'),                                   # tick spacing
    format(300, '064x'),                                   # creator tax, 300 bps
    '0' * 64,                                              # buyback off
    format(2, '064x'),                                     # phase 2
    '0' * 64 * 3,
    format(1, '064x'),                                     # exists
])


def abi_string(s):
    b = s.encode()
    return '0x' + (32).to_bytes(32, 'big').hex() + len(b).to_bytes(32, 'big').hex() + b.ljust(max(32, -(-len(b) // 32) * 32), b'\0').hex()


def launch_log(token, deployer, block):
    return {'address': ptc.FACTORY, 'removed': False, 'blockNumber': hex(block),
            'topics': [ptc.TOKEN_LAUNCHED, '0x' + token[2:].rjust(64, '0'), '0x' + '1' * 64, '0x' + deployer[2:].rjust(64, '0')]}


class Decode(unittest.TestCase):
    def test_real_sntl_record(self):
        rec = ptc.decode_launch(SNTL_REC)
        self.assertEqual(rec['token'], SNTL)
        self.assertEqual(rec['deployer'], DEP)
        self.assertEqual((rec['phase'], rec['creatorTaxBps'], rec['buyback']), (2, 300, False))

    def test_unknown_token_and_malformed(self):
        self.assertIsNone(ptc.decode_launch('0x' + '0' * 64 * 15))
        for bad in ('0x', '0x1234', '0x' + '0' * 64 * 14, None, 'zz'):
            with self.assertRaises(ValueError):
                ptc.decode_launch(bad)

    def test_strings(self):
        self.assertEqual(ptc.decode_string(abi_string('Sentinel')), 'Sentinel')
        self.assertEqual(ptc.decode_string('0x' + b'SNTL'.hex().ljust(64, '0')), 'SNTL')   # bytes32
        self.assertEqual(ptc.decode_string(abi_string('a\x00\x07b' + 'x' * 100)), 'ab' + 'x' * 62)
        self.assertIsNone(ptc.decode_string('0x'))
        self.assertIsNone(ptc.decode_string(None))

    def test_account_kind(self):
        self.assertEqual(ptc.account_kind('0x'), 'wallet')
        self.assertEqual(ptc.account_kind('0xef0100' + 'ab' * 20), 'wallet, EIP-7702 delegated')
        self.assertEqual(ptc.account_kind('0x6080604052'), 'contract')


class History(unittest.TestCase):
    def test_counts_own_launches_deduped_in_order(self):
        a, b, c = ('0x' + ch * 40 for ch in 'abc')
        other = '0x' + '9' * 40
        logs = [launch_log(b, DEP, 200), launch_log(a, DEP, 100), launch_log(c, DEP, 300), launch_log(b, DEP, 200),
                launch_log('0x' + 'd' * 40, other, 150),
                {**launch_log('0x' + 'e' * 40, DEP, 50), 'removed': True},
                {**launch_log('0x' + 'f' * 40, DEP, 60), 'address': '0x' + '2' * 40}]
        h = ptc.history(logs, DEP, b)
        self.assertEqual(h, {'launches': 3, 'firstBlock': 100, 'number': 2})
        self.assertIsNone(ptc.history(logs, DEP, '0x' + '7' * 40)['number'])


def report(**pons):
    base = {'deployer': DEP, 'feeRecipient': DEP, 'pairToken': ptc.ZERO, 'creatorTaxBps': 0, 'buyback': False, 'phase': 2,
            'baseFeeBps': 100, 'pairSymbol': None, 'deployerKind': 'wallet',
            'holdings': {'deployer': {'address': DEP, 'percent': 0.0}}, 'deployerHistory': {'launches': 1, 'firstBlock': 1, 'number': 1}}
    return {'chainId': 4663, 'block': 1, 'token': SNTL, 'erc20': True, 'name': 'Sentinel', 'symbol': 'SNTL', 'decimals': 18,
            'totalSupply': '1,000,000,000', 'pons': {**base, **pons}}


class Facts(unittest.TestCase):
    def test_quiet_token_has_no_facts(self):
        self.assertEqual(ptc.facts(report()), [])

    def test_each_fact(self):
        f = ptc.facts(report(creatorTaxBps=300, phase=0, holdings={'deployer': {'address': DEP, 'percent': 12.5}},
                             deployerHistory={'launches': 297, 'firstBlock': 1, 'number': 289}))
        self.assertEqual(len(f), 4)
        self.assertIn('Creator tax 3% on every trade, on top of the 1% base fee.', f)
        self.assertIn('Still on the bonding curve: no Uniswap v4 pool yet.', f)
        self.assertIn('Deployer holds 12.5% of supply.', f)
        self.assertIn('Deployer has launched 297 Pons tokens (this is #289).', f)

    def test_no_pons_and_not_erc20(self):
        self.assertIn('No Pons v2 launch record', ptc.facts({**report(), 'pons': None})[0])
        self.assertIn('Not an ERC-20', ptc.facts({**report(), 'erc20': False})[0])

    def test_never_judges(self):
        text = ptc.to_markdown({**report(creatorTaxBps=300, phase=0), 'facts': ptc.facts(report(creatorTaxBps=300, phase=0))}).lower()
        for word in ('scam', 'rug', 'honeypot', 'safe to', 'buy now', 'sell now'):
            self.assertNotIn(word, text)
        self.assertIn('not an audit', text)


class Main(unittest.TestCase):
    def test_bad_target_exits_3_without_network(self):
        with mock.patch.object(ptc, 'post', side_effect=AssertionError('no network expected')):
            for bad in ('', '0x123', 'SNTL', '0x' + 'g' * 40):
                self.assertEqual(ptc.main([bad]), 3)

    def test_rpc_down_exits_2(self):
        with mock.patch.object(ptc, 'post', side_effect=ptc.RpcError('gave up after retries')):
            self.assertEqual(ptc.main([SNTL]), 2)

    def test_wrong_chain_exits_2(self):
        with mock.patch.object(ptc, 'post', return_value={'jsonrpc': '2.0', 'id': 1, 'result': '0x1'}):
            self.assertEqual(ptc.main([SNTL]), 2)


if __name__ == '__main__':
    unittest.main()
