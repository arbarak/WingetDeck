# Changelog

Found a problem that is not listed here?
[Report it](https://github.com/arbarak/WingetDeck/issues/new/choose) and it can be fixed in the next release.

## 1.0.4, 9 November 2026

### Added

- **English or French.** Press `t` for Settings: Language is the first line. Pick English, Français or Automatic, and the
  screen changes straight away, with nothing to restart. Automatic follows the language Windows shows. Every screen,
  button, message and key hint is translated. Logs stay in English, and winget's own messages stay as winget writes
  them.
- Arabic was tried and is not offered: the Windows console has no right-to-left support, so Arabic words come out
  reversed.

### Fixed

- **The UPGRADE button now shows how many packages are ticked**, such as `UPGRADE (3)`. The count was always cut off.
- When the row of buttons under the table is too narrow for all of them, Major, Minor and Patch make room, so UPGRADE
  is never pushed out of the window.
- History shows `done, restart needed` instead of `done_restart`.

## 1.0.3, 9 November 2026

### Changed

- Downloads are named with the version and the processor type, such as `WingetDeck-1.0.3-x64.exe` and
  `WingetDeck-1.0.3-x86.exe`.

### Fixed

- **A strip down the right edge of the classic console** kept old colours after the window was resized or maximised. The
  console was keeping room for the scrollbar the app hides, and never drew there. The app now fills the whole window.
  Found on the Windows 10 PC.
- The log now records the window being closed with its X button, not only Quit.

## 1.0.2, 9 November 2026

### Added

- **Get winget**, for PCs where winget is missing, too old or not set up. It asks before each step:
  - It tries to activate a winget that is already on the PC, with nothing downloaded.
  - Otherwise it finds the newest stable winget made for this Windows build and processor, then offers to download and
    install it from Microsoft's official releases, showing the version and size first.
  - It installs nothing unless the checksum, Microsoft's signature and the package name all check out.
- **Microsoft Store** on the same screen opens App Installer's page.
- If App Installer is there but its `winget` command is off, the app says where to turn it on.

### Changed

- The app now has network code, used only by Get winget and only when you ask. It talks to GitHub alone.
- The app now understands winget in all 11 languages it ships, not only English: its stages and the details page.

### Fixed

Found by real upgrades on a second PC, with Windows 10 in French:

- **After accepting the agreements, Refresh sources always failed** with "Invalid command line arguments", so the list
  could be out of date. The next start would also have said the sources could not be listed. Both are fixed.
- **On Windows in another language, the app could not tell downloading from installing.** Stop offered Force stop and said
  an installer was running, even during a download, and Stop now and the mid-download Pause were never offered.
- Pressing Upgrade did nothing visible while the list of installed apps was saved, which took 9 seconds there, so it was
  easy to press again and save a second list. The app now says what it is doing, and ignores the second press.

Also fixed:

- Stop now checks that no installer is running before it ends anything, rather than relying on winget's words alone.
- Closing the app in the moment it was starting up could end in an error.
- Logs now mark a failed package as a warning, say when a Pause takes effect, and record the app closing.

## 1.0.1, 9 November 2026

These problems were found by running 1.0.0 on a second PC, with Windows 10. Double-clicking the exe there opens the
classic Windows console, whose fonts have far fewer symbols than Windows Terminal's.

### Fixed

| What you saw | What happens now |
|---|---|
| Empty boxes on buttons, on Refresh and Quit, on ticks and in the footer | The app checks the console's real font and draws the nearest symbol that font has |
| A cursor blinking in the top corner | The cursor is hidden |
| Scrollbars left at the edges of the window | They are hidden, and the console no longer offers to scroll |
| Long package IDs cut off, even in a full-screen window | IDs show in full whenever they fit |
| A wide empty gap after the package name | Spare width is shared between the columns |
| The last key in the footer cut off at the standard window size | All the keys fit. `Ctrl+P` still opens the palette on that screen |
| Settings checkboxes of different widths | They line up |

Also found while checking PCs without winget:

| What was wrong | What happens now |
|---|---|
| **Security:** a file called `winget.exe` in the folder the app was started from would be run in place of the real winget | The app never looks in the current folder for winget |
| Check again could not see a winget installed after the app started, despite saying no restart was needed | It looks again each time |
| A winget that was installed but missing from the PATH was reported as not installed | The app also looks where Windows keeps winget |
| A hung winget left the start screen waiting for up to 10 minutes | The app gives up after a minute and says why |

### Added

- `--basic` asks for the reduced symbols by hand, if your console shows boxes that the app did not catch.
- A [bug report form](https://github.com/arbarak/WingetDeck/issues/new/choose).

## 1.0.0, 9 November 2026

First release.
