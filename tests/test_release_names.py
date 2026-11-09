"""Downloads are named with the version and the processor type, such as WingetDeck-1.0.3-x64.exe.

A name that changes with each version cannot be reached through GitHub's "latest" link, so the page and the README
point at this version's files, and these tests fail if they fall behind the version number.
"""

import re
from pathlib import Path

from wingetdeck import __version__

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_the_version_is_three_plain_numbers():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_the_build_names_each_exe_with_the_version_and_processor():
    script = read("scripts/build.ps1")
    assert '$name = "WingetDeck-$version-$Arch"' in script
    assert "__version__" in script


def test_the_download_buttons_fetch_this_versions_files():
    page = read("site/index.html")
    for arch in ("x64", "x86"):
        assert f"releases/download/v{__version__}/WingetDeck-{__version__}-{arch}.exe" in page


def test_no_link_points_at_a_name_that_no_longer_exists():
    for name in ("site/index.html", "README.md", "SECURITY.md", ".github/ISSUE_TEMPLATE/bug_report.yml"):
        old = re.findall(r"WingetDeck-x(?:64|86)\.exe", read(name))
        assert not old, f"{name} still names {old[0]}"


def test_the_readme_names_this_versions_files():
    readme = read("README.md")
    assert f"WingetDeck-{__version__}-x64.exe" in readme
    assert f"WingetDeck-{__version__}-x86.exe" in readme
    other = set(re.findall(r"WingetDeck-(\d+\.\d+\.\d+)-x(?:64|86)\.exe", readme)) - {__version__}
    assert not other, f"the README still names version {sorted(other)}"
