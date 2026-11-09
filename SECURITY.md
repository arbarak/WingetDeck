# Security

WingetDeck starts installers on your PC, so security reports are very welcome.

## Reporting a problem

Please do not open a public issue. Use **Report a vulnerability** on the
[Security tab](https://github.com/arbarak/WingetDeck/security/advisories/new), which stays private until a fix is ready.
Say what you did, what happened, and which version you used.

Only the latest release gets fixes.

## What matters most

- Anything that makes the app install something you did not tick.
- Anything in a folder a normal user can write to that can influence a run as administrator.
- Secrets or personal details left in a diagnostic report.
- Changes to winget's settings beyond the one opt-in key, `network.downloader`.
- A process left frozen, or an unrelated process stopped.
- Any way to make Get winget install something that did not come from Microsoft.

## What the app does

- Winget downloads every upgrade. The app's own network code runs only when you press Get winget and agree, and it goes
  only to GitHub over HTTPS, refusing a redirect anywhere else.
- Get winget installs nothing unless the files match GitHub's checksums, each has a valid Microsoft signature, and the
  package is App Installer. Windows checks the signature again when it installs. PowerShell is started by its full path,
  and file names reach it through variables, so they cannot become code.
- It sends no data anywhere. Logs stay in its data folder until you share them.
- When running as administrator, it ignores the folder beside the exe and uses your profile folder.
- It finds winget on the PATH or in Windows' own folder for it, and never runs a `winget.exe` from the current folder.
- Winget's arguments are passed as a list, with no shell, and package ids from saved files are checked before use.

## Checking a download

The exes are not code-signed yet, so Windows SmartScreen may warn about them. Each release lists SHA-256 checksums in
`SHA256SUMS.txt`. To check a file:

```powershell
Get-FileHash .\WingetDeck-1.0.3-x64.exe -Algorithm SHA256
```
