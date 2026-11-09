import subprocess
import sys
import threading
import time

from wingetdeck.winget import proc
from wingetdeck.winget.proc import KillResult, freeze_tree, kill_tree, process_tree, thaw_tree

TICK = "import time\nwhile True:\n print(time.time(), flush=True); time.sleep(.05)"
PARENT = (
    "import subprocess,sys,time\n"
    "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
    "print(c.pid,flush=True);time.sleep(60)"
)


def _ticker():
    child = subprocess.Popen([sys.executable, "-c", TICK], stdout=subprocess.PIPE, text=True)
    lines = []
    threading.Thread(target=lambda: [lines.append(x) for x in child.stdout], daemon=True).start()
    return child, lines


def test_freeze_stops_and_thaw_restarts_a_real_process():
    child, lines = _ticker()
    try:
        time.sleep(0.5)
        assert lines
        freeze_tree(child.pid)
        time.sleep(0.2)
        before = len(lines)
        time.sleep(1)
        assert len(lines) == before
        thaw_tree(child.pid)
        time.sleep(0.5)
        assert len(lines) > before
    finally:
        child.kill()


def test_process_tree_lists_children():
    parent = subprocess.Popen([sys.executable, "-c", PARENT], stdout=subprocess.PIPE, text=True)
    try:
        child_pid = int(parent.stdout.readline())
        assert set(process_tree(parent.pid)) >= {parent.pid, child_pid}
    finally:
        kill_tree(parent.pid)


def test_kill_tree_kills_children():
    parent = subprocess.Popen([sys.executable, "-c", PARENT], stdout=subprocess.PIPE, text=True)
    child_pid = int(parent.stdout.readline())
    result = kill_tree(parent.pid)
    assert result == KillResult(killed=True, access_denied=False)
    parent.wait(5)
    time.sleep(0.2)
    assert child_pid not in proc.all_pids()


def test_kill_reports_access_denied_not_crash(monkeypatch):
    monkeypatch.setattr(proc, "process_tree", lambda pid: [pid])
    monkeypatch.setattr(proc, "_terminate", lambda pid: False)
    monkeypatch.setattr(proc, "_exists", lambda pid: True)
    assert kill_tree(12345) == KillResult(killed=False, access_denied=True)


def test_kill_of_process_already_gone_counts_as_killed(monkeypatch):
    monkeypatch.setattr(proc, "process_tree", lambda pid: [])
    assert kill_tree(999999).killed


def test_freeze_of_missing_process_does_not_raise():
    freeze_tree(999999)
    thaw_tree(999999)
