"""Offline tests for skills/hook-registry-check. No network.

Run: python3 tests/test_hook_registry_check.py
"""
import io, json, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills' / 'hook-registry-check'))
import hook_registry_check as hrc  # noqa: E402

# Runtime code of the NoOp hook on Robinhood Chain (0x8EF1…c0c4), read with eth_getCode on 2026-10-28.
NOOP = (Path(__file__).resolve().parent / 'fixtures' / 'noop-robinhood.hex').read_text().strip()
NOOP_ADDR = '0x8EF1699f78F830375239F6f3165cB72D5b64c0c4'
RH_PM = '0x8366a39cc670b4001a1121b8f6a443a643e40951'
BASE_PM = '0x498581ff718922c3f8e6a244956af099b2652b2b'
TSV = '\n'.join([
    '# comment line',
    f'robinhood\t4663\tfalse\t{RH_PM}\t0xf3\thttps://rh.example\thttps://x\trobinhood-mainnet',
    f'base\t8453\tfalse\t{BASE_PM}\t0xa3\thttps://base.example\thttps://x\tbase-mainnet',
    'broken line without tabs',
    'bad\tnotanumber\tfalse\t0x1\t0x2\thttps://x\thttps://y',
])
# IHooks selectors: beforeSwap(address,(address,address,uint24,int24,address),(bool,int256,uint160),bytes) and
# afterSwap(...). The registry lists NoOp with flags 0xC4 = beforeSwap + afterSwap + afterInitialize.
BEFORE_SWAP, AFTER_SWAP = '575e24b4', 'b47b2fb1'


def registry(**addresses):
    return {'chains': {'robinhood': {'chainId': 4663}, 'base': {'chainId': 8453}, 'monad': {'chainId': 143}},
            'hooks': [{'name': 'NoOp', 'stage': 'template', 'flags': '0xC4', 'addresses': addresses}]}


