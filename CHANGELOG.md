# Changelog

Found a problem that is not listed here?
[Report it](https://github.com/arbarak/WingetDeck/issues/new/choose) and it can be fixed in the next release.

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
