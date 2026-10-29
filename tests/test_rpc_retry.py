"""Regression test: every RPC helper retries when the public RPC drops the connection.

Seen live on 2026-10-29 15:00 WIB: snapshot-burn.py failed on http.client.RemoteDisconnected, which is not a
urllib URLError, so the retry did not catch it. No network: urlopen is patched, sleeps are skipped.

Run: python3 tests/test_rpc_retry.py
"""
import http.client, importlib.util, io, json, sys, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULES = {
    'snapshot_burn': 'scripts/snapshot-burn.py',
    'hook_registry_check': 'skills/hook-registry-check/hook_registry_check.py',
    'hook_usage': 'skills/hook-usage/hook_usage.py',
    'pons_curve_movers': 'skills/pons-curve-movers/pons_curve_movers.py',
    'pons_deployer_watch': 'skills/pons-deployer-watch/pons_deployer_watch.py',
    'pons_graduation_watch': 'skills/pons-graduation-watch/pons_graduation_watch.py',
    'pons_launch_watch': 'skills/pons-launch-watch/pons_launch_watch.py',
    'pons_token_check': 'skills/pons-token-check/pons_token_check.py',
}


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Ok(io.BytesIO):
    """A urlopen() result that also works as a context manager."""
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def call(mod):
    """One eth_chainId through the module's own RPC helper, whatever its signature."""
    if hasattr(mod, 'post') and mod.post.__code__.co_argcount == 2:   # hook_registry_check: post(url, body)
        return mod.rpc('https://rpc.invalid', 'eth_chainId', [])
    return mod.rpc('eth_chainId', [])


class DroppedConnection(unittest.TestCase):
    def check(self, name, rel, error):
        mod = load(name, rel)
        calls = []

        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise error
            return Ok(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': '0x1237'}).encode())

        opener = 'urlopen' if hasattr(mod, 'urlopen') else None
        target = (mod, 'urlopen') if opener else (mod.urllib.request, 'urlopen')
        with mock.patch.object(*target, side_effect=flaky), mock.patch.object(mod.time, 'sleep', lambda s: None):
            self.assertEqual(call(mod), '0x1237', f'{rel} did not retry {type(error).__name__}')
        self.assertEqual(len(calls), 2, rel)

    def test_remote_disconnected_is_retried_everywhere(self):
        for name, rel in MODULES.items():
            with self.subTest(rel):
                self.check(name, rel, http.client.RemoteDisconnected('Remote end closed connection without response'))

    def test_reset_and_truncated_reads_are_retried(self):
        for name, rel in MODULES.items():
            with self.subTest(rel):
                self.check(name, rel, ConnectionResetError(104, 'Connection reset by peer'))
                self.check(name, rel, http.client.IncompleteRead(b'{"jsonrpc"'))


if __name__ == '__main__':
    unittest.main()