class Pure(unittest.TestCase):
    def test_parse_chains_tsv(self):
        t = hrc.parse_chains_tsv(TSV)
        self.assertEqual(sorted(t), [4663, 8453])
        self.assertEqual(t[4663], {'name': 'robinhood', 'rpc': 'https://rh.example', 'poolManager': RH_PM})

    def test_real_chains_tsv_from_aeon_parses(self):
        # The same columns Aeon's deploy-uni-hook reads; Robinhood must resolve to its official RPC.
        t = hrc.parse_chains_tsv(f'robinhood\t4663\tfalse\t{RH_PM}\t0xf3334192d15450cdd385c8b70e03f9a6bd9e673b\t'
                                 'https://rpc.mainnet.chain.robinhood.com\thttps://robinhoodchain.blockscout.com\trobinhood-mainnet')
        self.assertEqual(t[4663]['rpc'], 'https://rpc.mainnet.chain.robinhood.com')

    def test_flags_match(self):
        self.assertTrue(hrc.flags_match(NOOP_ADDR, '0xC4'))
        self.assertFalse(hrc.flags_match(NOOP_ADDR, '0xC0'))
        self.assertFalse(hrc.flags_match('not-an-address', '0xC4'))
        self.assertFalse(hrc.flags_match(NOOP_ADDR, None))

    def test_registry_entries_one_row_per_chain(self):
        rows = hrc.registry_entries(registry(robinhood=NOOP_ADDR, monad='0x' + '1' * 36 + '00c4'))
        self.assertEqual([(r['chain'], r['chainId']) for r in rows], [('monad', 143), ('robinhood', 4663)])

    def test_fingerprint_on_real_noop(self):
        fp = hrc.fingerprint(NOOP)
        self.assertEqual(fp['bytes'], 1442)
        self.assertEqual(fp['solc'], '0.8.26')
        self.assertIn(BEFORE_SWAP, fp['selectors'])
        self.assertIn(AFTER_SWAP, fp['selectors'])

    def test_fingerprint_no_code_and_garbage(self):
        for bad in ('0x', '0x0', '', None, '0xzz', 42):
            self.assertIsNone(hrc.fingerprint(bad))

    def test_metadata_does_not_change_build_hash(self):
        # Same code, different CBOR metadata (what a recompile with another path produces).
        body, _ = hrc.split_metadata(bytes.fromhex(NOOP[2:]))
        n = len(bytes.fromhex(NOOP[2:])) - len(body) - 2
        other = '0x' + (body + b'\x99' * n + n.to_bytes(2, 'big')).hex()
        self.assertEqual(hrc.fingerprint(NOOP)['bodyHash'], hrc.fingerprint(other)['bodyHash'])

    def test_masked_immutables_hash_the_same(self):
        # One build on two chains: only the embedded PoolManager differs.
        code = bytes.fromhex(NOOP[2:])
        self.assertIn(bytes.fromhex(RH_PM[2:]), code)  # the real NoOp embeds Robinhood's PoolManager
        on_base = '0x' + code.replace(bytes.fromhex(RH_PM[2:]), bytes.fromhex(BASE_PM[2:])).hex()
        self.assertNotEqual(hrc.fingerprint(NOOP)['bodyHash'], hrc.fingerprint(on_base)['bodyHash'])
        self.assertEqual(hrc.fingerprint(NOOP, (RH_PM,))['bodyHash'], hrc.fingerprint(on_base, (BASE_PM,))['bodyHash'])

    def test_selectors_skip_push_data(self):
        # PUSH2 0x63aabbcc... must not be read as PUSH4: the 0x63 is data, not an opcode.
        body = bytes.fromhex('61') + bytes.fromhex('63aa') + bytes.fromhex('6311223344')
        self.assertEqual(hrc.selectors(body), {'11223344'})

    def test_selector_split(self):
        fp = hrc.fingerprint(NOOP)
        odd = dict(fp, selectors=fp['selectors'][1:])
        rows = [{'chain': 'base', 'fp': fp}, {'chain': 'robinhood', 'fp': fp}, {'chain': 'ethereum', 'fp': odd}, {'chain': 'monad', 'fp': None}]
        self.assertEqual(hrc.selector_split(rows), ['ethereum'])
        self.assertEqual(hrc.selector_split(rows[:2]), [])

    def test_problems_are_stable_keys(self):
        rows = [
            {'hook': 'A', 'chain': 'base', 'address': '0x' + '0' * 36 + '00c4', 'flags': '0xC4', 'flagsOk': True, 'status': 'no-code'},
            {'hook': 'A', 'chain': 'monad', 'address': '0x' + '0' * 36 + '00c4', 'flags': '0xC4', 'flagsOk': True, 'status': 'no-rpc'},
            {'hook': 'B', 'chain': 'base', 'address': '0x' + '0' * 36 + '00c0', 'flags': '0xC4', 'flagsOk': False, 'status': 'code'},
            {'hook': 'C', 'chain': 'base', 'address': '0x' + '0' * 36 + '00c4', 'flags': '0xC4', 'flagsOk': True, 'status': 'rpc-error'},
        ]
        p = hrc.problems(rows)
        self.assertEqual(len(p), 3)  # an RPC error is not a registry problem
        self.assertTrue(any(x.startswith('A@base: no code') for x in p))
        self.assertTrue(any(x.startswith('B@base: flags 0xC4 do not match') and '0xc0' in x for x in p))
        self.assertEqual(p, sorted(p))


