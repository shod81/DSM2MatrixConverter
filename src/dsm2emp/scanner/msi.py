"""MSI scanning and ProductCode GUID extraction using Windows Installer API."""

from __future__ import annotations

import ctypes
from pathlib import Path

from dsm2emp.rules.msi import extract_product_code_from_msi_binary, is_valid_guid


def extract_product_code_from_msi(msi_path: Path | str) -> str | None:
    """Extract the ProductCode GUID from an MSI file.

    Uses Windows Installer API (ctypes.windll.msi) when available on Windows,
    with a binary fallback parsing mechanism for cross-platform/non-Windows environments.
    """
    p = Path(msi_path)
    if not p.is_file():
        return None

    # 1. Primary approach on Windows: Windows Installer Database API
    try:
        if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "msi"):
            from ctypes import wintypes

            msi = ctypes.windll.msi
            hDb = wintypes.HANDLE()
            # MSIDBOPEN_READONLY = 0
            if msi.MsiOpenDatabaseW(str(p.resolve()), ctypes.c_wchar_p(0), ctypes.byref(hDb)) == 0:
                try:
                    hView = wintypes.HANDLE()
                    query = "SELECT `Value` FROM `Property` WHERE `Property` = 'ProductCode'"
                    if msi.MsiDatabaseOpenViewW(hDb, query, ctypes.byref(hView)) == 0:
                        try:
                            if msi.MsiViewExecute(hView, 0) == 0:
                                hRecord = wintypes.HANDLE()
                                if msi.MsiViewFetch(hView, ctypes.byref(hRecord)) == 0:
                                    try:
                                        buf = ctypes.create_unicode_buffer(128)
                                        size = wintypes.DWORD(128)
                                        rc = msi.MsiRecordGetStringW(
                                            hRecord, 1, buf, ctypes.byref(size)
                                        )
                                        if rc == 0:
                                            val = buf.value.strip()
                                            if is_valid_guid(val):
                                                return val.upper()
                                    finally:
                                        msi.MsiCloseHandle(hRecord)
                        finally:
                            msi.MsiCloseHandle(hView)
                finally:
                    msi.MsiCloseHandle(hDb)
    except Exception:
        pass

    # 2. Binary fallback (useful in tests, mock files with embedded GUID, or non-Windows)
    return extract_product_code_from_msi_binary(p)
