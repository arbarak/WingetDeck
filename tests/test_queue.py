from wingetdeck.core.queue import (
    Effect,
    ItemState,
    RunQueue,
    RunState,
)
from wingetdeck.winget.models import ChangeKind, Package, Stage

OK = 0
RESTART = 0x8A150109
NOT_APPLICABLE = 0x8A15002B
IN_USE = 0x8A150101
STOP_AFTER = "Stop after this one"
STOP_NOW = "Stop now"
FORCE = "Force stop"


def pkg(i):
    return Package(i, i, "1.0", "1.1", "winget", ChangeKind.MINOR)


def running(stage=Stage.DOWNLOADING, direct=True, ids=("A", "B", "C")):
    q = RunQueue([pkg(i) for i in ids], direct_downloader=direct)
    assert q.start() is Effect.START_NEXT
    q.on_stage(stage)
    return q


def states(q):
    return [i.state for i in q.items]


def test_starts_with_first_item_active():
    q = running()
    assert q.state is RunState.RUNNING and q.active.package.id == "A" and states(q)[0] is ItemState.ACTIVE


def test_pause_during_download_with_direct_freezes():
    q = running(Stage.DOWNLOADING, direct=True)
    assert q.pause() is Effect.FREEZE and q.state is RunState.PAUSED
    assert q.controls().pause_label == "Resume"


def test_resume_thaws():
    q = running(Stage.DOWNLOADING, direct=True)
    q.pause()
    assert q.resume() is Effect.THAW and q.state is RunState.RUNNING


def test_pause_during_download_without_direct_waits():
    q = running(Stage.DOWNLOADING, direct=False)
    assert q.pause() is Effect.NONE and q.state is RunState.RUNNING
    c = q.controls()
    assert c.pause_label == "Pausing after this package…" and not c.pause_enabled


def test_pause_label_before_pressing_without_direct_is_honest():
    assert running(Stage.DOWNLOADING, direct=False).controls().pause_label == "Pause after this package"


def test_pause_during_install_never_freezes():
    q = running(Stage.INSTALLING, direct=True)
    assert q.pause() is Effect.NONE
    assert q.controls().pause_label == "Pausing after this install…"


def test_pause_during_verify_never_freezes():
    assert running(Stage.VERIFYING, direct=True).pause() is Effect.NONE


def test_unknown_stage_uses_safe_rules():
    assert running(Stage.WORKING, direct=True).pause() is Effect.NONE


def test_no_stage_yet_uses_safe_rules():
    q = RunQueue([pkg("A")], direct_downloader=True)
    q.start()
    assert q.pause() is Effect.NONE


def test_pause_refused_by_handle_falls_back_to_pause_after():
    q = running(Stage.DOWNLOADING, direct=True)
    q.pause()
    q.freeze_refused()
    assert q.state is RunState.RUNNING and q.controls().pause_label == "Pausing after this package…"


def test_pause_after_applies_when_package_finishes():
    q = running(Stage.INSTALLING, direct=True)
    q.pause()
    assert q.on_finished(OK) is Effect.NONE and q.state is RunState.PAUSED and q.active is None
    assert q.controls().pause_label == "Resume"


def test_resume_between_packages_starts_next():
    q = running(Stage.INSTALLING)
    q.pause()
    q.on_finished(OK)
    assert q.resume() is Effect.START_NEXT and q.active.package.id == "B"


def test_stop_choices_download_with_direct():
    assert running(Stage.DOWNLOADING).controls().stop_choices == (STOP_AFTER, STOP_NOW)


def test_stop_choices_download_without_direct_still_offers_stop_now():
    assert running(Stage.DOWNLOADING, direct=False).controls().stop_choices == (STOP_AFTER, STOP_NOW)


def test_stop_choices_install():
    assert running(Stage.INSTALLING).controls().stop_choices == (STOP_AFTER, FORCE)


def test_stop_choices_between_packages():
    q = running(Stage.INSTALLING)
    q.pause()
    q.on_finished(OK)
    assert q.controls().stop_choices == ("Stop",)


def test_stop_after_finishes_active_and_stops_rest():
    q = running(Stage.INSTALLING)
    assert q.stop_after() is Effect.NONE
    assert q.on_finished(OK) is Effect.NONE and q.state is RunState.FINISHED
    assert states(q) == [ItemState.DONE, ItemState.STOPPED, ItemState.STOPPED]


def test_stop_now_kills_and_marks_rest_stopped():
    q = running(Stage.DOWNLOADING)
    assert q.stop_now() is Effect.KILL
    q.on_finished(1)
    assert q.state is RunState.FINISHED and states(q) == [ItemState.STOPPED] * 3


def test_frozen_then_stop_now_thaws_before_kill():
    q = running(Stage.DOWNLOADING)
    q.pause()
    assert q.stop_now() is Effect.THAW_AND_KILL


def test_stop_now_during_install_is_refused():
    q = running(Stage.INSTALLING)
    assert q.stop_now() is Effect.NONE and states(q)[0] is ItemState.ACTIVE