class EndToEnd(unittest.TestCase):
    def run_main(self, reg, codes, state=None, chain_ids=None):
        chain_ids = chain_ids or {'https://rh.example': 4663, 'https://base.example': 8453}

        def fake_rpc(url, method, params):
            if method == 'eth_chainId':
                return hex(chain_ids[url])
            if method == 'eth_blockNumber':
                return hex(100)
            return codes.get((url, params[0].lower()), '0x')

        with tempfile.TemporaryDirectory() as d:
            reg_path, tsv_path = Path(d) / 'hooklist.json', Path(d) / 'chains.tsv'
            reg_path.write_text(json.dumps(reg))
            tsv_path.write_text(TSV)
            args = ['--hooklist', str(reg_path), '--chains-tsv', str(tsv_path), '--json']
            if state:
                args += ['--state', state]
            out = io.StringIO()
            with mock.patch.object(hrc, 'rpc', side_effect=fake_rpc), mock.patch.object(hrc.time, 'sleep'), redirect_stdout(out):
                code = hrc.main(args)
        return code, json.loads(out.getvalue())

    def test_real_noop_on_two_chains_and_monad_unchecked(self):
        base_addr = '0xFBa729A7d8fc48cBb261A845A0f26281ED7800C4'
        on_base = '0x' + bytes.fromhex(NOOP[2:]).replace(bytes.fromhex(RH_PM[2:]), bytes.fromhex(BASE_PM[2:])).hex()
        codes = {('https://rh.example', NOOP_ADDR.lower()): NOOP, ('https://base.example', base_addr.lower()): on_base}
        code, rep = self.run_main(registry(robinhood=NOOP_ADDR, base=base_addr, monad='0x707A3072E285A2e2398253A30Bf6Bd7b5a7B40c4'), codes)
        self.assertEqual(code, 0)
        s = rep['summary']
        self.assertEqual((s['addresses'], s['withCode'], s['noCode'], s['unchecked'], s['flagMismatch']), (3, 2, 0, 1, 0))
        self.assertEqual(rep['problems'], ['NoOp@monad: chain not in deploy-uni-hook chains.tsv, cannot be checked'])
        self.assertEqual(rep['variants'], [{'hook': 'NoOp', 'variants': 1, 'groups': [['base', 'robinhood']], 'selectorsMatch': True}])

    def test_missing_code_and_wrong_chain_are_findings(self):
        codes = {}  # no code anywhere
        code, rep = self.run_main(registry(robinhood=NOOP_ADDR, base='0xFBa729A7d8fc48cBb261A845A0f26281ED7800C4'), codes,
                                  chain_ids={'https://rh.example': 4663, 'https://base.example': 1})
        self.assertEqual(code, 0)
        self.assertIn('NoOp@robinhood: no code at ' + NOOP_ADDR, rep['problems'])
        self.assertIn('NoOp@base: RPC answered for another chain', rep['problems'])

    def test_state_reports_only_changes(self):
        with tempfile.TemporaryDirectory() as d:
            state = str(Path(d) / 'state.json')
            reg = registry(robinhood=NOOP_ADDR)
            _, first = self.run_main(reg, {}, state)
            self.assertTrue(first['changed'])
            _, second = self.run_main(reg, {}, state)
            self.assertFalse(second['changed'])
            self.assertEqual(second['newSinceLast'], [])
            _, third = self.run_main(reg, {('https://rh.example', NOOP_ADDR.lower()): NOOP}, state)
            self.assertTrue(third['changed'])
            self.assertEqual(third['resolvedSinceLast'], ['NoOp@robinhood: no code at ' + NOOP_ADDR])

    def test_rpc_error_is_not_a_finding(self):
        def broken(url, method, params):
            raise hrc.RpcError('HTTP 429')
        with tempfile.TemporaryDirectory() as d:
            reg_path, tsv_path = Path(d) / 'h.json', Path(d) / 'c.tsv'
            reg_path.write_text(json.dumps(registry(robinhood=NOOP_ADDR)))
            tsv_path.write_text(TSV)
            out = io.StringIO()
            with mock.patch.object(hrc, 'rpc', side_effect=broken), redirect_stdout(out):
                self.assertEqual(hrc.main(['--hooklist', str(reg_path), '--chains-tsv', str(tsv_path), '--json']), 0)
        rep = json.loads(out.getvalue())
        self.assertEqual(rep['problems'], [])
        self.assertEqual(rep['summary']['unchecked'], 1)

    def test_one_empty_answer_is_reread_not_reported(self):
        # Live 2026-10-28: Unichain's public RPC answered '0x' once for a hook that has code.
        answers = iter(['0x', NOOP])

        def flaky(url, method, params):
            if method == 'eth_chainId':
                return hex(4663)
            if method == 'eth_blockNumber':
                return hex(100)
            return next(answers)
        with tempfile.TemporaryDirectory() as d:
            reg_path, tsv_path = Path(d) / 'h.json', Path(d) / 'c.tsv'
            reg_path.write_text(json.dumps(registry(robinhood=NOOP_ADDR)))
            tsv_path.write_text(TSV)
            out = io.StringIO()
            with mock.patch.object(hrc, 'rpc', side_effect=flaky), mock.patch.object(hrc.time, 'sleep'), redirect_stdout(out):
                hrc.main(['--hooklist', str(reg_path), '--chains-tsv', str(tsv_path), '--json'])
        rep = json.loads(out.getvalue())
        self.assertEqual(rep['problems'], [])
        self.assertEqual(rep['summary']['withCode'], 1)

    def test_unreachable_registry_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(hrc.main(['--hooklist', str(Path(d) / 'missing.json'), '--chains-tsv', str(Path(d) / 'x')]), 2)

    def test_markdown_states_facts_only(self):
        _, rep = self.run_main(registry(robinhood=NOOP_ADDR), {})
        md = hrc.to_markdown(rep)
        self.assertTrue(md.startswith('HOOK REGISTRY: CHANGES'))
        self.assertIn('not a verdict on the hook', md)
        for word in ('scam', 'malicious', 'unsafe', 'rug'):
            self.assertNotIn(word, md.lower())


if __name__ == '__main__':
    unittest.main()
