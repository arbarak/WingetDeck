"""What a new scan means for the table the user is looking at."""

from __future__ import annotations

from dataclasses import dataclass

from ..winget.models import Package, ScanResult


@dataclass(frozen=True)
class MergeResult:
    rows: list[Package]
    ticked: set[str]
    new_ids: set[str]
    gone_ids: set[str]


def merge_scan(
    old: list[Package],
    new: ScanResult,
    ticked: set[str],
    seen: set[str],
    first: bool | None = None,
) -> MergeResult:
    """Ticks follow the package id. Nothing is new on the first scan, because everything would be."""
    is_first = not seen if first is None else first
    ids = {p.id for p in new.packages}
    return MergeResult(
        rows=list(new.packages),
        ticked=ticked & ids,
        new_ids=set() if is_first else ids - seen,
        gone_ids={p.id for p in old} - ids,
    )
