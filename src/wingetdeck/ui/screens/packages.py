"""The package table, with Refresh, selection buttons and a short activity log."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Static

from ...core.queue import RunState
from ...core.runner import RunView
from ...core.selection import merge_scan
from ...winget.models import ChangeKind
from ..widgets.package_table import PackageTable

_REFRESH_BLOCKED = "Not available during an upgrade. It comes back when the run ends or pauses between packages."
_ACTIONS_HEIGHT = 3
_LOG_MIN = 4
_LOG_LINES = 200


def run_is_active(view: RunView) -> bool:
    """A run paused between packages is not active: nothing is happening."""
    if view.state is RunState.RUNNING:
        return True
    return view.state is RunState.PAUSED and view.active_name is not None


class PackagesScreen(Screen):
    BINDINGS = [
        Binding("f5", "refresh_list", "Refresh"),
        Binding("r", "refresh_list", "Refresh", show=False),
        Binding("slash", "filter", "Filter"),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        Binding("u", "upgrade", "Upgrade"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, source: str | None) -> None:
        super().__init__()
        self.source = source
        self.auto_check_timer = None
        self._seen: set[str] = set()
        self._first_scan = True
        self._scanning = False
        self._log_lines: list[str] = []
        self._run_was_active = False

    def compose(self) -> ComposeResult:
        ascii_mode = self.app.ascii_mode
        yield Header(show_clock=True, icon="○")
        with Vertical(id="packages-body"):
            yield Input(placeholder="Type to filter, Esc to clear", id="filter")
            yield PackageTable(ascii_mode=ascii_mode, id="table")
            yield Static("", id="empty", markup=False)
            with Horizontal(id="table-actions"):
                yield Button("Refresh" if ascii_mode else "↻ Refresh", id="refresh", classes="blue")
                yield Button("All", id="select-all", classes="gray")
                yield Button("None", id="select-none", classes="gray")
                yield Button("Major", id="select-major", classes="gray small-hide")
                yield Button("Minor", id="select-minor", classes="gray small-hide")
                yield Button("Patch", id="select-patch", classes="gray small-hide")
                yield Static("", id="actions-gap")
                yield Button("Back to the run", id="to-run", classes="gray")
                yield Button("UPGRADE", id="upgrade", disabled=True)
            with VerticalScroll(id="table-log-box"):
                yield Static("", id="table-log")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#filter", Input).display = False
        self.query_one("#empty", Static).display = False
        self.query_one("#to-run", Button).display = False
        settings = self.app.store.load_settings()
        self.query_one(PackageTable).include_pinned = settings.defaults.include_pinned
        if settings.auto_check_minutes:
            self.auto_check_timer = self.set_interval(settings.auto_check_minutes * 60, self.auto_check)
        self.app.add_run_listener(self.on_run_view)
        self.on_run_view(self.app.runner.view)
        self.query_one(PackageTable).focus()
        self.scan_packages(update_sources=False)

    def on_unmount(self) -> None:
        self.app.remove_run_listener(self.on_run_view)

    # The log panel

    def _say(self, kind: str, text: str, safe: bool = False) -> None:
        marks = {
            "dot": "[$wd-lime]●[/]",
            "tree": "[$wd-dim]└─[/]",
            "bad": "[$error]✗[/]",
            "warn": "[$warning]![/]",
        }
        body = text if safe else escape(text)
        self._log_lines = [*self._log_lines, f"{marks[kind]} {body}"][-_LOG_LINES:]
        self.query_one("#table-log", Static).update("\n".join(self._log_lines))
        self.query_one("#table-log-box", VerticalScroll).scroll_end(animate=False)

    # Scanning

    @work(exclusive=True, group="scan")
    async def scan_packages(self, update_sources: bool) -> None:
        app = self.app
        refresh = self.query_one("#refresh", Button)
        self._scanning = True
        refresh.disabled = True
        try:
            if update_sources:
                self._say("dot", "Updating sources…")
                try:
                    await app.backend.update_sources()
                    self._say("tree", "sources updated")
                except Exception as e:  # a stale list is still worth showing
                    app.log_file.warn("Source update failed", error=repr(e))
                    self._say("warn", f"Could not update sources, the list may be out of date: {e}")
            self._say("dot", "Checking for upgrades…")
            table = self.query_one(PackageTable)
            try:
                result = await app.backend.scan(self.source, include_pinned=table.include_pinned)
            except Exception as e:  # shown in the panel, the current rows stay
                app.log_file.error("Scan failed", error=repr(e))
                self._say("bad", f"Could not check for upgrades: {e}")
                return
            self._apply_scan(result, table)
        finally:
            self._scanning = False
            self._update_refresh()

    def _apply_scan(self, result, table: PackageTable) -> None:
        ignored = self.app.store.load_settings().ignored
        shown = [p for p in result.packages if p.id not in ignored]
        hidden = len(result.packages) - len(shown)
        merged = merge_scan(
            table.all_rows,
            type(result)(shown, result.unknown_hidden, result.notes),
            table.ticked,
            self._seen,
            first=self._first_scan,
        )
        self._first_scan = False
        self._seen |= {p.id for p in shown}
        table.set_rows(merged.rows, merged.ticked, merged.new_ids)
        self.app.log_file.info(
            "Scan finished",
            upgrades=len(merged.rows),
            new=sorted(merged.new_ids),
            gone=sorted(merged.gone_ids),
            ignored=hidden,
        )
        self._say("tree", f"{len(merged.rows)} upgrade(s) available")
        if merged.new_ids:
            self._say("tree", f"{len(merged.new_ids)} new since the last check")
        if merged.gone_ids:
            self._say("tree", f"{len(merged.gone_ids)} no longer need upgrading")
        if hidden:
            self._say("tree", f"{hidden} ignored package(s) hidden")
        if result.unknown_hidden:
            self._say("tree", f"{result.unknown_hidden} package(s) with an unknown version hidden by winget")
        self._show_rows_or_message()
        self.fit_table()

    def _show_rows_or_message(self) -> None:
        table = self.query_one(PackageTable)
        empty = self.query_one("#empty", Static)
        nothing = not table.all_rows
        table.display = not nothing
        empty.display = nothing
        if nothing:
            empty.update("Everything is up to date. Press Refresh to check again.")

    def fit_table(self) -> None:
        """Rows take what they need and the log gets the rest, until the rows need more room."""
        body = self.query_one("#packages-body")
        table = self.query_one(PackageTable)
        box = self.query_one("#table-log-box")
        spare = body.size.height - _ACTIONS_HEIGHT
        filter_box = self.query_one("#filter", Input)
        if filter_box.display:
            spare -= 3
        wanted = len(table.rows) + 1
        show_log = spare - min(wanted, 4) >= _LOG_MIN
        box.display = show_log
        room = spare - _LOG_MIN if show_log else spare
        table.styles.height = max(min(wanted, room), 2)

    def on_resize(self) -> None:
        self.fit_table()

    def auto_check(self) -> None:
        if self._scanning or run_is_active(self.app.runner.view):
            return
        self.scan_packages(update_sources=True)

    def _update_refresh(self) -> None:
        refresh = self.query_one("#refresh", Button)
        blocked = run_is_active(self.app.runner.view)
        refresh.disabled = blocked or self._scanning
        refresh.tooltip = _REFRESH_BLOCKED if blocked else "Update winget's sources, then check again"

    def on_run_view(self, view: RunView) -> None:
        if not self.query("#to-run"):
            return
        self._update_refresh()
        unfinished = view.state in (RunState.RUNNING, RunState.PAUSED)
        self.query_one("#to-run", Button).display = unfinished
        if unfinished:
            self._run_was_active = True
        elif self._run_was_active and view.state is RunState.FINISHED:
            self._run_was_active = False
            self.scan_packages(update_sources=False)

    # Controls

    @on(PackageTable.TicksChanged)
    def _ticks_changed(self) -> None:
        count = len(self.query_one(PackageTable).ticked)
        upgrade = self.query_one("#upgrade", Button)
        upgrade.label = f"UPGRADE ({count})" if count else "UPGRADE"
        upgrade.disabled = not count

    def on_button_pressed(self, event: Button.Pressed) -> None:
        table = self.query_one(PackageTable)
        match event.button.id:
            case "refresh":
                self.action_refresh_list()
            case "select-all":
                table.select_all()
            case "select-none":
                table.select_none()
            case "select-major":
                table.select_change(ChangeKind.MAJOR)
            case "select-minor":
                table.select_change(ChangeKind.MINOR)
            case "select-patch":
                table.select_change(ChangeKind.PATCH)
            case "upgrade":
                self.action_upgrade()
            case "to-run":
                self.app.show_progress()

    def action_refresh_list(self) -> None:
        if not self.query_one("#refresh", Button).disabled:
            self.scan_packages(update_sources=True)

    def action_filter(self) -> None:
        box = self.query_one("#filter", Input)
        box.display = True
        box.focus()
        self.fit_table()

    @on(Input.Changed, "#filter")
    def _filter_changed(self, event: Input.Changed) -> None:
        self.query_one(PackageTable).set_filter(event.value)
        self.fit_table()

    @on(Input.Submitted, "#filter")
    def _filter_done(self) -> None:
        self.query_one(PackageTable).focus()

    def action_select_all(self) -> None:
        self.query_one(PackageTable).select_all()

    def action_select_none(self) -> None:
        self.query_one(PackageTable).select_none()

    def action_upgrade(self) -> None:
        packages = self.query_one(PackageTable).ticked_packages()
        if packages:
            self.app.start_upgrade(packages)

    def action_back(self) -> None:
        box = self.query_one("#filter", Input)
        if box.display:
            box.value = ""
            box.display = False
            self.query_one(PackageTable).focus()
            self.fit_table()
        else:
            self.app.pop_screen()
