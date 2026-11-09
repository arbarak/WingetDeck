import json
import zipfile

from wingetdeck.core.logs import SessionLog, redact, save_diagnostic_report


def test_writes_text_and_jsonl_with_dated_names(tmp_data):
    log = SessionLog(tmp_data, debug=False, header={"winget": "1.29.380"})
    log.error("boom", package="Git.Git", code="0x8A150101")
    text = next(tmp_data.logs.glob("session_*.log")).read_text(encoding="utf-8")
    rows = next(tmp_data.logs.glob("session_*.jsonl")).read_text(encoding="utf-8").splitlines()
    row = json.loads(rows[-1])
    assert "winget=1.29.380" in text and "boom" in text
    assert row["level"] == "ERROR" and row["package"] == "Git.Git" and row["code"] == "0x8A150101"


def test_two_sessions_never_overwrite(tmp_data):
    SessionLog(tmp_data, False, {})
    SessionLog(tmp_data, False, {})
    assert len(list(tmp_data.logs.glob("session_*.log"))) == 2


def test_debug_only_written_with_flag(tmp_data):
    log = SessionLog(tmp_data, debug=False, header={})
    log.debug("raw")
    assert not log.events(level="DEBUG")
    verbose = SessionLog(tmp_data, debug=True, header={})
    verbose.debug("raw")
    assert verbose.events(level="DEBUG")


def test_events_filter_by_package(tmp_data):
    log = SessionLog(tmp_data, False, {})
    log.info("a", package="A")
    log.warn("b", package="B")
    assert [e.message for e in log.events(package="B")] == ["b"]
    assert [e.message for e in log.events(level="WARN")] == ["b"]


def test_package_transcript_keeps_text(tmp_data):
    log = SessionLog(tmp_data, False, {})
    with log.package_transcript("Git.Git") as f:
        f.write("line\n")
    found = list(tmp_data.logs.glob("winget_*_Git.Git.log"))
    assert found and found[0].read_text(encoding="utf-8") == "line\n"


def test_package_id_is_made_safe_for_file_names(tmp_data):
    log = SessionLog(tmp_data, False, {})
    with log.package_transcript(r"ARP\Machine\X86\{ABC}") as f:
        f.write("x")
    assert list(tmp_data.logs.glob("winget_*.log"))


def test_crash_file_contains_traceback_and_recent_events(tmp_data):
    log = SessionLog(tmp_data, False, {})
    log.info("before crash")
    try:
        1 / 0
    except ZeroDivisionError as e:
        path = log.write_crash(e)
    body = path.read_text(encoding="utf-8")
    assert "ZeroDivisionError" in body and "before crash" in body


def test_redact_removes_username_header_and_proxy_secret():
    out = redact(r"C:\Users\someuser\x --header 'Bearer abc' --proxy http://u:p@host", "someuser")
    assert "someuser" not in out and "abc" not in out and "u:p@" not in out


def test_redact_removes_custom_and_override_values():
    out = redact('winget upgrade --override "/KEY=secret" --custom "/PASS=hunter2"', "x")
    assert "secret" not in out and "hunter2" not in out


def test_diagnostic_report_zip_is_redacted(tmp_data):
    log = SessionLog(tmp_data, False, {})
    log.info(r"path C:\Users\someuser\x")
    z = save_diagnostic_report(log, "winget info", None, "someuser")
    with zipfile.ZipFile(z) as zf:
        assert "winget_info.txt" in zf.namelist()
        assert all(b"someuser" not in zf.read(n) for n in zf.namelist())


def test_diagnostic_report_includes_newest_winget_logs(tmp_data, tmp_path):
    src = tmp_path / "diag"
    src.mkdir()
    (src / "WinGet-a.log").write_text("first", encoding="utf-8")
    log = SessionLog(tmp_data, False, {})
    z = save_diagnostic_report(log, "info", src, "someuser")
    with zipfile.ZipFile(z) as zf:
        assert any("WinGet-a.log" in n for n in zf.namelist())


def test_total_size_counts_log_folder(tmp_data):
    log = SessionLog(tmp_data, False, {})
    log.info("hello")
    assert log.total_size_bytes() > 0
