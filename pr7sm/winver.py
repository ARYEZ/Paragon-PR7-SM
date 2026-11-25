"""A program's file details (Properties > Details): description, company, version. No Qt.

Windows keeps them in the .exe's version resource, read here with GetFileVersionInfoW / VerQueryValueW (the same
calls Process Explorer makes). Each file is read once and remembered. Elsewhere there are none: empty strings."""

from __future__ import annotations

import sys

_cache: dict[str, dict] = {}


def details(path: str) -> dict:
    if not path:
        return {}
    key = path.casefold()
    if key not in _cache:
        try:
            _cache[key] = _read(path) if sys.platform == "win32" else {}
        except Exception:  # noqa: BLE001 - an unreadable file has no details
            _cache[key] = {}
    return _cache[key]


def _read(path: str) -> dict:
    import ctypes
    from ctypes import wintypes
    ver = ctypes.windll.version
    size = ver.GetFileVersionInfoSizeW(path, None)
    if not size:
        return {}
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(path, 0, size, buf):
        return {}
    ptr, n = ctypes.c_void_p(), wintypes.UINT()

    def query(sub):
        if ver.VerQueryValueW(buf, sub, ctypes.byref(ptr), ctypes.byref(n)) and n.value:
            return ptr
        return None
    langs = []
    if query("\\VarFileInfo\\Translation"):
        arr = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * (n.value // 2))).contents
        langs = [f"{arr[i]:04x}{arr[i + 1]:04x}" for i in range(0, len(arr) - 1, 2)]
    langs += ["040904b0", "040904e4", "000004b0"]
    out = {}
    for name, field in (("description", "FileDescription"), ("company", "CompanyName"),
                        ("version", "FileVersion"), ("product", "ProductName")):
        for lang in langs:
            if query(f"\\StringFileInfo\\{lang}\\{field}"):
                out[name] = ctypes.wstring_at(ptr, n.value).rstrip("\0").strip()
                break
    return out
