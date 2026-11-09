# One portable console exe. Build through scripts/build.ps1, which names the output and keeps earlier builds.
import os
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH)
name = os.environ.get("WINGETDECK_EXE_NAME", "WingetDeck-x64")

datas = [(str(root / "src/wingetdeck/ui/app.tcss"), "wingetdeck/ui")]
binaries = []
# Textual and Rich load these by name at run time, so the analysis cannot see them.
hidden = collect_submodules("textual.widgets") + collect_submodules("rich")

try:
    import winpty  # noqa: F401
except ImportError:
    print("No pywinpty in this Python: this build has no live progress numbers.")
else:
    winpty_datas, winpty_binaries, winpty_hidden = collect_all("winpty")
    datas += winpty_datas
    binaries += winpty_binaries
    hidden += winpty_hidden

analysis = Analysis(
    [str(root / "src/wingetdeck/__main__.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["pytest", "tkinter", "unittest", "pydoc_data"],
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name=name,
    console=True,
    upx=False,
    icon=str(root / "assets/wingetdeck.ico"),
)
