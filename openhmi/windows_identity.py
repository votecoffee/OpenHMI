"""Windows password validation and enabled token-group SIDs; no impersonation."""

import ctypes
from contextlib import closing, contextmanager
from ctypes import wintypes as w
import os
import sqlite3


def enabled_group(attributes):
    return bool(attributes & 0x4) and not bool(attributes & 0x10)  # enabled, never deny-only


@contextmanager
def read_security_database(project):
    with closing(sqlite3.connect(project.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA trusted_schema=OFF')
        yield db


def check_mappings(project, identity):
    """Compare saved account names with current Windows SIDs without opening a runtime."""
    if not identity.available:
        raise RuntimeError('Windows mapping checks require a Windows server')
    with read_security_database(project) as db:
        enabled = db.execute('SELECT windows_enabled FROM security_settings WHERE id=1').fetchone()
        bindings = db.execute('SELECT sid,kind,label,hmi_group FROM security_windows ORDER BY label,kind,hmi_group').fetchall()
    if enabled is None:
        raise RuntimeError('Project has no HMI security settings')

    results = []
    for sid, kind, label, group in bindings:
        item = {'account': label, 'kind': kind, 'hmi_group': group, 'saved_sid': sid}
        try:
            if kind not in ('user', 'group') or not label or '\x00' in label:
                raise ValueError('Invalid stored Windows identity')
            resolved = identity.resolve(label, kind)
        except (OSError, ValueError) as error:
            item.update(status='unresolved', error=str(error))
        else:
            item.update(status='matched' if resolved == sid else 'mismatch', resolved_sid=resolved)
        results.append(item)

    report = {'ok': bool(results) and all(item['status'] == 'matched' for item in results),
              'windows_login_enabled': bool(enabled[0]), 'checked': len(results), 'mappings': results}
    if not results:
        report['message'] = 'No Windows assignments are configured.'
    return report


class WindowsIdentity:
    def __init__(self):
        self.available = os.name == 'nt'

    def _api(self):
        if not self.available:
            raise OSError('Windows login requires a Windows server')
        adv = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'LogonUserW': ([w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(w.HANDLE)], w.BOOL),
            'GetTokenInformation': ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)], w.BOOL),
            'ConvertSidToStringSidW': ([w.LPVOID, ctypes.POINTER(w.LPWSTR)], w.BOOL),
            'LookupAccountNameW': ([w.LPCWSTR, w.LPCWSTR, w.LPVOID, ctypes.POINTER(w.DWORD), w.LPWSTR, ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD)], w.BOOL),
            'LookupAccountSidW': ([w.LPCWSTR, w.LPVOID, w.LPWSTR, ctypes.POINTER(w.DWORD), w.LPWSTR, ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD)], w.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(adv, name)
            function.argtypes, function.restype = arguments, result
        kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
        kernel.LocalFree.argtypes, kernel.LocalFree.restype = [w.LPVOID], w.LPVOID
        return adv, kernel

    @staticmethod
    def _sid(adv, kernel, pointer):
        result = w.LPWSTR()
        if not adv.ConvertSidToStringSidW(pointer, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return result.value
        finally:
            kernel.LocalFree(ctypes.cast(result, w.LPVOID))

    def resolve(self, name, kind):
        adv, kernel = self._api()
        size, domain_size, use = w.DWORD(), w.DWORD(), w.DWORD()
        adv.LookupAccountNameW(None, name, None, ctypes.byref(size), None, ctypes.byref(domain_size), ctypes.byref(use))
        if not size.value:
            raise OSError('Windows account or group could not be resolved')
        sid = ctypes.create_string_buffer(size.value)
        domain = ctypes.create_unicode_buffer(domain_size.value)
        if not adv.LookupAccountNameW(None, name, sid, ctypes.byref(size), domain, ctypes.byref(domain_size), ctypes.byref(use)):
            raise OSError('Windows account or group could not be resolved')
        if (kind == 'user' and use.value != 1) or (kind == 'group' and use.value not in (2, 4, 5)):
            raise ValueError('Windows identity is not the requested user/group type')
        return self._sid(adv, kernel, sid)

    def authenticate(self, name, password):
        if '\x00' in name or '\x00' in password:
            return None
        adv, kernel = self._api()
        domain, username = (name.split('\\', 1) if '\\' in name else (None if '@' in name else '.', name))
        token = w.HANDLE()
        secret = ctypes.create_unicode_buffer(password)
        try:
            if not adv.LogonUserW(username, domain, secret, 3, 0, ctypes.byref(token)):
                return None

            def information(kind):
                length = w.DWORD()
                adv.GetTokenInformation(token, kind, None, 0, ctypes.byref(length))
                buffer = ctypes.create_string_buffer(length.value)
                if not adv.GetTokenInformation(token, kind, buffer, length, ctypes.byref(length)):
                    raise ctypes.WinError(ctypes.get_last_error())
                return buffer

            class SidAttributes(ctypes.Structure):
                _fields_ = [('sid', w.LPVOID), ('attributes', w.DWORD)]

            class TokenGroups(ctypes.Structure):
                _fields_ = [('count', w.DWORD), ('groups', SidAttributes * 1)]

            user = information(1)
            user_pointer = SidAttributes.from_buffer(user).sid
            user_sid = self._sid(adv, kernel, user_pointer)
            name_size, domain_size, use = w.DWORD(), w.DWORD(), w.DWORD()
            adv.LookupAccountSidW(None, user_pointer, None, ctypes.byref(name_size), None, ctypes.byref(domain_size), ctypes.byref(use))
            account_name, account_domain = ctypes.create_unicode_buffer(name_size.value), ctypes.create_unicode_buffer(domain_size.value)
            if not adv.LookupAccountSidW(None, user_pointer, account_name, ctypes.byref(name_size), account_domain, ctypes.byref(domain_size), ctypes.byref(use)):
                raise OSError('Authenticated Windows identity could not be resolved')
            canonical_name = f'{account_domain.value}\\{account_name.value}'
            groups = information(2)
            count = w.DWORD.from_buffer(groups).value
            entries = (SidAttributes * count).from_buffer(groups, TokenGroups.groups.offset)
            return {'name': canonical_name, 'sid': user_sid, 'groups': [self._sid(adv, kernel, entry.sid) for entry in entries if enabled_group(entry.attributes)]}
        finally:
            ctypes.memset(ctypes.addressof(secret), 0, ctypes.sizeof(secret))
            if token:
                kernel.CloseHandle(token)
