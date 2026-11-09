# What has been tested, on what

Version 1.0.2, 9 November 2026. "Supported" in the design means the app targets a system. This page says what has
actually been run.

## The test machines

**Main machine:** Windows 11 Pro 23H2 (build 22631), x64, en-US, winget v1.29.380. Windows Sandbox runs the same Windows
build, so it proves nothing about other Windows versions.

**Second PC:** Windows 10 (build 19045), x64, fr-FR, classic console with Consolas, winget v1.29.380. Version 1.0.0 was
opened there, which is how the problems fixed in 1.0.1 were found. Version 1.0.1 then did real upgrades there, which found
the problems fixed in 1.0.2. Version 1.0.2 has not been run there yet.

## Not yet done

**The biggest gaps: Resume, Stop now and a Pause in the middle of a download have not been used in a real upgrade.** Pause
and Stop between packages have (see "Real upgrades on the second PC" below).

| Not done | Why | What it would prove |
|---|---|---|
| A real upgrade with the finished exe, with Pause, Resume, Stop now | Sandbox needs about 10 GB free and C: has about 2 GB; the one upgrade on the owner's PC ran without them | That the pieces below work together for real |
| A real upgrade with the x86 exe | Same | The x86 path without a pseudo console |
| U2: long freezes during a download | Same | Whether a server drops a download frozen for many minutes, and whether winget then fails cleanly |
| Default-downloader control in Sandbox | Same; the first attempt froze the source update rather than a download, so it was not valid | Confirms the host measurement in a clean system |
| Exe in a clean Sandbox | Same | `scripts/portable_check.py` hides Python from the exe on the owner's PC, which is close but not a PC that never had it |
| Version 1.0.1 on Windows 10 | Not yet tried on the second PC | That the fixes hold there. Windows 10 and 11 fill in missing symbols differently, so the checks below cannot fully stand in for it |
| **Get winget really activating or installing winget** | This PC already has winget, and these steps change the PC | That Windows accepts the install, that a fresh account gets working winget, and sideloading on older Windows 10. Everything before that last step has run for real (below) |
| Windows Server 2019/2022/2025, LTSC | No such machine or VM | Anything at all on those systems |
| ARM64 | No machine, and no native exe | The x64 exe under emulation, or running from source |
| Non-English Windows | Not tried | Parsing rests on column positions and saved samples only |
| Dragging a real window edge and minimising, by hand | Not tried | Resizing was tested in a real pseudo console instead (below) |
| Version 1.0.1 in Windows Terminal, seen by eye | Not done in this round | Windows Terminal keeps the full symbols, and the automatic tests cover that path |
| The taskbar progress colour | Only the code sent was checked | That the terminal shows it |
| The Windows notification appearing | The script was run up to the point of showing it, so nothing popped up | That it appears |
| Long unattended runs, real installer prompts | Not tried | |
| A PC that has never accepted winget's source agreements | The owner's PC accepted them long ago | The app asks and scans again; this was tested against a pretend refusal, and the code comes from winget's table |
| Agreement links before a download | No real package with agreements captured; written from the reviewer's reading of winget's output | Live progress for those packages |
| What quitting during a real install does | Needs a real upgrade | The reviewer showed winget dies with the app, using a test child process, not a real install |

## Done

### Automated suite

`.venv\Scripts\python -m pytest` on the owner's PC, using a pretend winget unless noted: 653 passed at v1.0.2. A test
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

Each was run on the owner's PC, in a pseudo console with no window on the desktop. Version 1.0.1 builds:
`dist\2026-11-09\162720\WingetDeck-x64.exe` and `dist\2026-11-09\162808\WingetDeck-x86.exe`.

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

### One real upgrade

On 9 November 2026 the version 1.0.0 x64 exe upgraded one package on the owner's PC, wkhtmltox (`wkhtmltopdf.wkhtmltox`), driven
through a pseudo console by the keys a person would press. The default downloader was in use, and the licence question
was answered "Skip those packages".

| What | Result |
|---|---|
| Only the ticked package was requested | Yes, by the session log |
| Snapshot of installed versions saved before the run | Yes |
| Live download progress from winget | Yes, 26.6 MB |
| Installer hash checked by winget, then the install | Yes; the app's folder in Program Files was rewritten at the time of the run |
| Winget's result | `0x00000000`, reported as Upgraded, 11 seconds |
| App exit and crash logs | Exit code 0, no crash log |

This package does not tell Windows its version, so winget still shows it as `Unknown` and offers it again after the
upgrade. That is how this package behaves, and it means the upgrade did not show a new version number. A package that
reports its version has not yet been upgraded by the exe.

### Real upgrades on the second PC

Version 1.0.1, from its logs, on the French Windows 10 PC above. The logs do not show how the screens looked.

