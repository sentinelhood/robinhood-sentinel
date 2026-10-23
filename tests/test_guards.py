"""Offline tests for scripts/snapshot-guards.py. No network.

Run: python3 tests/test_guards.py
"""
import importlib.util, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('guards', Path(__file__).resolve().parents[1] / 'scripts' / 'snapshot-guards.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

TOKEN = '0x57c140bfe79001d29c3d1108f461bd977198480f'
DEP = '0x45cde31e37365c5cd378135e93bea0d0f89cb9d5'
M = 10 ** 24  # 1,000,000 SNTL
DAY = 86400


def data(amount, token=TOKEN):
    return g.BURN_SEL + hex(amount)[2:].rjust(64, '0') + token[2:].rjust(64, '0')


def burn(amount=M, sender=DEP, token=TOKEN, ts=1_000_000, block=1, tx='0x01'):
    return {'tx': tx, 'from': sender, 'token': token, 'amount': amount, 'ts': ts, 'block': block}


class ParseCall(unittest.TestCase):
    def test_burn_with_token(self):
        self.assertEqual(g.parse_guard_call({'to': g.SNTL, 'input': data(M)}), (M, TOKEN))

    def test_rejects_plain_burn_other_contract_and_garbage(self):
        plain = g.BURN_SEL + hex(M)[2:].rjust(64, '0')
        for tx in [{'to': g.SNTL, 'input': plain},
                   {'to': '0x' + '1' * 40, 'input': data(M)},
                   {'to': g.SNTL, 'input': data(M) + '00'},
                   {'to': g.SNTL, 'input': '0xa9059cbb' + data(M)[10:]},
                   {'to': g.SNTL, 'input': data(M)[:74] + 'f' * 64},          # not an address word
                   {'to': g.SNTL, 'input': data(M, '0x' + '0' * 40)},         # zero address
                   {'to': None, 'input': data(M)}]:
            self.assertIsNone(g.parse_guard_call(tx))


class Decide(unittest.TestCase):
    def test_one_burn_gives_thirty_days(self):
        guards, rejected = g.decide([burn()], {TOKEN: DEP}, now=1_000_000 + DAY)
        self.assertEqual(rejected, [])
        self.assertEqual(len(guards), 1)
        self.assertTrue(guards[0]['active'])
        self.assertEqual(guards[0]['expiresAt'], g.iso(1_000_000 + 30 * DAY))
        self.assertEqual(guards[0]['burnedRaw'], str(M))

    def test_burns_stack_and_expire(self):
        bs = [burn(ts=0, block=1, tx='0x01'), burn(ts=10 * DAY, block=2, tx='0x02')]
        guards, _ = g.decide(bs, {TOKEN: DEP}, now=59 * DAY)
        self.assertTrue(guards[0]['active'])
        self.assertEqual(guards[0]['expiresAt'], g.iso(60 * DAY))
        guards, _ = g.decide(bs, {TOKEN: DEP}, now=61 * DAY)
        self.assertFalse(guards[0]['active'])
        # A burn after expiry starts a fresh period from its own time.
        guards, _ = g.decide(bs + [burn(ts=100 * DAY, block=3, tx='0x03')], {TOKEN: DEP}, now=101 * DAY)
        self.assertEqual(guards[0]['expiresAt'], g.iso(130 * DAY))

    def test_rejections(self):
        cases = [(burn(sender='0x' + '2' * 40), {TOKEN: DEP}, 'sender is not the token deployer'),
                 (burn(amount=M - 1), {TOKEN: DEP}, 'below the 1,000,000 SNTL minimum'),
                 (burn(), {TOKEN: None}, 'not a Pons v2 token'),
                 (burn(token=g.SNTL), {g.SNTL: DEP}, 'official token is always watched')]
        for b, deps, reason in cases:
            guards, rejected = g.decide([b], deps, now=0)
            self.assertEqual(guards, [])
            self.assertEqual(rejected[0]['reason'], reason)


if __name__ == '__main__':
    unittest.main()
