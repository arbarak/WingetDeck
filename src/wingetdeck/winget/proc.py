"""Freeze, thaw and kill a process and its children, using Windows' own calls."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_SUSPEND_RESUME = 0x0800
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED = 0x1000
_STILL_ACTIVE = 259
_INVALID_HANDLE = ctypes.c_void_p(-1).value

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_ntdll = ctypes.WinDLL("ntdll")


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
_kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_ntdll.NtSuspendProcess.argtypes = [wintypes.HANDLE]
_ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]


@dataclass(frozen=True)
class KillResult:
    killed: bool
    access_denied: bool = False


def _snapshot() -> list[tuple[int, int, str]]:
    handle = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if handle == _INVALID_HANDLE:
        return []
    rows: list[tuple[int, int, str]] = []
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        more = _kernel32.Process32FirstW(handle, ctypes.byref(entry))
        while more:
            rows.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            more = _kernel32.Process32NextW(handle, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(handle)
    return rows


def all_pids() -> set[int]:
    return {pid for pid, _, _ in _snapshot()}


def _started_at(pid: int) -> int | None:
    """When the process started, or None if Windows will not say."""

    def read(handle) -> int | bool:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not _kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return False
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime

    return _with_handle(pid, _PROCESS_QUERY_LIMITED, read) or None


def _may_be_child(parent_born: int | None, child_born: int | None) -> bool:
    """Windows keeps a dead parent's id on its orphans and reuses ids, so a listed parent can be a
    stranger. A process older than its listed parent cannot be its child. If either time is unknown it
    counts as a child, because losing track of a running installer is the worse mistake."""
    return parent_born is None or child_born is None or child_born >= parent_born


def process_tree(pid: int) -> list[int]:
    """The process and everything under it, parents first. Empty if it no longer exists."""
    rows = _snapshot()
    if not any(p == pid for p, _, _ in rows):
        return []
    tree = [pid]
    for current in tree:
        born = _started_at(current)
        for child, parent, _ in rows:
            if parent == current and child not in tree and _may_be_child(born, _started_at(child)):
                tree.append(child)
    return tree


def tree_names(pid: int) -> list[str]:
    """Names of the processes under pid, for telling that an installer has started."""
    rows = _snapshot()
    tree = process_tree(pid)
    return [name for p, _, name in rows if p in tree and p != pid]


def _with_handle(pid: int, access: int, action) -> bool:
    handle = _kernel32.OpenProcess(access, False, pid)
    if not handle:
        return False
    try:
        return action(handle)
    finally:
        _kernel32.CloseHandle(handle)


def freeze_tree(pid: int) -> None:
    for member in process_tree(pid):
        _with_handle(member, _PROCESS_SUSPEND_RESUME, lambda h: _ntdll.NtSuspendProcess(h) == 0)


def thaw_tree(pid: int) -> None:
    # Walk the tree again: a child may have appeared while it was being frozen.
    for member in process_tree(pid):
        _with_handle(member, _PROCESS_SUSPEND_RESUME, lambda h: _ntdll.NtResumeProcess(h) == 0)


def _terminate(pid: int) -> bool:
    return _with_handle(pid, _PROCESS_TERMINATE, lambda h: bool(_kernel32.TerminateProcess(h, 1)))


def _exists(pid: int) -> bool:
    def active(handle) -> bool:
        code = wintypes.DWORD()
        return bool(_kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == _STILL_ACTIVE

    return _with_handle(pid, _PROCESS_QUERY_LIMITED, active)


def kill_tree(pid: int) -> KillResult:
    """Kill children first. An elevated installer cannot be killed from a normal run: say so."""
    tree = process_tree(pid)
    denied = False
    for member in reversed(tree):
        if not _terminate(member) and _exists(member):
            denied = True
    return KillResult(killed=not denied, access_denied=denied)
