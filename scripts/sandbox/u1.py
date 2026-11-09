"""U1: does freeze or kill really stop the network with the direct downloader?
Runs the default downloader first as a control: it must reproduce what was seen on the owner's PC.
Then U3: what installs print, across installer types.
"""

import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from spike_tools import WINGET, Run, rates, save, set_downloader, suspend, temp_files

out = sys.argv[1]
PACKAGE = "Microsoft.VisualStudioCode"
ACCEPT = ["--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]


def one(label: str, downloader: str | None) -> dict:
    set_downloader(downloader)
    target = tempfile.mkdtemp(prefix=f"dl-{label}-")
    result: dict = {"downloader": downloader, "idle_mb_s": rates(3)}
    run = Run("download", "--id", PACKAGE, "-e", "-s", "winget", "-d", target, *ACCEPT,
              raw_path=Path(out, f"pty_{label}.txt"))
    result["progress_started"] = run.wait_for_progress()
    if not result["progress_started"]:
        result["no_progress_output"] = run.clean()[-800:]
        run.kill()
        return result
    result["first_progress"] = run.sizes[-1]
    result["during_download_mb_s"] = rates(1)
    result["suspend_status"] = suspend(run.pid)
    result["frozen_mb_s"] = rates(8)
    result["progress_while_frozen"] = run.sizes[-1]
    result["temp_files_frozen"] = temp_files()
    result["resume_status"] = suspend(run.pid, resume=True)
    result["after_thaw_mb_s"] = rates(1)
    result["progress_after_thaw"] = run.sizes[-1]
    result["alive_before_kill"] = run.proc.isalive()
    result["kill"] = run.kill()
    time.sleep(0.3)
    result["after_kill_mb_s"] = rates(6)
    result["temp_files_after_kill"] = temp_files()
    result["alive_after_kill"] = run.proc.isalive()
    run.wait(5)
    return result


results = {"default": one("default", None)}
save(out, "u1.json", results)
time.sleep(5)
results["wininet"] = one("wininet", "wininet")
save(out, "u1.json", results)

# Full download with wininet, to confirm it works at all
set_downloader("wininet")
run = Run("download", "--id", "jqlang.jq", "-e", "-s", "winget", "-d", tempfile.mkdtemp(), *ACCEPT)
results["wininet_complete_exit"] = run.wait(180)
save(out, "u1.json", results)
set_downloader(None)


def older_version(package: str) -> str | None:
    text = subprocess.run([WINGET, "show", "--id", package, "-e", "-s", "winget", "--versions", *ACCEPT[1:]],
                          capture_output=True).stdout.decode("utf-8", "replace")
    lines = [ln.strip() for ln in text.splitlines()]
    dash = next((i for i, ln in enumerate(lines) if ln.startswith("---")), None)
    versions = [ln for ln in lines[dash + 1:] if ln] if dash is not None else []
    return versions[1] if len(versions) > 1 else None


def installer_test(label: str, package: str, app_running: str | None = None) -> dict:
    result: dict = {"package": package}
    version = older_version(package)
    result["older_version"] = version
    if not version:
        return result
    done = subprocess.run([WINGET, "install", "--id", package, "-e", "-s", "winget", "-v", version, "--silent", *ACCEPT],
                          capture_output=True, timeout=300)
    result["install_exit"] = hex(done.returncode & 0xFFFFFFFF)
    time.sleep(2)
    app = None
    if app_running:
        found = list(Path("C:/Program Files").rglob(app_running))
        if found:
            app = subprocess.Popen([str(found[0])])
            time.sleep(2)
        result["app_started"] = bool(found)
    run = Run("upgrade", "--id", package, "-e", "-s", "winget", "--silent", *ACCEPT,
              raw_path=Path(out, f"pty_install_{label}.txt"))
    code = run.wait(180)
    result["upgrade_exit"] = hex(code & 0xFFFFFFFF) if code is not None else "still running after 180 s"
    result["child_processes"] = sorted(run.children)
    result["clean_output"] = re.sub(r"[\s\S]*?(Found)", r"\1", run.clean(), count=1)[-1500:]
    if code is None:
        run.kill()
    if app:
        app.kill()
    return result


u3 = {}
for label, package, running in [
    ("nullsoft", "Notepad++.Notepad++", None),
    ("msi", "PuTTY.PuTTY", None),
    ("portable", "jqlang.jq", None),
]:
    try:
        u3[label] = installer_test(label, package, running)
    except Exception as e:
        u3[label] = {"error": repr(e)}
    save(out, "u3.json", u3)
