from wingetdeck.core.selection import merge_scan
from wingetdeck.winget.models import ChangeKind, Package, ScanResult


def pkg(i):
    return Package(i, i, "1.0", "1.1", "winget", ChangeKind.MINOR)


def test_merge_keeps_ticks_marks_new_drops_gone():
    old = [pkg("A"), pkg("B")]
    new = ScanResult([pkg("B"), pkg("C")])
    m = merge_scan(old, new, ticked={"A", "B"}, seen={"A", "B"})
    assert [p.id for p in m.rows] == ["B", "C"]
    assert m.ticked == {"B"} and m.new_ids == {"C"} and m.gone_ids == {"A"}


def test_first_scan_marks_nothing_new():
    m = merge_scan([], ScanResult([pkg("A"), pkg("B")]), ticked=set(), seen=set())
    assert m.new_ids == set() and m.gone_ids == set()


def test_package_seen_earlier_is_not_new_when_it_returns():
    m = merge_scan([pkg("B")], ScanResult([pkg("A"), pkg("B")]), ticked=set(), seen={"A", "B"})
    assert m.new_ids == set()


def test_scan_finding_nothing_after_an_empty_first_scan_still_marks_new_later():
    assert merge_scan([], ScanResult([pkg("A")]), set(), seen=set(), first=False).new_ids == {"A"}


def test_a_newer_version_replaces_the_old_row():
    newer = Package("A", "A", "1.0", "2.0", "winget", ChangeKind.MAJOR)
    m = merge_scan([pkg("A")], ScanResult([newer]), ticked={"A"}, seen={"A"})
    assert m.rows[0].available == "2.0" and m.ticked == {"A"}
