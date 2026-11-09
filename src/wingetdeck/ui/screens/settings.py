"""Settings: language, run defaults, look, timers, the direct downloader's Undo, log size and cleanup."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from ... import i18n
from ...core.queue import RunState
from ...i18n import LANGUAGES, N_, t
from ...core.safety import restart_as_admin
from ...paths import is_elevated
from ...winget.backend import UpgradeOptions
from ...winget.settings_file import DownloaderChange
from ..themes import THEMES
from ..widgets.options_form import OptionsForm
from .dialogs import ConfirmDialog
from .base import DeckScreen, Footer, TitleBar

_MB = 1024 * 1024
_LARGE_LOGS_MB = 500
_DELETE = N_("Delete old logs")
_AUTOMATIC = ""


@dataclass(frozen=True)
class Draft:
    """What the page showed, saved or not, so a change of language does not lose what was typed."""

    defaults: UpgradeOptions
    theme: str
    stall: str
    auto_check: str
    consent: bool
    restore_point: bool


class SettingsScreen(DeckScreen):
    BINDINGS = [Binding("escape", "app.pop_screen", N_("Back"))]

    def __init__(self, draft: Draft | None = None) -> None:
        super().__init__()
        self.draft = draft

    def compose(self) -> ComposeResult:
        s = self.app.store.load_settings()
        d = self.draft or Draft(
            s.defaults, s.theme, str(s.stall_minutes), str(s.auto_check_minutes or ""),
            s.consented_agreements, s.create_restore_point,
        )
        yield TitleBar()
        with VerticalScroll(id="settings-body"):
            yield Static(t("This app"), classes="form-title")
            with Horizontal(classes="form-row"):
                yield Label("Language" if i18n.current() == "en" else f"{t('Language')} (Language)", classes="form-label")
                yield Select(self._languages(), value=s.language if s.language in LANGUAGES else _AUTOMATIC,
                             allow_blank=False, id="language")
            with Horizontal(classes="form-row"):
                yield Label(t("Theme"), classes="form-label")
                names = [(theme.name.replace("wingetdeck-", "").title(), theme.name) for theme in THEMES]
                value = d.theme if d.theme in [n for _, n in names] else names[0][1]
                yield Select(names, value=value, allow_blank=False, id="theme")
            with Horizontal(classes="form-row"):
                yield Label(t("Warn after no output (minutes)"), classes="form-label")
                yield Input(d.stall, id="stall-minutes")
            with Horizontal(classes="form-row"):
                yield Label(t("Check for upgrades every (minutes, empty is off)"), classes="form-label")
                yield Input(d.auto_check, id="auto-check")
            yield Checkbox(t("Accept package and source agreements automatically"), d.consent, id="consent")
            yield Checkbox(t("Create a restore point before a run (administrator only)"), d.restore_point,
                           id="restore-point")
            yield Static(t("Upgrade options for every package"), classes="form-title")
            yield OptionsForm(d.defaults, id="defaults")
            yield Static(t("Winget's direct downloader"), classes="form-title")
            yield Static("", id="direct-status", markup=False)
            yield Button(t("Undo the direct downloader change"), id="undo-direct", classes="gray")
            yield Static(t("Administrator"), classes="form-title")
            yield Static(
                t(
                    "Without administrator rights each installer may ask for permission itself. "
                    "An administrator copy uses your profile folder for its data, not the folder beside the exe."
                ),
                markup=False,
            )
            yield Button(t("Restart as administrator"), id="restart-admin", classes="gray")
            yield Static(t("Ignored packages"), classes="form-title")
            yield Static("", id="ignored-list", markup=False)
            yield Button(t("Show ignored packages again"), id="clear-ignored", classes="gray")
            yield Static(t("Logs"), classes="form-title")
            yield Static("", id="log-size", markup=False)
            yield Button(t("Clean up old logs…"), id="cleanup", classes="red")
        with Horizontal(id="settings-actions"):
            yield Button(t("Save"), id="save-settings")
            yield Static("", id="settings-note", markup=False)
        yield Footer()

    def fresh(self) -> DeckScreen:
        return SettingsScreen(self._draft())

    def _languages(self) -> list[tuple[str, str]]:
        system = i18n.choose(_AUTOMATIC, self.app.system_language())
        automatic = t("Automatic ({language})", language=LANGUAGES[system])
        return [(automatic, _AUTOMATIC), *[(name, code) for code, name in LANGUAGES.items()]]

    def _draft(self) -> Draft:
        return Draft(
            self.query_one(OptionsForm).value(),
            str(self.query_one("#theme", Select).value),
            self.query_one("#stall-minutes", Input).value,
            self.query_one("#auto-check", Input).value,
            self.query_one("#consent", Checkbox).value,
            self.query_one("#restore-point", Checkbox).value,
        )

    @on(Select.Changed, "#language")
    def _language_changed(self, event: Select.Changed) -> None:
        """Applies at once and is saved at once, whatever else on the page is still unsaved."""
        app = self.app
        setting = str(event.value)
        settings = app.store.load_settings()
        if setting == settings.language:
            return
        app.store.save_settings(replace(settings, language=setting))
        before = i18n.current()
        app.apply_language(setting)
        if i18n.current() != before:
            app.call_later(self._redraw)

    async def _redraw(self) -> None:
        if self.app.screen is not self:
            return
        fresh = SettingsScreen(self._draft())
        await self.app.switch_screen(fresh)
        fresh.query_one("#language", Select).focus()
        fresh.note_language()

    def note_language(self) -> None:
        self._note(t("Language changed. It is saved already: the rest of this page still needs Save."))

    def on_mount(self) -> None:
        self._show_direct()
        self._show_ignored()
        self._show_size()
        button = self.query_one("#restart-admin", Button)
        button.display = not is_elevated()
        button.disabled = self.app.runner.view.state in (RunState.RUNNING, RunState.PAUSED)
        if button.disabled:
            button.tooltip = t("Not available during an upgrade run.")

    def _note(self, text: str) -> None:
        self.query_one("#settings-note", Static).update(text)

    def _show_direct(self) -> None:
        s = self.app.store.load_settings()
        caps = self.app.backend.capabilities()
        on = bool(caps and caps.direct_downloader) or s.moved_downloader is not None
        if caps and caps.settings_locked:
            text = t("Winget's settings are locked by your organisation, so this cannot be changed.")
        elif on:
            text = t("It is on. Pause can hold a download, and Delivery Optimization is not used for any winget download.")
        else:
            text = t("It is off. Pause waits until the current package has finished.")
        self.query_one("#direct-status", Static).update(text)
        self.query_one("#undo-direct", Button).disabled = s.moved_downloader is None

    def _show_ignored(self) -> None:
        ignored = sorted(self.app.store.load_settings().ignored)
        self.query_one("#ignored-list", Static).update(", ".join(ignored) if ignored else t("None"))
        self.query_one("#clear-ignored", Button).disabled = not ignored

    def _show_size(self) -> None:
        size = self.app.log_file.total_size_bytes() / _MB
        folder = self.app.log_file.data_dir.logs
        text = t("Logs use {size} MB in {folder}. Nothing is deleted automatically.", size=f"{size:.0f}", folder=folder)
        if size > _LARGE_LOGS_MB:
            text = t(
                "Logs have grown large: {size} MB in {folder}. Clean up below if you wish.", size=f"{size:.0f}", folder=folder
            )
        self.query_one("#log-size", Static).update(text)

    def _number(self, widget_id: str, blank_allowed: bool) -> int | None:
        text = self.query_one(widget_id, Input).value.strip()
        if not text and blank_allowed:
            return None
        value = int(text)
        if value <= 0:
            raise ValueError(text)
        return value

    def _save(self) -> None:
        app = self.app
        try:
            stall = self._number("#stall-minutes", blank_allowed=False)
            auto = self._number("#auto-check", blank_allowed=True)
        except ValueError:
            self._note(t("Please enter a whole number of minutes, above zero."))
            return
        theme = self.query_one("#theme", Select).value
        consent = self.query_one("#consent", Checkbox).value
        settings = replace(
            app.store.load_settings(),
            defaults=self.query_one(OptionsForm).value(),
            theme=theme,
            stall_minutes=stall,
            auto_check_minutes=auto,
            consented_agreements=consent,
            asked_agreements=True,
            create_restore_point=self.query_one("#restore-point", Checkbox).value,
        )
        app.store.save_settings(settings)
        app.runner.set_stall_minutes(settings.stall_minutes)
        app.theme = theme
        app.backend.accept_source_agreements = consent
        app.log_file.info("Settings saved")
        self._note(t("Saved."))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "save-settings":
                self._save()
            case "undo-direct":
                self._undo_direct()
            case "clear-ignored":
                self._clear_ignored()
            case "cleanup":
                self._ask_cleanup()
            case "restart-admin":
                self._restart()

    def _restart(self) -> None:
        if restart_as_admin():
            self.app.log_file.info("Restarting as administrator")
            self.app.exit()
        else:
            self._note(t("Windows did not restart the app as administrator, so this copy stays open."))

    def _undo_direct(self) -> None:
        app = self.app
        settings = app.store.load_settings()
        stored = settings.moved_downloader
        if stored is None:
            return
        backup = stored.get("backup")
        change = DownloaderChange(stored["previous_existed"], stored["previous_value"], Path(backup) if backup else None)
        try:
            app.backend.undo_direct_downloader(change)
        except Exception as e:  # keep the record so Undo can be tried again
            app.log_file.error("Could not undo the downloader change", error=repr(e))
            self._note(t("Could not restore winget's settings: {error}", error=e))
            return
        app.store.save_settings(replace(settings, moved_downloader=None))
        self._note(t("Winget's settings are back as they were."))
        self._show_direct()

    def _clear_ignored(self) -> None:
        store = self.app.store
        store.save_settings(replace(store.load_settings(), ignored=set()))
        self._show_ignored()

    def _old_logs(self) -> list[Path]:
        log = self.app.log_file
        current = {p.resolve() for p in log.paths}
        return [p for p in log.data_dir.logs.iterdir() if p.is_file() and p.resolve() not in current]

    def _ask_cleanup(self) -> None:
        old = self._old_logs()
        text = t(
            "This deletes {count} old log file(s) from earlier sessions and cannot be undone. This session's logs stay.",
            count=len(old),
        )
        self.app.push_screen(ConfirmDialog(N_("Clean up old logs?"), text, (_DELETE,), danger=(_DELETE,)), self._cleanup)

    def _cleanup(self, choice: str | None) -> None:
        if choice != _DELETE:
            return
        removed = 0
        for path in self._old_logs():
            try:
                path.unlink()
                removed += 1
            except OSError as e:
                self.app.log_file.warn("Could not delete a log", path=str(path), error=repr(e))
        self.app.log_file.info("Old logs deleted", count=removed)
        self._show_size()