| What was done | What happened |
|---|---|
| Scan with winget speaking French | Read 13 upgrades. Each later scan agreed with what had been upgraded |
| Rustup, Notepad++, 7-Zip and Laragon upgraded | All reported Upgraded, and all left the list. The saved lists confirm the new versions of the first two |
| OBS Studio, twice | Its installer refused because files were in use. Shown as in use, not as upgraded, with winget's code |
| Administrator prompts from installers | Answered on the PC, with the app itself not elevated |
| A run of 10 packages | 7-Zip finished and Laragon was running |
| Pause during Laragon | Laragon finished, and the next package did not start |
| Stop while paused | The 8 packages left were marked stopped and not started. No saved queue stayed behind |
| Text in the transcripts | No damaged characters, accents included |

It found three faults, all fixed in 1.0.2: Refresh sources failing after the agreements were accepted, stages not understood
in French, and a second press of Upgrade while the first was saving its list. The first fix was then run against real winget
on the main machine, and the second replays a real French transcript from that PC. Not used there: Resume, Stop now, Force
stop, a Pause in the middle of a download, and the details page.

### The classic Windows console

Windows 10 opens the exe in the classic console, and Windows 11 normally does not, which is why 1.0.0's problems were
missed. These checks open that real console on Windows 11, using `conhost.exe`, with the demo. Each screen was looked at
in a screenshot.

| Setup | Exe | Screens | Result |
|---|---|---|---|
| Consolas | x64 | Start, table, details, filter, settings, logs, history, palette, licence, downloading, installing, paused, stop, quit, resume | No boxes, no stray cursor, no scrollbars |
| Lucida Console | x64 | Start, table, details, settings, palette, downloading, paused, stop, quit, resume | Same |
| Courier New | x64 | Table, downloading | Same |
| Terminal (old raster font) | x64 | Start, table, downloading | Switches to plain text, as intended |
| `--ascii` | x64 | Start, table, downloading | Plain text only |
| Maximised | x64 | Table, settings, downloading, filter | Same, and long IDs show in full |
| Consolas | x86 | Start, table, downloading, paused, stop | Same |
| Consolas, real winget, scan only | x64, x86 | Table | Real upgrades listed |
| Mouse clicks, demo | x64 | Tick a row, press UPGRADE, finish a run | All work. The clicks were sent as window messages, not by a physical mouse |

The window checks used a build from just before the winget lookup fixes, which change no screen. The Consolas row with
all the screens came from a build before the footer and Settings layout fixes, and its table, settings and downloading
screens were then checked again. This console's own font list was measured with Windows'
font functions: Consolas lacks 27 of the symbols the app can use, Lucida Console 40 and Courier New 39.

An automatic test also walks every screen in a real pseudo console, reads every character the app sends, and checks each
against the real fonts. Those three fonts are what it checks; a console set to some other font is handled by the same
check when the app runs, but has not been looked at.

### A PC without winget, simulated

Both final exes ran in a pseudo console with the real winget hidden, by giving them a PATH without its folder. A copy of
the exe stood in for winget, because it answers `--version`. The previous build failed the two checks marked below, which
shows the test can catch them.

| Check | x64 | x86 |
|---|---|---|
| No winget: the help screen appears, with no crash | Pass | Pass |
| A `winget.exe` in the current folder is not run (previous build ran it) | Pass | Pass |
| Check again with still no winget: the help screen again | Pass | Pass |
| Check again after winget appears: it is found and run (previous build did not find it) | Pass | Pass |

The same simulated PC, with the stand-in reporting a version too old, then pressed Get winget on the final exes: both
reached the real GitHub, including its HTTPS certificates from inside the exe, and showed the offer for the real latest
version. It was declined there.

### Get winget, against the real services

`scripts/repair_check.py --download` on the main machine, with the install and activate commands blocked:

| Check | Result |
|---|---|
| Finds the newest stable version on the real GitHub, and reads its minimum Windows build from the package, using about 30 KB | v1.29.380, build 17763 |
| Says nothing fits on a Windows build older than that | Yes |
| Downloads all 300 MB and checks GitHub's SHA-256 checksums | Pass |
| Microsoft's signature on the real package and its 3 dependencies, read by Windows | Valid |
| The package's name and publisher | App Installer, Microsoft |
| Windows' error for a package or file that does not exist reaches the user as readable text | Yes |
| The temporary files are removed afterwards | Yes |

The screens and every failure, such as a bad checksum, a wrong signature, a redirect to another site, no internet and a
full disk, are covered by automatic tests against a pretend GitHub and a pretend Windows.

No PC that really lacks winget has been tried. Nor has a PC where App Installer is present but not yet set up for the
user, or one that has never accepted winget's source agreements.

### Other direct checks

- QuickEdit is turned off and restored afterwards on a real hidden console, including after a crash and with Textual's
  own console changes in between.
- With `--ascii`, every character sent to a real pseudo console was checked to be plain ASCII.

## Known limits

- x86 has no live numbers, only an animation and the elapsed time.
- Get winget depends on Windows allowing the install. Policy, or sideloading being off on an older Windows 10, can refuse it,
  and the app then shows Windows' message and offers the Microsoft Store.
- The classic console has fewer symbols, so its bars and icons are a little blockier than in Windows Terminal.
- The exe is not signed, so SmartScreen may warn.
- Ending the app from Task Manager while a download is frozen cannot unfreeze winget.
- A custom installer argument containing spaces can slip past the diagnostic report's secret removal. Read a report
  before sharing it.
