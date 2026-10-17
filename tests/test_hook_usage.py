import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills' / 'hook-usage'))
import hook_usage as hu  # noqa: E402

HOOK = '0x7566a3bfbe88c06bc5f33fea927f461e8279d0c4'
OTHER = '0x' + '11' * 20


def word(hex_value):
    return hex_value.rjust(64, '0')


def init_data(hook):
    # fee, tickSpacing, hooks, sqrtPriceX96, tick
    words = [word('bb8'), word('3c'), word(hook[2:]), word('1' * 40), word('0')]
    assert all(len(w) == 64 for w in words)
    return '0x' + ''.join(words)


class DecodeTests(unittest.TestCase):
    def test_hook_is_third_word(self):
        self.assertEqual(hu.hook_from_initialize(init_data(HOOK)), HOOK)

    def test_hook_is_lowercased(self):
        self.assertEqual(hu.hook_from_initialize(init_data(HOOK.upper().replace('0X', '0x'))), HOOK)

    def test_short_data_rejected(self):
        with self.assertRaises(ValueError):
            hu.hook_from_initialize('0x' + '00' * 64)

    def test_misaligned_data_rejected(self):
        with self.assertRaises(ValueError):
            hu.hook_from_initialize(init_data(HOOK) + '0')

    def test_event_topics_match_signatures(self):
        # Verified with viem keccak256 against the v4 PoolManager event signatures.
        self.assertEqual(hu.INITIALIZE, '0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438')
        self.assertEqual(hu.SWAP, '0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f')


class RegistryTests(unittest.TestCase):
    def test_only_robinhood_entries_and_flag_check(self):
        reg = {'hooks': [
            {'name': 'DynamicFee', 'flags': '0x10C4', 'addresses': {'robinhood': HOOK, 'base': OTHER}},
            {'name': 'BaseOnly', 'flags': '0xC4', 'addresses': {'base': OTHER}},
            {'name': 'Bad', 'flags': '0xC4', 'addresses': {'robinhood': OTHER}},
        ]}
        hooks = hu.load_registry(fetch=lambda url: reg)
        self.assertEqual(set(hooks), {HOOK, OTHER})
        self.assertTrue(hooks[HOOK]['flagsMatch'])
        self.assertFalse(hooks[OTHER]['flagsMatch'])


class ScanTests(unittest.TestCase):
    def test_scan_pools_keeps_only_registry_hooks_and_advances_cursor(self):
        calls = []

        def fake_logs(topics, lo, hi):
            calls.append((lo, hi))
            return [{'topics': [hu.INITIALIZE, '0xaa'], 'data': init_data(HOOK), 'blockNumber': hex(lo)},
                    {'topics': [hu.INITIALIZE, '0xbb'], 'data': init_data(OTHER), 'blockNumber': hex(lo)}] if lo == 100 else []

        orig, hu.get_logs = hu.get_logs, fake_logs
        orig_sleep, hu.time.sleep = hu.time.sleep, lambda s: None
        try:
            state = {'lastBlock': 99}
            pools = hu.scan_pools(state, {HOOK: {'name': 'DynamicFee'}}, head=100 + hu.INIT_STEP, log=lambda m: None)
        finally:
            hu.get_logs, hu.time.sleep = orig, orig_sleep
        self.assertEqual(pools, {'0xaa': {'hook': HOOK, 'block': 100}})
        self.assertEqual(state['lastBlock'], 100 + hu.INIT_STEP)
        self.assertEqual(calls[0], (100, 100 + hu.INIT_STEP - 1))

    def test_get_logs_splits_range_on_cap(self):
        def fake_rpc(method, params):
            f = params[0]
            lo, hi = int(f['fromBlock'], 16), int(f['toBlock'], 16)
            if hi - lo > 10:
                raise hu.RpcError('logs matched by query exceeds limit of 10000')
            return [{'block': lo}]

        orig, hu.rpc = hu.rpc, fake_rpc
        try:
            out = hu.get_logs([hu.INITIALIZE], 0, 40)
        finally:
            hu.rpc = orig
        self.assertEqual([o['block'] for o in out], sorted(o['block'] for o in out))
        self.assertGreater(len(out), 1)

    def test_other_rpc_errors_are_not_swallowed(self):
        orig, hu.rpc = hu.rpc, lambda m, p: (_ for _ in ()).throw(hu.RpcError('eth_getLogs: HTTP 500'))
        try:
            with self.assertRaises(hu.RpcError):
                hu.get_logs([hu.INITIALIZE], 0, 10)
        finally:
            hu.rpc = orig


class ReportTests(unittest.TestCase):
    def test_report_totals_and_ordering(self):
        hooks = {HOOK: {'name': 'DynamicFee', 'stage': 'template', 'flagsMatch': True},
                 OTHER: {'name': 'Quiet', 'stage': 'deployed', 'flagsMatch': True}}
        pools = {'0xaa': {'hook': HOOK, 'block': 1}, '0xbb': {'hook': HOOK, 'block': 2}}
        swaps = {'0xaa': 5}
        senders = {'0xaa': {'0x1', '0x2'}}
        r = hu.build_report(hooks, pools, swaps, senders, head=123, days=7)
        self.assertEqual(r['totals'], {'hooks': 2, 'hooksWithPools': 1, 'pools': 2, 'swaps': 5})
        self.assertEqual(r['hooks'][0]['hook'], 'DynamicFee')
        self.assertEqual(r['hooks'][0]['activePools'], 1)
        self.assertEqual(r['hooks'][0]['uniqueSenders'], 2)
        self.assertEqual(r['hooks'][1]['pools'], 0)
        md = hu.to_markdown(r)
        self.assertIn('1/2 hooks have pools', md)
        self.assertIn('DynamicFee: 2 pools, 1 active, 5 swaps, 2 callers', md)


if __name__ == '__main__':
    unittest.main()
