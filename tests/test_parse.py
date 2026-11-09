from pathlib import Path

import pytest

from wingetdeck.winget.models import ChangeKind
from wingetdeck.winget.parse import (
    ProgressParser,
    classify_change,
    display_width,
    parse_upgrade_table,
    strip_terminal_codes,
)

FIX = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    with (FIX / name).open(encoding="utf-8", newline="" if name.startswith("pty") else None) as f:
        return f.read()


def test_real_table():
    r = parse_upgrade_table(fixture("en_upgrade_include_unknown.txt"))
    wsl = next(p for p in r.packages if p.id == "Microsoft.WSL")
    assert (wsl.name, wsl.installed, wsl.available, wsl.source) == (
        "Windows Subsystem for Linux", "2.7.3.0", "2.7.14", "winget")
    assert wsl.change is ChangeKind.PATCH
    wk = next(p for p in r.packages if p.id == "wkhtmltopdf.wkhtmltox")
    assert wk.installed == "Unknown" and wk.change is ChangeKind.UNKNOWN


def test_real_table_counts_hidden_unknowns():
    r = parse_upgrade_table(fixture("en_upgrade.txt"))
    assert [p.id for p in r.packages] == ["Microsoft.WSL"] and r.unknown_hidden == 1


def test_no_upgrades_is_empty_not_error():
    r = parse_upgrade_table(fixture("synthetic_none.txt"))
    assert r.packages == [] and r.notes


def test_explicit_targeting_table_is_marked():
    r = parse_upgrade_table(fixture("synthetic_explicit.txt"))
    by_id = {p.id: p for p in r.packages}
    assert by_id["Discord.D"].explicit_only and not by_id["Git.Git"].explicit_only


def test_translated_headers_parse_by_position():
    assert parse_upgrade_table(fixture("synthetic_de.txt")).packages[0].id == "Git.Git"
    fr = parse_upgrade_table(fixture("synthetic_fr.txt")).packages[0]
    assert (fr.name, fr.id, fr.source) == ("Réseau é", "Reseau.App", "winget")


def test_cjk_name_keeps_columns_aligned():
    p = parse_upgrade_table(fixture("synthetic_cjk.txt")).packages[0]
    assert p.id == "Example.App" and p.available == "2.0" and p.name == "日本語アプリ"


def test_truncated_id_flagged():
    p = parse_upgrade_table(fixture("synthetic_truncated.txt")).packages[0]
    assert p.truncated_id and p.available == "1.1"


def test_footer_text_is_not_a_package():
    r = parse_upgrade_table(fixture("synthetic_footer.txt"))
    assert [p.id for p in r.packages] == ["Git.Git"] and r.unknown_hidden == 3 and len(r.notes) == 3


def test_version_with_space_and_missing_source():
    foo, bar = parse_upgrade_table(fixture("synthetic_lessthan.txt")).packages
    assert foo.installed == "< 1.2.3" and foo.change is ChangeKind.UNKNOWN
    assert bar.source is None and bar.available == "1.1"


def test_spinner_before_the_table_is_ignored():
    raw = chr(13) + "   -" + chr(13) + "   |" + chr(13) + fixture("en_upgrade.txt")
    assert parse_upgrade_table(raw).packages[0].id == "Microsoft.WSL"


@pytest.mark.parametrize("a,b,k", [
    ("1.2.3", "2.0.0", "MAJOR"), ("1.2.3", "1.3.0", "MINOR"), ("2.7.3.0", "2.7.14", "PATCH"),
    ("Unknown", "1.0", "UNKNOWN"), ("1.0-beta", "abc", "UNKNOWN"), ("< 1.0", "1.2", "UNKNOWN"),
    ("25.00", "25.01", "MINOR"), ("1", "1.0.1", "PATCH"),
])
def test_classify_change(a, b, k):
    assert classify_change(a, b).name == k


def test_display_width_counts_double_width():
    assert display_width("ab") == 2 and display_width("日本") == 4


def test_strip_terminal_codes_removes_colour_and_taskbar():
    assert strip_terminal_codes("\x1b[96mGit\x1b[0m\x1b]9;4;1;5\x1b\\") == "Git"


def test_progress_across_split_chunks():
    pp, out, raw = ProgressParser(), [], fixture("pty_download.txt")
    for i in range(0, len(raw), 37):
        out += pp.feed(raw[i:i + 37])
    mb = [x for x in out if x.total_mb]
    assert mb and 26 < mb[-1].total_mb < 28
    assert mb[-1].received_mb >= mb[0].received_mb
    assert all(0 <= x.percent <= 100 for x in out if x.percent is not None)


def test_progress_reads_real_line_and_computes_percent():
    p = ProgressParser().feed("\r  ███▍  \x1b[0m 247 MB /  494 MB")[-1]
    assert (p.received_mb, p.total_mb, p.percent) == (247, 494, 50)


def test_progress_units_convert_to_mb():
    p = ProgressParser().feed("512 KB / 1.0 GB")[-1]
    assert p.received_mb == 0.5 and p.total_mb == 1024


def test_partial_number_waits_for_its_unit():
    pp = ProgressParser()
    assert pp.feed("12 MB /  2") == []
    assert pp.feed("6.7 MB")[-1].total_mb == 26.7


def test_taskbar_code_gives_percent():
    assert ProgressParser().feed("\x1b]9;4;1;71\x1b\\")[-1].percent == 71


def test_spinner_gives_no_percent():
    assert all(x.percent is None for x in ProgressParser().feed("\r   -\r   \\"))