def test_force_stop_kills_and_marks_failed():
    q = running(Stage.INSTALLING)
    assert q.force_stop() is Effect.KILL
    q.on_finished(1)
    assert states(q) == [ItemState.FAILED, ItemState.STOPPED, ItemState.STOPPED]
    assert "force" in q.items[0].message.lower()


def test_stop_between_packages_stops_rest_without_kill():
    q = running(Stage.INSTALLING)
    q.pause()
    q.on_finished(OK)
    assert q.stop_after() is Effect.NONE and q.state is RunState.FINISHED
    assert states(q)[1:] == [ItemState.STOPPED, ItemState.STOPPED]


def test_finished_advances_to_next():
    q = running()
    assert q.on_finished(OK) is Effect.START_NEXT and q.active.package.id == "B"


def test_last_package_finishes_run():
    q = running(ids=("A",))
    assert q.on_finished(OK) is Effect.NONE and q.state is RunState.FINISHED


def test_restart_needed_counts_as_done():
    q = running()
    q.on_finished(RESTART)
    assert q.items[0].state is ItemState.DONE_RESTART


def test_no_applicable_upgrade_is_skipped():
    q = running()
    q.on_finished(NOT_APPLICABLE)
    assert q.items[0].state is ItemState.SKIPPED


def test_failure_continues_to_next_and_keeps_reason():
    q = running()
    assert q.on_finished(IN_USE) is Effect.START_NEXT
    assert q.items[0].state is ItemState.FAILED and q.items[0].in_use
    assert "0x8A150101" in q.items[0].code


def test_remove_only_waiting_items():
    q = running()
    assert not q.remove("A") and q.remove("B")
    assert [i.package.id for i in q.items] == ["A", "C"]


def test_move_only_waiting_items():
    q = running(ids=("A", "B", "C"))
    assert q.move("C", -1)
    assert [i.package.id for i in q.items] == ["A", "C", "B"]
    assert not q.move("C", -1), "cannot jump ahead of the active item"
    assert not q.move("A", 1), "the active item cannot move"


def test_rug_pull_packages_go_last():
    q = RunQueue([pkg("Microsoft.AppInstaller"), pkg("A"), pkg("Microsoft.WindowsTerminal"), pkg("B")], False)
    assert [i.package.id for i in q.items] == ["A", "B", "Microsoft.AppInstaller", "Microsoft.WindowsTerminal"]


def test_rug_pull_packages_stay_last_after_move():
    q = RunQueue([pkg("A"), pkg("B"), pkg("Microsoft.AppInstaller")], False)
    q.start()
    assert not q.move("B", 1)
    assert not q.move("Microsoft.AppInstaller", -1)


def test_retry_failed_contains_only_failed():
    q = running()
    q.on_finished(IN_USE)
    q.on_finished(OK)
    q.on_finished(OK)
    retry = q.retry_failed()
    assert [i.package.id for i in retry.items] == ["A"] and retry.state is RunState.IDLE


def test_snapshot_restore_active_returns_to_waiting():
    q = running()
    q.on_finished(OK)
    restored = RunQueue.restore(q.snapshot())
    assert [(i.package.id, i.state) for i in restored.items] == [("B", ItemState.WAITING), ("C", ItemState.WAITING)]


def test_snapshot_keeps_direct_flag():
    assert RunQueue.restore(running(direct=True).snapshot()).direct_downloader


def test_summary_counts():
    q = running()
    q.on_finished(RESTART)
    q.on_finished(IN_USE)
    q.on_finished(OK)
    s = q.summary()
    assert (s.done, s.restart_needed, s.failed) == (2, 1, 1)


def test_set_direct_applies_from_next_package():
    q = running(Stage.DOWNLOADING, direct=False)
    q.set_direct_downloader(True)
    assert q.pause() is Effect.NONE, "the running download started under the old setting"
    q2 = running(Stage.DOWNLOADING, direct=False)
    q2.set_direct_downloader(True)
    q2.on_finished(OK)
    q2.on_stage(Stage.DOWNLOADING)
    assert q2.pause() is Effect.FREEZE


def test_stop_after_on_a_frozen_download_lets_it_continue():
    q = running(Stage.DOWNLOADING)
    q.pause()
    assert q.stop_after() is Effect.THAW and q.state is RunState.RUNNING
    assert q.on_finished(OK) is Effect.NONE and q.state is RunState.FINISHED
    assert states(q) == [ItemState.DONE, ItemState.STOPPED, ItemState.STOPPED]


def test_kill_refused_lets_the_exit_code_decide():
    q = running(Stage.INSTALLING)
    q.force_stop()
    q.kill_refused()
    q.on_finished(OK)
    assert states(q) == [ItemState.DONE, ItemState.STOPPED, ItemState.STOPPED]


def test_restart_active_clears_the_stage():
    q = running(Stage.DOWNLOADING)
    q.restart_active()
    assert q.stage is None and q.active.package.id == "A" and q.state is RunState.RUNNING
