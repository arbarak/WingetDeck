"""The run: what is happening now, the controls, the log and the queue."""

from __future__ import annotations

import time
from dataclasses import asdict, replace

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, RichLog, Static

from ...core.queue import ItemState, RunState
from ...core.runner import RunView
from ...winget.models import Stage
from ..pixels import BOX, PixelArt
from ..widgets.meters import Meter, PercentBar, StageList, clock
from ..widgets.queue_panel import QueuePanel
from .dialogs import ConfirmDialog

STOP_AFTER = "Stop after this one"
STOP_NOW = "Stop now"
FORCE_STOP = "Force stop"
STOP_PLAIN = "Stop"
_TURN_ON = "Turn it on"
_SAMPLE_SECONDS = 0.5
_ANIMATION_SECONDS = 0.15
_CHIPS = {
    Stage.DOWNLOADING: "DOWNLOADING",
    Stage.VERIFYING: "VERIFYING",
    Stage.INSTALLING: "INSTALLING",
    Stage.WORKING: "WORKING",
}
_ICON_PALETTE = {"#": "#00c8e8", "+": "#0a6fdc"}
_ICON_DONE = {"#": "#66dd00", "+": "#3c8a00"}

_OFFER = (
    "This download cannot be held right now. Windows' download service carries it on even if winget "
    "is frozen, so a true Pause needs winget's direct downloader.\n\n"
    "Turning it on changes one winget setting (network.downloader) for all winget use on this PC, "
    "not only here. Delivery Optimization will not be used, so large downloads may be slower. "
    "Your settings file is backed up first, and Settings has an Undo.\n\n"
    "It applies from the next package. This one will pause when it has finished."
)


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


