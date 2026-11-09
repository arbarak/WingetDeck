"""Tries the Get winget steps against the real GitHub and the real Windows, and installs nothing.

    repair_check.py              looks for a version, and reads the package's signature details from a dependency
    repair_check.py --download   also downloads every file (about 300 MB) and runs every check, stopping before install

It never runs the real install or activate command. Their PowerShell is tried only with a package name and a file that
do not exist, to prove that Windows' answer reaches the user as a readable message.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import threading
from pathlib import Path

from wingetdeck.winget.repair import (
    PACKAGE_FAMILY,
    RepairError,
    WingetRepair,
    device_architecture,
    run_powershell,
)

failures: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(("ok  " if ok else "FAIL"), name, detail)
    if not ok:
        failures.append(name)


class StopBeforeInstalling(Exception):
    pass


def no_install(script: str, env=None, timeout: int = 300) -> str:
    """Real PowerShell for reading signatures. Anything that would change the PC stops here."""
    if "Add-AppxPackage" in script:
        if PACKAGE_FAMILY in script and "-RegisterByFamilyName" in script or "-Path" in script:
            raise StopBeforeInstalling(env)
        raise AssertionError(script)
    return run_powershell(script, env, timeout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    build = sys.getwindowsversion().build
    architecture = device_architecture()
    print(f"this PC: Windows build {build}, {architecture}")
    repair = WingetRepair(powershell=no_install)

    offer = repair.find_offer(build, architecture)
    check("a compatible version is found on the real GitHub", offer is not None, offer and offer.version)
    if offer is None:
        return 1
    print(f"     needs build {offer.min_build}, {offer.total_megabytes} MB to download")
    check("older Windows is told no version fits", repair.find_offer(10000, architecture) is None)
    check("every stable version found is for a real processor", repair.find_offer(build, "x86") is not None)

    print("App Installer on this PC:", repair.app_installer_version())

    for name, script in (
        ("activate", "Add-AppxPackage -RegisterByFamilyName -MainPackage WingetDeck.DoesNotExist_0000000000000"),
        ("install", "Add-AppxPackage -Path C:\\WingetDeck-does-not-exist.msixbundle"),
    ):
        try:
            run_powershell(script)
            check(f"{name} failure is reported", False)
        except RepairError as e:
            check(f"{name} failure reaches the user as readable text", bool(str(e)) and "\x1b" not in str(e), str(e)[:120])

    if args.download:
        seen: list[str] = []
        with tempfile.TemporaryDirectory(prefix="WingetDeck-check-") as folder:
            repair = WingetRepair(powershell=no_install, work_root=Path(folder))
            try:
                repair.download_and_install(offer, architecture, seen.append, threading.Event())
                check("the install step was reached", False)
            except StopBeforeInstalling as e:
                env = e.args[0]
                check("download, checksum, signature and identity all passed", True)
                check(
                    "the bundle and the dependencies for this processor would be installed",
                    env["WINGETDECK_BUNDLE"].endswith(".msixbundle") and bool(env["WINGETDECK_DEPENDENCIES"]),
                    env["WINGETDECK_DEPENDENCIES"].count("|") + 1,
                )
            except RepairError as e:
                check("download, checksum, signature and identity all passed", False, e)
            check("progress was shown", any("Downloading" in s for s in seen) and any("Checking" in s for s in seen))

    print("PASSED" if not failures else f"FAILED {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
