"""U2: how long can a direct download stay frozen and still finish after thawing?"""

import sys
import tempfile
import time
from pathlib import Path

from spike_tools import Run, save, set_downloader, suspend

out = sys.argv[1]
PACKAGE = "Git.Git"
ACCEPT = ["--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]
results = {}

# Control: the default downloader, after sources are fresh, so the freeze lands on the real download.
import subprocess
from spike_tools import WINGET, rates, temp_files

subprocess.run([WINGET, "source", "update", "--disable-interactivity"], capture_output=True, timeout=300)
set_downloader(None)
control = Run("download", "--id", "Microsoft.VisualStudioCode", "-e", "-s", "winget", "-d", tempfile.mkdtemp(), *ACCEPT,
              raw_path=Path(out, "pty_control.txt"))
control.wait_for_progress()
results["control_default"] = {"first_progress": control.sizes[-1] if control.sizes else None, "during_mb_s": rates(1)}
suspend(control.pid)
results["control_default"]["frozen_mb_s"] = rates(6)
results["control_default"]["progress_while_frozen"] = control.sizes[-1] if control.sizes else None
results["control_default"]["temp_frozen"] = temp_files()
suspend(control.pid, resume=True)
results["control_default"]["kill"] = control.kill()
results["control_default"]["after_kill_mb_s"] = rates(6)
results["control_default"]["temp_after_kill"] = temp_files()
save(out, "u2.json", results)
time.sleep(20)

set_downloader("wininet")
for minutes in (1, 5, 15):
    run = Run("download", "--id", PACKAGE, "-e", "-s", "winget", "-d", tempfile.mkdtemp(), *ACCEPT)
    started = run.wait_for_progress()
    at_freeze = run.sizes[-1] if run.sizes else None
    suspend(run.pid)
    time.sleep(minutes * 60)
    suspend(run.pid, resume=True)
    thawed = time.time()
    code = run.wait(300)
    results[f"{minutes}_min"] = {
        "started": started,
        "at_freeze": at_freeze,
        "last_progress": run.sizes[-1] if run.sizes else None,
        "exit": hex(code & 0xFFFFFFFF) if code is not None else "hung",
        "seconds_after_thaw": round(time.time() - thawed, 1),
        "tail": run.clean()[-400:],
    }
    save(out, "u2.json", results)
    Path(out, "pty_u2.txt").write_text("".join(run.raw), encoding="utf-8", newline="")
set_downloader(None)