class ProgressScreen(Screen):
    AUTO_FOCUS = "#pause"
    BINDINGS = [
        Binding("p", "pause_resume", "Pause/Resume"),
        Binding("s", "stop", "Stop"),
        Binding("b", "back", "Packages"),
        Binding("escape", "back", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._seen_output = 0
        self._last_sample = 0.0
        self._notice = ""
        self._icon_done = False

    def compose(self) -> ComposeResult:
        ascii_mode = self.app.ascii_mode
        yield Header(show_clock=True, icon="○")
        with Horizontal(id="run-top"):
            yield Button("< Packages" if ascii_mode else "‹ Packages", id="back", classes="gray")
            yield Static("", id="run-name", markup=False)
            yield Static("", id="chip", markup=False)
            yield Static("", id="run-count", markup=False)
            yield Static("", id="run-gap")
            yield Button("Pause", id="pause", classes="blue")
            yield Button("Stop" if ascii_mode else "■ Stop", id="stop", classes="red")
            yield Button("Retry failed", id="retry")
        with Horizontal(id="run-mid"):
            with Vertical(id="run-icon"):
                yield PixelArt(BOX, _ICON_PALETTE, ascii_mode=ascii_mode, id="package-icon")
            with Vertical(id="run-meters"):
                yield Meter("download", ascii_mode, id="meter-speed")
                yield Meter("received", ascii_mode, id="meter-received")
            with Vertical(id="run-state"):
                yield PercentBar(ascii_mode, id="percent")
                yield StageList(ascii_mode, id="stages")
        yield Static("", id="summary", markup=False)
        yield Static("", id="item-notes", markup=False)
        yield Static("", id="notice", markup=False)
        with Horizontal(id="run-tabs"):
            yield Button("LOG", id="tab-log", classes="blue", compact=True)
            yield Button("QUEUE", id="tab-queue", classes="gray", compact=True)
        with Horizontal(id="run-bottom"):
            with Vertical(id="log-box") as box:
                box.border_title = "LOG"
                yield RichLog(id="run-log", wrap=False, markup=False, highlight=False)
            with Vertical(id="queue-box") as box:
                box.border_title = "QUEUE"
                yield QueuePanel(ascii_mode, id="queue")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#summary").display = False
        self.query_one("#item-notes").display = False
        self.query_one("#notice").display = False
        self.query_one("#retry").display = False
        self.query_one("#run-tabs").display = False
        self.set_interval(_ANIMATION_SECONDS, self.query_one(PercentBar).tick)
        self.app.add_run_listener(self.on_run_view)
        self.on_run_view(self.app.runner.view)

    def new_run(self) -> None:
        """Keeps the log of the earlier run on screen, but measures afresh."""
        self._seen_output = 0
        self._notice = ""
        self.query_one("#meter-speed", Meter).clear()
        self.query_one("#meter-received", Meter).clear()
        self.query_one("#run-log", RichLog).write(Text("── new run ──", style="dim"))

    # Showing the state of the run

    def on_run_view(self, view: RunView) -> None:
        if not self.query("#run-top"):
            return
        self._show_top(view)
        self._show_numbers(view)
        self._show_log(view)
        self.query_one(QueuePanel).show(view.items)
        self._show_results(view)
        self._show_notice(view)

    def _chip(self, view: RunView) -> tuple[str, str]:
        if view.state is RunState.FINISHED:
            bad = view.summary is not None and view.summary.failed > 0
            return ("FINISHED", "bad" if bad else "good")
        if view.state is RunState.PAUSED:
            return ("PAUSED", "hold")
        if view.stage in _CHIPS:
            return (_CHIPS[view.stage], "busy")
        return ("STARTING", "busy")

    def _show_top(self, view: RunView) -> None:
        name = view.active_name or ("All done" if view.state is RunState.FINISHED else "Waiting")
        self.query_one("#run-name", Static).update(name)
        text, kind = self._chip(view)
        chip = self.query_one("#chip", Static)
        chip.update(text)
        chip.set_classes(f"chip-{kind}")
        total = len(view.items)
        finished = sum(1 for i in view.items if i.state not in (ItemState.WAITING, ItemState.ACTIVE))
        self.query_one("#run-count", Static).update(f"{finished}/{total}  {clock(view.elapsed_s)}")
        running = view.state in (RunState.RUNNING, RunState.PAUSED)
        pause = self.query_one("#pause", Button)
        stop = self.query_one("#stop", Button)
        pause.display = stop.display = running
        if running:
            if str(pause.label) != view.controls.pause_label:
                pause.label = view.controls.pause_label
                pause.refresh(layout=True)
            pause.disabled = not view.controls.pause_enabled
        failed = view.summary is not None and view.summary.failed > 0
        self.query_one("#retry").display = view.state is RunState.FINISHED and failed

    def _show_numbers(self, view: RunView) -> None:
        progress = view.progress
        moving = view.state is RunState.RUNNING
        caption = {
            RunState.PAUSED: "Paused",
            RunState.FINISHED: "Finished",
        }.get(view.state, "Working…" if not self.app.ascii_mode else "Working")
        self.query_one(PercentBar).show(progress, view.elapsed_s, caption, moving)
        self.query_one(StageList).show(view.stage, view.state is RunState.FINISHED)
        speed = self.query_one("#meter-speed", Meter)
        received = self.query_one("#meter-received", Meter)
        now = time.monotonic()
        take_sample = moving and now - self._last_sample >= _SAMPLE_SECONDS
        if take_sample:
            self._last_sample = now
        speed_text = f"{view.speed_mb_s:.1f} MB/s" if view.speed_mb_s is not None else None
        speed.show(speed_text, view.speed_mb_s if take_sample and view.speed_mb_s is not None else None)
        mb = progress.received_mb if progress else None
        received.show(f"{mb:.0f} MB" if mb is not None else None, mb if take_sample and mb is not None else None)
        done = view.state is RunState.FINISHED
        if done != self._icon_done:
            self._icon_done = done
            icon = self.query_one("#package-icon", PixelArt)
            icon.palette = _ICON_DONE if done else _ICON_PALETTE
            icon.refresh()

    def _show_log(self, view: RunView) -> None:
        fresh = view.output_total - self._seen_output
        if fresh <= 0:
            return
        self._seen_output = view.output_total
        log = self.query_one("#run-log", RichLog)
        for when, line in view.output[-fresh:]:
            text = Text(f"{when}  ", style="dim")
            text.append(line, style="not dim")
            log.write(text)

    def _show_results(self, view: RunView) -> None:
        summary = self.query_one("#summary", Static)
        notes = self.query_one("#item-notes", Static)
        reasons = [self._reason(i) for i in view.items if i.state is ItemState.FAILED]
        notes.display = bool(reasons)
        if reasons:
            notes.update("\n".join(reasons))
        finished = view.state is RunState.FINISHED and view.summary is not None
        summary.display = finished
        if finished:
            s = view.summary
            parts = [f"{s.done} upgraded"]
            if s.restart_needed:
                parts.append(_plural(s.restart_needed, "needs a restart", "need a restart"))
            if s.skipped:
                parts.append(f"{s.skipped} skipped")
            if s.failed:
                parts.append(f"{s.failed} failed")
            if s.stopped:
                parts.append(f"{s.stopped} stopped")
            summary.update("Finished: " + ", ".join(parts))

    @staticmethod
    def _reason(item) -> str:
        name = item.package.name
        if item.in_use:
            return f"{name} is in use. Close it yourself, then press Retry failed. ({item.code})"
        return f"{name}: {item.message} ({item.code})"

    def _show_notice(self, view: RunView) -> None:
        lines = [line for line in (self._notice, view.last_error) if line]
        if view.stalled:
            lines.append("No output from winget for a while. It may just be slow, so nothing was stopped.")
        notice = self.query_one("#notice", Static)
        notice.display = bool(lines)
        if lines:
            notice.update("\n".join(lines))

    def say(self, text: str) -> None:
        self._notice = text
        self._show_notice(self.app.runner.view)

    # The controls

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "back":
                self.action_back()
            case "pause":
                self.action_pause_resume()
            case "stop":
                self.action_stop()
            case "retry":
                self.app.retry_failed()
            case "tab-log":
                self.set_tab("log")
            case "tab-queue":
                self.set_tab("queue")

    def set_tab(self, name: str) -> None:
        self.query_one("#log-box").display = name == "log"
        self.query_one("#queue-box").display = name == "queue"
        self.query_one("#tab-log").set_classes("blue" if name == "log" else "gray")
        self.query_one("#tab-queue").set_classes("blue" if name == "queue" else "gray")

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_pause_resume(self) -> None:
        runner = self.app.runner
        view = runner.view
        if view.state is RunState.PAUSED:
            self._notice = ""
            runner.resume()
            return
        if not view.controls.pause_enabled:
            return
        offer = (
            view.stage is Stage.DOWNLOADING
            and not view.direct_downloader
            and self._may_offer_direct_downloader()
        )
        runner.pause()
        if offer:
            self._offer_direct_downloader()

    def _may_offer_direct_downloader(self) -> bool:
        caps = self.app.backend.capabilities()
        settings = self.app.store.load_settings()
        return bool(caps) and not caps.settings_locked and not settings.offered_direct_downloader

    def _offer_direct_downloader(self) -> None:
        store = self.app.store
        store.save_settings(replace(store.load_settings(), offered_direct_downloader=True))
        dialog = ConfirmDialog("Pause during a download", _OFFER, (_TURN_ON,), cancel_label="Not now")
        self.app.push_screen(dialog, self._offer_answered)

    def _offer_answered(self, choice: str | None) -> None:
        if choice != _TURN_ON:
            return
        app = self.app
        try:
            change = app.backend.enable_direct_downloader(app.log_file.data_dir.state)
        except Exception as e:  # shown to the user: nothing changed and pausing stays as it was
            app.log_file.error("Could not turn on the direct downloader", error=repr(e))
            self.say(f"The winget setting could not be changed: {e}")
            return
        stored = {**asdict(change), "backup": str(change.backup) if change.backup else None}
        app.store.save_settings(replace(app.store.load_settings(), moved_downloader=stored))
        app.runner.set_direct_downloader(True)
        self.say("The direct downloader is on from the next package. Settings has an Undo.")

    def action_stop(self) -> None:
        view = self.app.runner.view
        choices = view.controls.stop_choices
        if not choices:
            return
        self.app.push_screen(
            ConfirmDialog("Stop the upgrade run?", self._stop_text(view), choices, danger=(STOP_NOW, FORCE_STOP)),
            self._stop_answered,
        )

    def _stop_text(self, view: RunView) -> str:
        after = "Stop after this one lets the current package finish, then stops the rest."
        if STOP_PLAIN in view.controls.stop_choices:
            return "The packages still waiting will not be upgraded."
        if FORCE_STOP in view.controls.stop_choices:
            return (
                f"{after}\n\nAn installer is running. Force stop ends it midway, which is only for an "
                "installer that has hung. You will be asked once more."
            )
        if view.direct_downloader:
            return (
                f"{after}\n\nStop now ends the download and nothing will install. A partial file may be left "
                "in winget's temporary folder."
            )
        return (
            f"{after}\n\nStop now ends winget and nothing will install, but Windows' download service may "
            "finish the download in the background, and that file may stay in winget's temporary folder."
        )

    def _stop_answered(self, choice: str | None) -> None:
        runner = self.app.runner
        if choice in (STOP_AFTER, STOP_PLAIN):
            runner.stop_after()
            self.say("Stopping after this package.") if choice == STOP_AFTER else None
        elif choice == STOP_NOW:
            runner.stop_now()
            if not runner.view.direct_downloader:
                self.say("Stopped. Windows' download service may still finish the download in the background.")
        elif choice == FORCE_STOP:
            self.app.push_screen(
                ConfirmDialog(
                    "Force stop this installer?",
                    "Ending an installer midway can leave the app broken until it is reinstalled. "
                    "Use this only if the installer has hung.",
                    (FORCE_STOP,),
                    danger=(FORCE_STOP,),
                    cancel_label="Keep going",
                ),
                self._force_answered,
            )

    def _force_answered(self, choice: str | None) -> None:
        if choice == FORCE_STOP:
            self.app.runner.force_stop()
            self._show_notice(self.app.runner.view)

    @on(QueuePanel.Move)
    def _move(self, event: QueuePanel.Move) -> None:
        self.app.runner.move_item(event.package_id, event.delta)

    @on(QueuePanel.Remove)
    def _remove(self, event: QueuePanel.Remove) -> None:
        self.app.runner.remove_item(event.package_id)
