"""Write a Windows Sandbox config for one experiment. Usage: make_wsb.py <experiment> [arg]

Folders: scripts/sandbox (C:\\spike), .sandbox/sandbox-out (C:\\out, writable),
.sandbox/sandbox-cache (C:\\cache), the host Python (C:\\py) and the project's packages (C:\\site).
"""

import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
PY = Path(sys.base_prefix)


def folder(host: Path, sandbox: str, read_only: bool = True) -> str:
    flag = "true" if read_only else "false"
    return (
        f"<MappedFolder><HostFolder>{escape(str(host))}</HostFolder>"
        f"<SandboxFolder>{sandbox}</SandboxFolder><ReadOnly>{flag}</ReadOnly></MappedFolder>"
    )


def main() -> None:
    experiment = " ".join(sys.argv[1:])
    command = f"powershell -ExecutionPolicy Bypass -File C:\\spike\\setup_and_run.ps1 {experiment}"
    extra = ROOT / "dist-sandbox"
    maps = [
        folder(ROOT / "scripts" / "sandbox", "C:\\spike"),
        folder(ROOT / ".sandbox" / "sandbox-out", "C:\\out", read_only=False),
        folder(ROOT / ".sandbox" / "sandbox-cache", "C:\\cache"),
        folder(PY, "C:\\py"),
        folder(ROOT / ".venv" / "Lib" / "site-packages", "C:\\site"),
    ]
    if extra.exists():
        maps.append(folder(extra, "C:\\dist"))
    xml = (
        "<Configuration><vGPU>Disable</vGPU><Networking>Enable</Networking>"
        f"<MappedFolders>{''.join(maps)}</MappedFolders>"
        f"<LogonCommand><Command>{escape(command)}</Command></LogonCommand></Configuration>"
    )
    out = ROOT / ".sandbox" / f"spike-{sys.argv[1]}.wsb"
    out.write_text(xml, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
