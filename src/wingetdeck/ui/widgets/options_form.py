"""The run options, used for the defaults in Settings and for one package."""

from __future__ import annotations

from dataclasses import replace

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Checkbox, Input, Label, Select

from ...i18n import N_, t
from ...winget.backend import UpgradeOptions

_MODES = [(N_("Silent"), "silent"), (N_("Interactive"), "interactive"), (N_("Installer's default"), "default")]
_SCOPES = [(N_("Default"), "default"), (N_("Current user"), "user"), (N_("Whole machine"), "machine")]
_ARCHITECTURES = [(N_("Default"), "default"), ("x64", "x64"), ("x86", "x86"), ("arm64", "arm64")]


def _shown(choices: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(t(label), value) for label, value in choices]


class OptionsForm(Vertical):
    def __init__(self, options: UpgradeOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def compose(self) -> ComposeResult:
        o = self.options
        mode = "interactive" if o.interactive else "silent" if o.silent else "default"
        with Horizontal(classes="form-row"):
            yield Label(t("Installer window"), classes="form-label")
            yield Select(_shown(_MODES), value=mode, allow_blank=False, id="opt-mode")
        with Horizontal(classes="form-row"):
            yield Label(t("Scope"), classes="form-label")
            yield Select(_shown(_SCOPES), value=o.scope or "default", allow_blank=False, id="opt-scope")
        with Horizontal(classes="form-row"):
            yield Label(t("Architecture"), classes="form-label")
            yield Select(_shown(_ARCHITECTURES), value=o.architecture or "default", allow_blank=False, id="opt-arch")
        yield Checkbox(t("Force, even if the hash or checks fail"), o.force, id="opt-force")
        yield Checkbox(t("Uninstall the previous version first"), o.uninstall_previous, id="opt-uninstall")
        yield Checkbox(t("Skip dependencies"), o.skip_dependencies, id="opt-skip-deps")
        yield Checkbox(t("Include pinned packages"), o.include_pinned, id="opt-pinned")
        yield Checkbox(t("Include packages with an unknown version"), o.include_unknown, id="opt-unknown")
        with Horizontal(classes="form-row"):
            yield Label(t("Custom arguments"), classes="form-label")
            yield Input(o.custom or "", id="opt-custom", placeholder=t("Added to the installer's arguments"))
        with Horizontal(classes="form-row"):
            yield Label(t("Override arguments"), classes="form-label")
            yield Input(o.override or "", id="opt-override", placeholder=t("Replaces the installer's arguments"))

    def value(self) -> UpgradeOptions:
        mode = self.query_one("#opt-mode", Select).value
        scope = self.query_one("#opt-scope", Select).value
        architecture = self.query_one("#opt-arch", Select).value
        return replace(
            self.options,
            silent=mode == "silent",
            interactive=mode == "interactive",
            scope=None if scope == "default" else scope,
            architecture=None if architecture == "default" else architecture,
            force=self.query_one("#opt-force", Checkbox).value,
            uninstall_previous=self.query_one("#opt-uninstall", Checkbox).value,
            skip_dependencies=self.query_one("#opt-skip-deps", Checkbox).value,
            include_pinned=self.query_one("#opt-pinned", Checkbox).value,
            include_unknown=self.query_one("#opt-unknown", Checkbox).value,
            custom=self.query_one("#opt-custom", Input).value.strip() or None,
            override=self.query_one("#opt-override", Input).value.strip() or None,
        )
