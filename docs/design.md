# WingetDeck: design

Date: 2026-11-09. Working name, easy to change. Status: approved by the owner 2026-11-09, with a portable build ("go ahead please build portable version").

**Portable (owner's requirement):** the deliverable is one standalone exe that needs no installer, no admin rights and
no Python. Copy it anywhere and run it. Settings, saved queue, snapshots and logs go in a `WingetDeck-data` folder beside
the exe. If that location is not writable, such as Program Files or a read-only drive, fall back to
`%LOCALAPPDATA%\WingetDeck` and show which is in use. An elevated run always uses `%LOCALAPPDATA%\WingetDeck`, and
links or junctions are refused: another user could otherwise leave settings or a queue beside the exe that would then
drive installers as administrator. Any `%LOCALAPPDATA%\WingetDeck` path below means this data folder.
Winget itself must be present on the PC; it cannot be bundled.

## 1. What this is and why

A clickable, full-screen terminal app for upgrading Windows software through `winget`, with a pixel-art splash,
live table, tree-style log and single-item dashboard. The owner saw a clickable mock of this flow and approved the feel ("ohh sooo cool").

The owner asked for, in their words:

- "clickable for selection and button start"
- "pause and stop etc resume", "very advanced version"
- "compatible with all devices related to winget"
- a responsive window that can be minimised and maximised
- a "refresh button for any new" upgrades
- logs "for debugging any issues or errors" in future

## 2. Goals

1. See every available upgrade and choose them by clicking, or by keyboard.
2. Start, pause, resume and stop a run, and have those buttons be **true**: the screen never claims something
   that is not happening.
3. Stay usable at any window size, on every Windows version where winget itself can run.
4. Leave a clear trail so any future failure can be diagnosed afterwards.

## 3. Non-goals

- Searching for or installing new apps, or uninstalling (except rollback, section 7.8).
- Installing packages in parallel: Windows installers conflict, so the queue runs one package at a time.
- Linux or macOS (winget is Windows only).
- Other package managers such as Chocolatey or Scoop.
- A native non-terminal window. A terminal app is the look the owner approved.
- Telemetry or any network call of its own. The app only talks to winget.

## 4. Anti-goals: a failure even if everything else works

- A control that looks like it worked but did not (see section 6). This is the biggest risk in the project.
- Fake progress. If winget gives no number, show a "working" animation, never an invented percentage.
- Reporting success when an upgrade failed, or failure when it succeeded (see the codes in section 7.6).
- Leaving a program half-installed because the user pressed a normal Stop button.
- Upgrading anything the user did not explicitly tick and start.
- Copying another project's code or art. We write our own; the logo (a box and arrow) is original and stays that way.

## 5. Tested facts this design rests on

All measured on 2026-11-09 on the owner's PC: Windows 11 23H2 (build 22631) x64, en-US, winget v1.29.380.

| # | Fact | Evidence |
|---|---|---|
| F1 | Piped winget gives **no progress**, only finished lines. | `winget download` of a 28 MB package produced 6 lines and no percent or MB text |
| F2 | In a pseudo console (ConPTY via `pywinpty` 3.1.2) winget draws a live bar such as `██▉  223 MB /  494 MB`, one coloured character at a time, so it must be parsed from accumulated text with escape codes removed. | Spike on a 494 MB package |
| F3 | It also emits taskbar progress codes `ESC ] 9;4;<state>;<percent> ESC \`. They are sparse: 8 in about 14 s. | Same spike |
| F4 | By default the download runs in the **Delivery Optimization service**, not in winget. Freezing winget (`NtSuspendProcess`) stops the progress display but **not** the transfer. | Network stayed at 26-28 MB/s for 6 s while frozen |
| F5 | Killing the winget process tree does **not** stop that transfer either. The file reached 100% and a 495 MB `DO*.tmp` stayed in `%LOCALAPPDATA%\Temp\WinGet\<package>\`. | Network and `Get-DeliveryOptimizationStatus` |
| F6 | The owner's PC has no winget `settings.json` at present. | File not found in `LocalState` |
| F7 | `winget list` piped on this version did not truncate names or ids and is UTF-8: longest line was 195 bytes, with non-ASCII names intact. Older versions reportedly truncate at 120 columns, so truncation must still be handled. | Output file; Microsoft Q&A |
| F8 | `winget upgrade` columns: Name, Id, Version, Available, Source, with a dashed line under the header. Installed version can be `Unknown`. | Live output |
| F9 | `pywinpty` ships wheels for x64 and ARM64 but **not** x86. Textual is pure Python. PyInstaller supports x86, x64 and ARM64 but must build on each. | PyPI |
| F10 | The `Microsoft.WinGet.Client` PowerShell module is not installed on the owner's PC, so it cannot be assumed. | `Get-Module -ListAvailable` |
| F11 | Winget's own logs live in `%LOCALAPPDATA%\Packages\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalState\DiagOutputDir`. | `winget --info` |

**Not yet tested (must be settled before pause is built):**

- **U1.** With `network.downloader` set to `wininet`, do freeze and kill really stop the network? See section 6.2.

**Where these run (owner's decision):** in Windows Sandbox, which is enabled on the owner's PC, so their winget
settings and installed apps stay untouched. Winget must be installed inside it first. It also serves as the place
for throwaway-package install tests. If a Sandbox result could differ from a normal PC, say so instead of assuming.
- **U2.** How long can a download stay frozen before the server drops the connection, and does winget then fail
  cleanly? Only an 8 s freeze has been observed, and under the service downloader at that.
- **U3.** What does the install stage look like in a pseudo console, across installer types?

**Status at v1.0.0:** U1 answered yes, measured in Sandbox only (`docs/spikes/2026-11-09-sandbox-results.md`). U3 done:
nullsoft, MSI and portable all exit 0. **U2 not done**, and the Sandbox control for the default downloader is not valid,
because Sandbox filled the disk. `docs/TESTED.md` tracks both.

## 6. Pause, Stop and Resume

### 6.1 Rules for each stage

| Stage | Pause | Stop |
|---|---|---|
| Waiting, or between packages | Queue holds. Immediate. | Remaining items become Stopped. |
| Downloading, direct downloader on | Freeze winget's process tree. | Kill the tree. Item becomes Stopped. |
| Downloading, direct downloader off | Button reads "Pause after this package". `winget upgrade` runs download, hash check and install as one command, so there is no safe hold point after the download: the package finishes, including its install, then the queue holds. | "Stop after this one" lets the package finish. "Stop now" kills winget, so nothing gets installed, but the screen must say the background download may still run to the end and leave a temp file (F4, F5). |
| Installing | **Never freeze an installer.** Button reads "Pausing after this install…". | "Stop after this one" by default. A separate **Force stop** asks for confirmation and warns the app may be left broken. If the installer is elevated and cannot be killed, say so. |

Stop always offers two choices: **Stop after this one** and **Stop now**.

Resume continues a paused queue. If a frozen download has failed by the time of resuming (U2), retry that
package automatically once and log it.

### 6.2 The direct downloader (owner's decision pending)

A true mid-download pause appears to need the winget setting `network.downloader: wininet`. There is no
per-run flag for it, so it applies to all winget use on the PC. It is written from memory of the winget
documentation and is unverified until U1 runs. (U1 has since confirmed it, in Sandbox.)

- Off by default. The first time the user presses Pause during a download, explain the trade-off and offer to
  turn it on.
- Change only that one key, keep the rest of the file, and copy the previous file to a dated backup first.
- Settings has an "Undo" that restores the earlier value.
- If winget's settings are locked by policy, detect that and keep to the table's "off" behaviour.
- If U1 shows it does not work, the "off" behaviour becomes the only behaviour, and the owner must be told.

### 6.3 Resume after closing, crash or reboot

The queue is saved to disk after every state change. On next launch: "Resume unfinished queue (3 left)?".
An interrupted download starts again from zero; do not promise partial-file continuation.

## 7. Features

### 7.1 Splash
Pixel logo, source list (All sources, plus each source reported by `winget source list`), START and ✕. Shows
winget version and Windows build. If winget is missing or too old, show how to get it instead of crashing.

### 7.2 Package table
- Columns as in the mock: tick, Name, Id, Installed, Available, Source, Change.
- Change is major, minor, patch or unknown, colour coded. Non-numeric versions count as unknown.
- Click a row to tick; shift-click for a range. Click a header to sort, again to reverse.
- Select All, Select None, select by change type, `/` to filter as you type.
- Pinned packages are listed but not selectable unless "include pinned" is on.
- Details drawer from `winget show`: publisher, homepage, release notes.

### 7.3 Refresh
A visible **Refresh** button, plus `r` and `F5`.
- Forces `winget source update`, then rescans. A plain rescan could miss new versions because winget caches sources.
- Keeps ticks by package id. Marks packages not seen in the previous scan as **NEW**. Removes ones no longer upgradable.
- Unavailable during an active run, with a tooltip saying why. Available while the run is paused between packages.
- Optional auto-check every N minutes while idle, off by default.

### 7.4 Progress screen
As in the mock: package icon, speed and received meters, percent bar, stages (Download, Verify hash, Install,
Done), log panel, queue panel. Adds Pause/Resume and Stop buttons, and queue up/down and ✕ for items not yet started.
- Percent and sizes come from F2, using F3 as a fallback. Speed is calculated from those numbers.
- Install has no percent: show the animation and elapsed time.
- Stall warning if nothing changes for a configurable time (default 10 minutes). Warn only, never kill.

### 7.5 Run options
Global defaults, overridable per package: silent or interactive, scope, architecture, force, uninstall previous,
skip dependencies, include pinned, include unknown. Advanced: custom and override installer arguments.

Agreements: the first run explains that package and source licence agreements will be accepted through
`--accept-package-agreements` and `--accept-source-agreements`, and asks for consent. Without consent, packages
needing it are marked and skipped.

### 7.6 Results and errors
Plain-language reason for each failure, from winget's documented
[return codes](https://github.com/microsoft/winget-cli/blob/master/doc/windows/package-manager/winget/returnCodes.md).
Must-handle cases:

- `0x8A150109` REBOOT_REQUIRED_TO_FINISH: **success**, flagged "restart needed". Many tools get this wrong.
- `0x8A15010A` restart first, then retry.
- `0x8A15002B` no applicable upgrade: skipped, not failed.
- `0x8A15002C` some items in a bulk upgrade failed.
- Application in use: tell the user which app to close, and offer Retry. The user closes it. The app never closes another program, because that could lose unsaved work.

Retry Failed button. Summary screen at the end of the run.

### 7.7 Packages that can pull the rug out
Upgrading the terminal hosting the app, or App Installer (winget itself), can end the run. Move them to the end
of the queue with a warning, and rely on section 6.3 for recovery.

### 7.8 Safety
- Before each run, write a dated snapshot with `winget export --include-versions`.
- Best-effort **Roll back** from history: reinstall the earlier version if the source still has it. Say so plainly when it does not.
- Optional restore point when running as administrator.
- Ignore list, and pin/unpin through `winget pin`.

### 7.9 Comfort
Clickable footer, `Ctrl+P` palette, several themes (green dark default), `--demo` mode using a fake winget so the
whole app can be tried with nothing installed. Windows notification when an unattended run ends, best effort.

## 8. Diagnostic logs

Present from the first commit; every other part writes through it.

**Location:** `%LOCALAPPDATA%\WingetDeck\logs\`. Windows-native and writable without admin rights.

**Files** (new dated names; nothing is ever overwritten):
- `session_<stamp>.log`: readable timeline of every state change, button press, winget command line, exit code in hex with its meaning, and timing.
- `session_<stamp>.jsonl`: the same events in machine-readable form.
- `winget_<stamp>_<package-id>.log`: the full text of winget's output for that package, kept even on success.
- `crash_<stamp>.log`: any unhandled exception, with traceback and the last 200 events. The terminal must be restored and the path shown to the user, never a raw traceback on a broken screen.
- The session header records app version, Windows build, architecture, winget version, terminal, window size, locale, admin status, and whether the direct downloader is on.

**Inside the app:**
- A **Logs** screen to read and filter the current session by level and package.
- Errors in the run log show a "see details" link to that package's log.
- **Open logs folder** button.
- **Save diagnostic report**: a dated zip of the session's logs, `winget --info`, and the newest winget logs from F11, ready to attach to a bug report.
- `--debug` flag for verbose logging, including raw terminal output, escape codes and parsing decisions.
- Parser failures log the raw line that could not be read, so a new winget format can be fixed from the log alone.

**Privacy:** written locally only. The diagnostic report replaces the Windows user name in paths, and removes
values passed through `--header`, proxy credentials and custom installer arguments. Show what is included before saving.

**Retention:** logs are **never deleted automatically** (the owner's standing rule is to keep old files). Settings
shows the total size and warns above 500 MB. A cleanup button exists but always asks first.

## 9. Responsive window

Windows Terminal or the console provides the minimise, maximise and resize controls. The app must follow them live,
with no restart and without losing ticks, scroll position or running work.

| Width (columns) | Package table | Progress screen |
|---|---|---|
| 120 or more | All columns | Three-part header; log and queue side by side |
| 80 to 119 | Drops Id; Source narrows | Meters beside the percent bar; icon hidden |
| Under 80 | Tick, Name, Installed → Available only | Everything stacked; log and queue as tabs |

- Height: logo shrinks then disappears on short windows, and the log panel collapses before the table does.
- Below about 50×16: a "window too small" message. Work continues underneath.
- Maximised: extra space goes to names and the log, never to stretched empty columns.
- Minimised: the run continues. The window title shows progress, such as `3/7 · 42% · WingetDeck`, and the taskbar
  shows progress via `ESC ] 9;4` where the terminal supports it.
- Buttons remain large enough to click at every size, with key shortcuts always shown.

## 10. Device and system compatibility

| Target | Level | Notes |
|---|---|---|
| Windows 11; Windows 10 1809+ (build 17763); Server 2025 | **Supported** | Microsoft's stated support |
| Server 2019, 2022 | Best effort | Microsoft calls it experimental; works if winget is present |
| Windows LTSC | Best effort | Winget needs manual installation (community guides) |
| Server Core, or Windows older than 1809 | Not possible | Winget cannot run there. If the app does start, show a clear message. |
| x64 | Exe built here | Tested on the owner's PC |
| x86 | Exe built here, without live progress | F9: no `pywinpty` wheel, so it uses the piped fallback. Needs 32-bit Python installed for the build. |
| ARM64 | No native exe in this release | PyInstaller cannot cross-build and there is no ARM64 machine. Windows 11 ARM may run the x64 exe through emulation, and Python users can run from source (`pywinpty` has ARM64 wheels). Both untested. ARM64 winget support was also not confirmed by the sources found. |

Must work across differences, not just one machine:

- **Winget versions:** read flags from `--help` and `--version` rather than assuming. Handle truncated ids (F7) by resolving them against `winget export` or `winget list --id`.
- **Windows display languages:** read tables by the column positions of the dashed line and the header, never by header words. Stage text is translated, so a non-English system may show generic "Working" for a stage rather than break. Progress parsing relies on numbers and F3.
- **Wide characters:** column positions must account for double-width characters such as CJK names.
- **No pseudo console available:** fall back to piped mode with no live numbers. Everything else still works.
- **Terminals:** Windows Terminal and the classic console. Classic console QuickEdit mode can swallow mouse clicks, so turn it off while running and restore it on exit. Verify this directly.
- **Fonts and colours:** an ASCII fallback (`--ascii`, plus auto-detection where possible) for consoles that cannot draw the symbols.
- **Admin or not:** both work. Not elevated by default, so each installer may show its own UAC prompt. A "Restart as administrator" button reduces prompts. Winget launched under SYSTEM is out of scope.

"Supported" above means the app targets that system and winget officially runs there. It does not mean it has been
tested there. Tested status is tracked separately and published with each release.

**Honest limit (owner's decision: local only, no GitHub):** there are no remote test machines. The owner's PC and
Windows Sandbox only prove Windows 11 x64, because Sandbox uses the same Windows build as the host. Windows 10,
Server and ARM64 stay **untested** unless a machine or VM is added later (Windows 11 Pro has Hyper-V, so a Windows 10
VM is possible). A non-English language pack can be tried in Sandbox. The compatibility code is still written and
unit-tested with saved samples, and the README states exactly what was tested on what.

## 11. How it gets made (builder's call unless marked)

The builder's choices:
- Python 3.12, Textual 8.x, `pywinpty`, packaged by PyInstaller as a standalone exe per architecture, so nothing else needs installing.

Required separation:
- A **winget backend** behind an interface, with real and fake implementations. The UI never spawns processes directly.
- Parsers as pure functions tested against saved real output.
- A queue state machine (section 6) with no UI code, tested without running winget.

Left to the builder: module layout, file formats, theme set, exact key bindings, details of the details drawer.

## 12. Testing

- Unit tests for parsers using saved real output, including non-English samples and truncated rows, which should be collected early.
- Unit tests for every queue state transition, including pause and stop at each stage.
- UI tests with Textual's test driver in `--demo` mode: click every control, and resize through each band in section 9 with a run in progress.
- Spikes U1 to U3 happen before their dependent features are built.
- **Real upgrades on the owner's PC only with their explicit go-ahead.** Two are available: Microsoft.WSL and wkhtmltox. Upgrading WSL could disturb running Linux environments.

## 13. Project setup note

Exes are unsigned, so Windows SmartScreen may warn. The project began as a local repository and is now public on
GitHub; `SECURITY.md` covers how it is protected.
