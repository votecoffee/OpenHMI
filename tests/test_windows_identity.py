"""Read-only native token parsing; does not perform a password/domain logon."""

import ctypes
from ctypes import wintypes as w
import os
import unittest
from openhmi.windows_identity import WindowsIdentity


@unittest.skipUnless(os.name == 'nt', 'Native Windows readback requires Windows')
class WindowsTokenTests(unittest.TestCase):
    def test_parse_current_process_token_and_resolve_canonical_user(self):
        provider = WindowsIdentity()
        adv, kernel = provider._api()
        kernel.GetCurrentProcess.argtypes, kernel.GetCurrentProcess.restype = [], w.HANDLE
        adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
        adv.OpenProcessToken.restype = w.BOOL

        def current_token(username, domain, password, logon_type, logon_provider, output):
            # Replace only the credential boundary with a read-only TOKEN_QUERY handle.
            self.assertEqual(logon_type, 3)
            self.assertEqual(logon_provider, 0)
            return adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, output)

        adv.LogonUserW = current_token
        provider._api = lambda: (adv, kernel)
        identity = provider.authenticate('synthetic-name', 'SyntheticOnly-2026!')
        self.assertIn('\\', identity['name'])
        self.assertNotEqual(identity['name'], 'synthetic-name')
        self.assertTrue(identity['sid'].startswith('S-'))
        self.assertTrue(all(sid.startswith('S-') for sid in identity['groups']))
        self.assertEqual(provider.resolve(identity['name'], 'user'), identity['sid'])
