# What has been tested, on what

Version 1.0.0, 9 November 2026. "Supported" in the design means the app targets a system. This page says what has
actually been run.

## The one test machine

Windows 11 Pro 23H2 (build 22631), x64, en-US, winget v1.29.380. Windows Sandbox runs the same Windows build, so it
proves nothing about other Windows versions.

## Not yet done

**The biggest gap: no real package has been upgraded by the finished exe yet.** The whole upgrade flow has only run
against the pretend winget in tests.

| Not done | Why | What it would prove |
|---|---|---|
| A real upgrade with the finished exe, with Pause, Resume, Stop now | Sandbox needs about 10 GB free and C: has about 2 GB; a real upgrade on the owner's PC needs their yes | That the pieces below work together for real |
| U2: long freezes during a download | Same | Whether a server drops a download frozen for many minutes, and whether winget then fails cleanly |
| Default-downloader control in Sandbox | Same; the first attempt froze the source update rather than a download, so it was not valid | Confirms the host measurement in a clean system |
| Exe in a clean Sandbox | Same | `scripts/portable_check.py` hides Python from the exe on the owner's PC, which is close but not a PC that never had it |
| Windows 10, Server 2019/2022/2025, LTSC | No such machine or VM | Anything at all on those systems |
| ARM64 | No machine, and no native exe | The x64 exe under emulation, or running from source |
| Non-English Windows | Not tried | Parsing rests on column positions and saved samples only |
| Dragging a real window edge, maximise and minimise, by hand | Kept off the owner's desktop | Resizing was tested in a real pseudo console instead (below) |
| Windows Terminal and classic console, seen by eye | Same | Mouse clicks in the classic console in particular |
| The taskbar progress colour | Only the code sent was checked | That the terminal shows it |
| The Windows notification appearing | The script was run up to the point of showing it, so nothing popped up | That it appears |
| Long unattended runs, real installer prompts | Not tried | |
| A PC that has never accepted winget's source agreements | The owner's PC accepted them long ago | The app asks and scans again; this was tested against a pretend refusal, and the code comes from winget's table |
| Agreement links before a download | No real package with agreements captured; written from the reviewer's reading of winget's output | Live progress for those packages |
| What quitting during a real install does | Needs a real upgrade | The reviewer showed winget dies with the app, using a test child process, not a real install |

## Done

### Automated suite

`.venv\Scripts\python -m pytest` on the owner's PC, using a pretend winget unless noted: 465 passed at v1.0.0. A test
marked `real` reads the real winget (passed) and one marked `real_download` downloads a package; both run only on
request, and `real_download` was not rerun on the final code.

### Measured with real winget

| What | Where | Result |
|---|---|---|
| Piped winget shows no progress; a pseudo console shows live bars | Owner's PC | Confirmed, spec F1 to F3 |
| Default downloader: freezing or killing winget does not stop the transfer | Owner's PC | Confirmed: about 27 MB/s kept going in a Windows service |
| Direct downloader: freeze stops the network, thaw resumes, kill stops it, full download exits 0 | Sandbox | Confirmed: 47 MB/s to 0 in about 1 s. A 94 MB partial file stays after kill |
| Nullsoft, MSI and portable installers in a pseudo console | Sandbox | All exit 0 |

See `docs/spikes/2026-11-09-sandbox-results.md`. These tested winget itself, before the app was finished.

### The built exes

Each was run on the owner's PC, in a pseudo console with no window on the desktop. Final builds:
`dist\2026-11-09\140546\WingetDeck-x64.exe` and `dist\2026-11-09\140632\WingetDeck-x86.exe`.

| Check | x64 | x86 |
|---|---|---|
| `--version` from a path with spaces and non-English letters, with Python hidden | Pass | Pass |
| Demo through to the package table, then a clean quit | Pass | Pass |
| `WingetDeck-data` appears beside the exe | Pass | Pass |
| Read-only folder (permissions denied): runs, and data goes to the profile folder | Pass | Pass |
| Real terminal driver through 7 window sizes, with the too-small message | Pass | Pass |
| **Real winget, scan only:** real version shown, real upgrades listed, resized, clean quit, no crash log | Pass (2 upgrades found) | Pass |
| Session log reports live progress | Yes | No, as intended |

Upgrade was never pressed in any of these.

### Other direct checks

- QuickEdit is turned off and restored afterwards on a real hidden console, including after a crash and with Textual's
  own console changes in between.
- With `--ascii`, every character sent to a real pseudo console was checked to be plain ASCII.

## Known limits

- x86 has no live numbers, only an animation and the elapsed time.
- The exe is not signed, so SmartScreen may warn.
- Ending the app from Task Manager while a download is frozen cannot unfreeze winget.
- A custom installer argument containing spaces can slip past the diagnostic report's secret removal. Read a report
  before sharing it.
