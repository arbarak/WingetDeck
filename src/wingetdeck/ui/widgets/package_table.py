"""The clickable table. Drawn line by line because a row click needs Shift, a header click needs the
column under the mouse, and the columns change with the window width."""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len, set_cell_size
from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.binding import Binding
from textual.geometry import Size
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip

from ...winget.models import ChangeKind, Package

_TICK_WIDTH = 3
_VERSION_MIN = 9
_VERSION_MAX = 16
_ID_MAX = 30
_WIDE = 120
_MEDIUM = 80
_RANK = {ChangeKind.MAJOR: 0, ChangeKind.MINOR: 1, ChangeKind.PATCH: 2, ChangeKind.UNKNOWN: 3}
_TITLES = {
    "tick": "",
    "name": "NAME",
    "id": "ID",
    "installed": "INSTALLED",
    "available": "AVAILABLE",
    "versions": "VERSION",
    "source": "SOURCE",
    "change": "CHANGE",
}


@dataclass(frozen=True)
class Column:
    key: str
    width: int


def fit(text: str, width: int, ellipsis: str) -> str:
    """Exactly `width` cells wide, counting double-width letters properly."""
    if width <= 0:
        return ""
    if cell_len(text) <= width:
        return set_cell_size(text, width)
    return set_cell_size(set_cell_size(text, width - 1) + ellipsis, width)


def _version_width(rows: list[Package], attribute: str) -> int:
    longest = max((len(getattr(p, attribute)) for p in rows), default=0)
    return min(max(longest, _VERSION_MIN), _VERSION_MAX)


