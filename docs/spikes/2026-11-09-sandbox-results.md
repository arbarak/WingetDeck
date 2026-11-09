# Windows Sandbox results, 9 November 2026

Raw output was kept in `.sandbox/sandbox-out/u1` (`u1.json`, `u3.json`, transcripts).

DIRECT_DOWNLOADER_WORKS: yes (measured in Sandbox only)

## U1: does Pause stop the transfer with the direct downloader?

Yes, with `network.downloader: wininet`.

| Step | Result |
|---|---|
| Freeze during a real download | Network fell from about 47 MB/s to 0 within about 1 second |
| Thaw | Transfer continued |
| Kill | Network fell to 0 |
| Full download left to finish | Exit code 0 |
| Temp file after kill | One partial file with a hash name remains (94 MB) |

The screen must say that a partial file can be left behind after Stop.

## U1 control with the default downloader: not valid

The Sandbox control froze winget during its source update (bar `1024 KB / 3.73 MB`), not during a
package download, so it says nothing about the default downloader. It did show that source updates
draw progress bars too, which is why the stream ignores bars before the download line.

The default downloader result used by the app comes from the host measurement in the spec (F-facts):
freezing or killing winget left the transfer running at about 27 MB/s in the Delivery Optimization
service.

## U3: install types

Nullsoft (Notepad++), MSI (PuTTY, child `msiexec.exe`, which prints "Starting package uninstall..."
before installing) and portable (jq) all exited 0. Transcripts are in `tests/fixtures/pty_install_*.txt`.

## Not done

- **U2 (freezes of 1, 5 and 15 minutes) did not run.** The Sandbox filled drive C: to 588 KB free and
  was closed. Long freezes are untested: a server may drop a connection held idle that long. The app
  therefore keeps the retry-once rule after a resume.
- The valid default-downloader control in Sandbox.

Run both when the PC has about 10 GB free: `scripts/sandbox/make_wsb.py`, then `u2.py`.
