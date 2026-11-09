"""Command line entry point."""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Callable

from . import __version__
from .core.console import install_close_handler
from .core.logs import SessionLog
from .core.runner import Runner
from .core.store import AlreadyRunning, SingleInstance, Store
from .paths import DataDir, app_data_dir, is_elevated
from .ui.app import WingetDeckApp
from .ui.console import (
    QuickEditGuard,
    TerminalInfo,
    check_support,
    detect_terminal,
    font_has_glyph,
    session_header,
    tidy_classic_console,
    user_locale,
    windows_build,
)
from .ui.symbols import basic_symbols, lacks_any_stand_in
from .winget.fake import FakeBackend, demo_packages
from .winget.real import RealBackend

_USUAL_CONSOLE_FONT = "Consolas"


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="wingetdeck", description="Upgrade Windows apps through winget.")
    parser.add_argument("--demo", action="store_true", help="try the app with a pretend winget; nothing is installed")
    parser.add_argument("--debug", action="store_true", help="also log every line winget prints")
    parser.add_argument("--ascii", action="store_true", help="use plain characters for consoles that cannot draw symbols")
    parser.add_argument("--basic", action="store_true", help="use only symbols the console font can draw")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    return parser.parse_args(argv)


def _symbols_for(terminal: TerminalInfo) -> Callable[[str], str]:
    """Measure this console's font. If it cannot be read, assume it lacks everything that has a stand-in."""
    has_glyph = font_has_glyph(terminal.font or _USUAL_CONSOLE_FONT) or lacks_any_stand_in
    return basic_symbols(has_glyph)


def demo_data_dir(data: DataDir) -> DataDir:
    """Demo runs never touch the real queue, history or settings."""
    demo = DataDir(data.root / "demo", data.portable)
    _ = demo.logs, demo.state, demo.snapshots
    return demo


def _crash(log: SessionLog, error: BaseException) -> int:
    path = log.write_crash(error)
    print(f"WingetDeck stopped because of an error. Details are in:\n{path}", file=sys.stderr)
    return 1


def _run(app: WingetDeckApp, log: SessionLog, runner: Runner) -> int:
    def window_closed() -> None:
        log.info("Window closed")  # Windows ends the process moments later, so say so first
        runner.emergency_stop()

    install_close_handler(window_closed)
    try:
        with QuickEditGuard():
            app.run()
    except Exception as e:
        return _crash(log, e)
    finally:
        runner.emergency_stop()
    if app._exception is not None:  # Textual has already restored the terminal
        return _crash(log, app._exception)
    log.info("Session closed")  # without this line, a log cannot tell a closed window from a killed one
    return app.return_code or 0


def _safe_output() -> None:
    """A path with letters the console code page lacks must not turn an error message into a crash."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    _safe_output()
    args = _parse(argv)
    if args.version:
        print(f"WingetDeck {__version__}")
        return 0
    problem = check_support(windows_build())
    if problem and not args.demo:
        print(problem, file=sys.stderr)
        return 1
    terminal = detect_terminal()
    data = app_data_dir()
    if args.demo:
        data = demo_data_dir(data)
    try:
        with SingleInstance(data):
            size = shutil.get_terminal_size()
            header = session_header(args.demo, terminal, (size.columns, size.lines), user_locale(), is_elevated())
            log = SessionLog(data, args.debug, header)
            store = Store(data, log)
            backend = FakeBackend(demo_packages()) if args.demo else RealBackend(log)
            runner = Runner(backend, store, log, lambda view: None)
            app = WingetDeckApp(
                backend,
                store,
                log,
                runner,
                ascii_mode=args.ascii or terminal.ascii_recommended,
                symbols=_symbols_for(terminal) if args.basic or terminal.basic_symbols else None,
                tidy_console=tidy_classic_console if terminal.basic_symbols or terminal.ascii_recommended else None,
            )
            return _run(app, log, runner)
    except AlreadyRunning:
        print("WingetDeck is already running. Switch to its window.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