def columns(width: int, rows: list[Package]) -> list[Column]:
    """Which columns show at this width. Extra space goes to the names, not to stretched columns."""
    installed = _version_width(rows, "installed")
    available = _version_width(rows, "available")
    if width < _MEDIUM:
        versions = min(installed + available + 3, max(width // 2, 12))
        name = max(width - _TICK_WIDTH - versions - 2, 8)
        return [Column("tick", _TICK_WIDTH), Column("name", name), Column("versions", versions)]
    source = 8 if width >= _WIDE else 7
    fixed = [
        Column("installed", installed),
        Column("available", available),
        Column("source", source),
        Column("change", 8),
    ]
    used = _TICK_WIDTH + sum(c.width for c in fixed)
    if width < _WIDE:
        name = width - used - len(fixed) - 1
        return [Column("tick", _TICK_WIDTH), Column("name", name), *fixed]
    room = width - used - len(fixed) - 2
    longest_id = max((len(p.id) for p in rows), default=0)
    id_width = min(max(longest_id, 10), _ID_MAX, room // 2)
    return [Column("tick", _TICK_WIDTH), Column("name", room - id_width), Column("id", id_width), *fixed]


def _sort_key(package: Package, key: str):
    if key == "change":
        return (_RANK[package.change], package.name.lower())
    if key == "versions":
        return package.available.lower()
    return (getattr(package, key) or "").lower()


class PackageTable(ScrollView, can_focus=True):
    COMPONENT_CLASSES = {
        "table--header",
        "table--cursor",
        "table--hover",
        "table--ticked",
        "table--unticked",
        "table--major",
        "table--minor",
        "table--patch",
        "table--unknown",
        "table--new",
        "table--note",
    }
    BINDINGS = [
        Binding("up", "move(-1)", show=False),
        Binding("down", "move(1)", show=False),
        Binding("pageup", "move(-10)", show=False),
        Binding("pagedown", "move(10)", show=False),
        Binding("home", "move(-100000)", show=False),
        Binding("end", "move(100000)", show=False),
        Binding("space", "tick_cursor", "Tick"),
    ]

    include_pinned: reactive[bool] = reactive(False)

    class TicksChanged(Message):
        pass

    def __init__(self, ascii_mode: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.ascii_mode = ascii_mode
        self.all_rows: list[Package] = []
        self.rows: list[Package] = []
        self.ticked: set[str] = set()
        self.new_ids: set[str] = set()
        self.filter_text = ""
        self.sort_key = "change"
        self.sort_reverse = False
        self.cursor = 0
        self.anchor: int | None = None
        self._hover: int | None = None

    # Data

    def set_rows(self, rows: list[Package], ticked: set[str], new_ids: set[str]) -> None:
        """Keeps the scroll position and the cursor's package when the same rows come back."""
        current = self.rows[self.cursor].id if self.cursor < len(self.rows) else None
        self.all_rows = rows
        self.ticked = {i for i in ticked if self._selectable_id(i)}
        self.new_ids = new_ids
        self._rebuild(current)
        self.post_message(self.TicksChanged())

    def _selectable_id(self, package_id: str) -> bool:
        return any(p.id == package_id and self.selectable(p) for p in self.all_rows)

    def selectable(self, package: Package) -> bool:
        return not package.truncated_id and (self.include_pinned or not package.pinned)

    def _rebuild(self, keep_id: str | None = None) -> None:
        wanted = self.filter_text.lower()
        rows = [p for p in self.all_rows if wanted in p.name.lower() or wanted in p.id.lower()]
        self.rows = sorted(rows, key=lambda p: _sort_key(p, self.sort_key), reverse=self.sort_reverse)
        if keep_id is not None:
            self.cursor = next((n for n, p in enumerate(self.rows) if p.id == keep_id), 0)
        self.cursor = min(self.cursor, max(len(self.rows) - 1, 0))
        self.virtual_size = Size(self.size.width, len(self.rows) + 1)
        self.refresh()

    def set_filter(self, text: str) -> None:
        self.filter_text = text
        self.anchor = None
        self._rebuild()

    def sort_by(self, key: str) -> None:
        if key == self.sort_key:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_key, self.sort_reverse = key, False
        self.anchor = None
        self._rebuild(self.rows[self.cursor].id if self.rows else None)

    def watch_include_pinned(self) -> None:
        self.refresh()

    # Ticking

    def _ticks_changed(self) -> None:
        self.refresh()
        self.post_message(self.TicksChanged())

    def tick_row(self, index: int) -> None:
        if not 0 <= index < len(self.rows) or not self.selectable(self.rows[index]):
            return
        self.ticked ^= {self.rows[index].id}
        self.anchor = index
        self._ticks_changed()

    def tick_range(self, start: int, end: int) -> None:
        low, high = sorted((start, end))
        self.ticked |= {p.id for p in self.rows[low : high + 1] if self.selectable(p)}
        self._ticks_changed()

    def select_all(self) -> None:
        self.ticked |= {p.id for p in self.rows if self.selectable(p)}
        self._ticks_changed()

    def select_none(self) -> None:
        self.ticked = set()
        self._ticks_changed()

    def select_change(self, kind: ChangeKind) -> None:
        self.ticked |= {p.id for p in self.rows if p.change is kind and self.selectable(p)}
        self._ticks_changed()

    def ticked_packages(self) -> list[Package]:
        return [p for p in sorted(self.all_rows, key=lambda p: _sort_key(p, self.sort_key)) if p.id in self.ticked]

    # Keys and mouse

    def action_move(self, delta: int) -> None:
        if not self.rows:
            return
        self.cursor = max(0, min(self.cursor + delta, len(self.rows) - 1))
        self.scroll_to_row(self.cursor)
        self.refresh()

    def scroll_to_row(self, index: int) -> None:
        top = self.scroll_offset.y
        visible = max(self.size.height - 1, 1)
        if index < top:
            self.scroll_to(y=index, animate=False)
        elif index >= top + visible:
            self.scroll_to(y=index - visible + 1, animate=False)

    def action_tick_cursor(self) -> None:
        self.tick_row(self.cursor)

    def _row_at(self, y: int) -> int | None:
        index = y - 1 + self.scroll_offset.y
        return index if y >= 1 and index < len(self.rows) else None

    def _column_at(self, x: int) -> str | None:
        left = 0
        for column in columns(self.size.width, self.all_rows):
            if left <= x < left + column.width + 1:
                return column.key
            left += column.width + 1
        return None

    def on_click(self, event: events.Click) -> None:
        self.focus()
        if event.y == 0:
            key = self._column_at(event.x)
            if key == "tick":
                visible = [p for p in self.rows if self.selectable(p)]
                if visible and all(p.id in self.ticked for p in visible):
                    self.ticked -= {p.id for p in visible}
                    self._ticks_changed()
                else:
                    self.select_all()
            elif key:
                self.sort_by(key)
            return
        index = self._row_at(event.y)
        if index is None:
            return
        self.cursor = index
        if event.shift and self.anchor is not None:
            self.tick_range(self.anchor, index)
        else:
            self.tick_row(index)
        self.refresh()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        index = self._row_at(event.y)
        if index != self._hover:
            self._hover = index
            self.refresh()

    def on_leave(self, _event: events.Leave) -> None:
        self._hover = None
        self.refresh()

    def on_resize(self, _event: events.Resize) -> None:
        self.virtual_size = Size(self.size.width, len(self.rows) + 1)
        self.refresh()

    def get_content_height(self, container, viewport, width) -> int:
        return len(self.rows) + 1

    # Drawing

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if y == 0:
            return self._header(width)
        index = self._row_at(y)
        if index is None:
            return Strip.blank(width, self.rich_style)
        return self._row(index, width)

    def _ellipsis(self) -> str:
        return "~" if self.ascii_mode else "…"

    def _header(self, width: int) -> Strip:
        style = self.get_component_rich_style("table--header")
        segments: list[Segment] = []
        for column in columns(width, self.all_rows):
            if column.key == "tick":
                title = "[x]" if self.ascii_mode else "[✓]"
            else:
                title = _TITLES[column.key]
                if column.key == self.sort_key:
                    up, down = ("^", "v") if self.ascii_mode else ("▲", "▼")
                    title = f"{up if self.sort_reverse else down} {title}"
            segments.append(Segment(fit(title, column.width, self._ellipsis()) + " ", style))
        return Strip(segments).adjust_cell_length(width, style)

    def _notes(self, package: Package) -> list[str]:
        notes = []
        if package.pinned:
            notes.append("pinned")
        if package.explicit_only:
            notes.append("explicit")
        if package.truncated_id:
            notes.append("id cut off")
        return notes

    def _row(self, index: int, width: int) -> Strip:
        package = self.rows[index]
        if index == self.cursor and self.has_focus:
            base = self.get_component_rich_style("table--cursor")
            plain_row = True
        else:
            base = self.get_component_rich_style("table--hover") if index == self._hover else self.rich_style
            plain_row = False

        def styled(name: str) -> Style:
            return base if plain_row else base + self.get_component_rich_style(name)

        segments: list[Segment] = []
        for column in columns(width, self.all_rows):
            segments.extend(self._cell(package, column, base, styled))
            segments.append(Segment(" ", base))
        return Strip(segments).adjust_cell_length(width, base)

    def _cell(self, package: Package, column: Column, base: Style, styled) -> list[Segment]:
        cut = self._ellipsis()
        if column.key == "tick":
            if not self.selectable(package):
                return [Segment(fit("[-]", column.width, cut), styled("table--note"))]
            if package.id in self.ticked:
                mark = "[x]" if self.ascii_mode else "[✓]"
                return [Segment(fit(mark, column.width, cut), styled("table--ticked"))]
            return [Segment(fit("[ ]", column.width, cut), styled("table--unticked"))]
        if column.key == "name":
            return self._name_cell(package, column.width, base, styled)
        if column.key == "versions":
            arrow = "->" if self.ascii_mode else "→"
            return [Segment(fit(f"{package.installed} {arrow} {package.available}", column.width, cut), base)]
        if column.key == "change":
            word = package.change.value
            return [Segment(fit(word, column.width, cut), styled(f"table--{word}"))]
        return [Segment(fit(getattr(package, column.key) or "", column.width, cut), base)]

    def _name_cell(self, package: Package, width: int, base: Style, styled) -> list[Segment]:
        tags: list[tuple[str, str]] = []
        if package.id in self.new_ids:
            tags.append((" NEW ", "table--new"))
        for note in self._notes(package):
            tags.append((f"({note})", "table--note"))
        tag_cells = sum(cell_len(text) + 1 for text, _ in tags)
        name_width = max(width - tag_cells, min(width, 6))
        result = [Segment(fit(package.name, name_width, self._ellipsis()), base)]
        room = width - name_width
        for text, style in tags:
            if room < cell_len(text) + 1:
                break
            result.append(Segment(" ", base))
            result.append(Segment(text, styled(style)))
            room -= cell_len(text) + 1
        if room:
            result.append(Segment(" " * room, base))
        return result
