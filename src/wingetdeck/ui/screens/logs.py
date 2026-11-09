"""Reading this session's log, the winget output for one package, and the diagnostic report."""

from __future__ import annotations

import getpass
import os
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, OptionList, RichLog, Select, Static
from textual.widgets.option_list import Option

from ...core.logs import LogEvent, report_contents, save_diagnostic_report
from ...winget.parse import strip_terminal_codes
from .dialogs import ConfirmDialog

_LEVELS = ("ALL", "INFO", "WARN", "ERROR")
_ALL_PACKAGES = "__all__"
_SAVE = "Save report"
_LEVEL_STYLES = {"INFO": "#7fb7ff", "WARN": "#ffd75f", "ERROR": "bold #ff5a5a", "DEBUG": "#8a8a8a"}


def winget_log_folder() -> Path | None:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    return Path(local) / "Packages" / "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe" / "LocalState" / "DiagOutputDir"


def _user_name() -> str:
    try:
        return getpass.getuser()
    except (OSError, KeyError, ImportError):
        return ""


class TranscriptScreen(Screen):
    """Everything winget printed for one package."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self, package_id: str, path: Path | None = None) -> None:
        super().__init__()
        self.package_id = package_id
        self.path = path

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, icon="○")
        yield Static(f"winget output for {self.package_id}", id="transcript-title", markup=False)
        yield RichLog(id="transcript", wrap=True, markup=False, highlight=False)
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one(RichLog)
        path = self.path or self.app.log_file.transcript_for(self.package_id)
        if path is None:
            log.write("There is no winget output for this package in this session.")
            return
        log.write(str(path))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            log.write(f"Could not read it: {e}")
            return
        for line in strip_terminal_codes(text).replace("\r", "\n").splitlines():
            if line.strip():
                log.write(line)


class LogsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self) -> None:
        super().__init__()
        self.level = "ALL"
        self.package: str | None = None
        self.shown: list[LogEvent] = []
        self._drawn: tuple = ()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, icon="○")
        with Horizontal(id="logs-top"):
            for level in _LEVELS:
                yield Button(level, id=f"level-{level}", classes="blue" if level == "ALL" else "gray", compact=True)
            yield Select([("All packages", _ALL_PACKAGES)], value=_ALL_PACKAGES, allow_blank=False, id="package")
            yield Button("Open logs folder", id="open-folder", classes="gray", compact=True)
            yield Button("Save diagnostic report", id="save-report", classes="gray", compact=True)
        yield Static(str(self.app.log_file.text_path), id="logs-path", markup=False)
        yield Static("", id="logs-note", markup=False)
        yield OptionList(id="log-events", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.redraw()
        self.set_interval(1.0, self.redraw)

    def _events(self) -> list[LogEvent]:
        level = None if self.level == "ALL" else self.level
        return self.app.log_file.events(level, self.package)

    def _update_packages(self, events: list[LogEvent]) -> None:
        names = sorted({e.package for e in events if e.package})
        select = self.query_one("#package", Select)
        wanted = (_ALL_PACKAGES, *names)
        if getattr(self, "_package_names", None) != wanted:
            self._package_names = wanted
            current = select.value
            select.set_options([("All packages", _ALL_PACKAGES), *[(n, n) for n in names]])
            select.value = current if current in wanted else _ALL_PACKAGES

    def redraw(self) -> None:
        self._update_packages(self.app.log_file.events())
        self.shown = self._events()
        signature = (self.level, self.package, len(self.shown))
        if signature == self._drawn:
            return
        self._drawn = signature
        listing = self.query_one(OptionList)
        keep = listing.highlighted
        listing.clear_options()
        listing.add_options([Option(self._line(e)) for e in self.shown])
        if keep is not None and self.shown:
            listing.highlighted = min(keep, len(self.shown) - 1)

    @staticmethod
    def _line(event: LogEvent) -> Text:
        text = Text(f"{event.time}  ", style="#8a8a8a")
        text.append(f"{event.level:<5} ", style=_LEVEL_STYLES.get(event.level, ""))
        if event.package:
            text.append(f"{event.package}  ", style="#00c8e8")
        text.append(event.message, style="not dim")
        if event.fields:
            text.append("  " + " ".join(f"{k}={v}" for k, v in event.fields.items()), style="#8a8a8a")
        if event.level == "ERROR" and event.package:
            text.append("  see details", style="underline #00c8e8")
        return text

    def open_event(self, index: int) -> None:
        if 0 <= index < len(self.shown) and self.shown[index].package:
            self.app.push_screen(TranscriptScreen(self.shown[index].package))

    @on(OptionList.OptionSelected, "#log-events")
    def _chosen(self, event: OptionList.OptionSelected) -> None:
        self.open_event(event.option_index)

    @on(Select.Changed, "#package")
    def _package_changed(self, event: Select.Changed) -> None:
        self.package = None if event.value == _ALL_PACKAGES else event.value
        self.redraw()

    def _set_level(self, level: str) -> None:
        self.level = level
        for name in _LEVELS:
            self.query_one(f"#level-{name}", Button).set_classes("blue" if name == level else "gray")
        self.redraw()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button.id or ""
        if button.startswith("level-"):
            self._set_level(button.removeprefix("level-"))
        elif button == "open-folder":
            self._open_folder()
        elif button == "save-report":
            self._ask_to_save()

    def _note(self, text: str) -> None:
        self.query_one("#logs-note", Static).update(text)

    def _open_folder(self) -> None:
        folder = str(self.app.log_file.data_dir.logs)
        try:
            os.startfile(folder)
        except OSError as e:
            self._note(f"Could not open {folder}: {e}")

    def _ask_to_save(self) -> None:
        contents = report_contents(self.app.log_file, winget_log_folder())
        text = (
            "The report is saved on this PC only. Your Windows user name, custom installer arguments, "
            "--header values and proxy passwords are removed.\n\nIt will contain:\n  "
            + "\n  ".join(contents)
        )
        self.app.push_screen(ConfirmDialog("Save a diagnostic report?", text, (_SAVE,)), self._save_answered)

    def _save_answered(self, choice: str | None) -> None:
        if choice == _SAVE:
            self._save_report()

    @work(group="report")
    async def _save_report(self) -> None:
        app = self.app
        try:
            info = await app.backend.info_text()
        except Exception as e:  # the report is most useful exactly when winget is misbehaving
            app.log_file.warn("winget --info failed", error=repr(e))
            info = f"winget --info failed: {e}"
        try:
            path = save_diagnostic_report(app.log_file, info, winget_log_folder(), _user_name())
        except OSError as e:
            app.log_file.error("Could not save the report", error=repr(e))
            self._note(f"Could not save the report: {e}")
            return
        app.log_file.info("Diagnostic report saved", path=str(path))
        self._note(f"Saved: {path}")
