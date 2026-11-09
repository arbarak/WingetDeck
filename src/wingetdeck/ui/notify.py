"""A Windows notification when a long run ends. Best effort: it never stops anything if it fails."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable

from ..core.queue import Summary
from ..i18n import t

# The text comes in through the environment, so a package name can never become part of a command.
_SCRIPT = (
    "$m=[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime];"
    "$x=$m::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
    "$t=$x.GetElementsByTagName('text');"
    "$null=$t.Item(0).AppendChild($x.CreateTextNode('WingetDeck'));"
    "$null=$t.Item(1).AppendChild($x.CreateTextNode($env:WINGETDECK_NOTE));"
    "$n=[Windows.UI.Notifications.ToastNotification]::new($x);"
    "$m::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($n)"
)


def summary_text(summary: Summary) -> str:
    one = summary.restart_needed == 1
    restart = t("{count} needs a restart" if one else "{count} need a restart", count=summary.restart_needed)
    parts = [
        (summary.done, t("{count} upgraded", count=summary.done)),
        (summary.restart_needed, restart),
        (summary.skipped, t("{count} skipped", count=summary.skipped)),
        (summary.failed, t("{count} failed", count=summary.failed)),
        (summary.stopped, t("{count} stopped", count=summary.stopped)),
    ]
    return ", ".join(text for count, text in parts if count) or t("Nothing to do")


def notify_done(summary: Summary, spawn: Callable[..., object] = subprocess.Popen) -> bool:
    try:
        spawn(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _SCRIPT],
            env={**os.environ, "WINGETDECK_NOTE": summary_text(summary)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:  # noqa: BLE001 - a notification must never end a run
        return False
    return True
