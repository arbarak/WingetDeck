"""Save a picture of a screen of the demo app, for checking the look without a terminal.

Usage: python scripts/shot.py OUTPUT.svg [WIDTH HEIGHT] [KEYS...]

Set WINGETDECK_SHOT_REAL=1 to read this PC's real winget instead of the demo list. Keep the keys to
looking around: this drives the real app. Set WINGETDECK_SHOT_LANGUAGE=fr for the French screens.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from wingetdeck.core.logs import SessionLog
from wingetdeck.core.runner import Runner
from wingetdeck.core.store import Settings, Store
from wingetdeck.paths import resolve_data_dir
from wingetdeck.ui.app import WingetDeckApp
from wingetdeck.winget.fake import FakeBackend, demo_packages
from wingetdeck.winget.real import RealBackend


async def main() -> None:
    out = Path(sys.argv[1])
    size = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (120, 36)
    keys = sys.argv[4:]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        data = resolve_data_dir(Path(folder) / "a", Path(folder) / "b")
        log = SessionLog(data, False, {})
        store = Store(data, log)
        store.save_settings(Settings(language=os.environ.get("WINGETDECK_SHOT_LANGUAGE", "")))
        real = os.environ.get("WINGETDECK_SHOT_REAL") == "1"
        backend = RealBackend(log) if real else FakeBackend(demo_packages(), speed=4)
        runner = Runner(backend, store, log, lambda view: None)
        app = WingetDeckApp(backend, store, log, runner)
        async with app.run_test(size=size) as pilot:
            await pilot.pause(0.5)
            for key in keys:
                if key.startswith("wait"):
                    await pilot.pause(float(key[4:]))
                elif key.startswith("#"):
                    await pilot.click(key)
                else:
                    await pilot.press(key)
                await pilot.pause(0.2)
            out.write_text(app.export_screenshot(), encoding="utf-8")
            await runner.shutdown()
        log.close() if hasattr(log, "close") else None


asyncio.run(main())
