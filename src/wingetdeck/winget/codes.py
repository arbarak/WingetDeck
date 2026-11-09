"""What winget's exit codes mean for the person watching the run."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .code_table import CODES


class Outcome(Enum):
    SUCCESS = "success"
    SUCCESS_RESTART = "success_restart"
    SKIPPED = "skipped"
    FAILED = "failed"
    FAILED_IN_USE = "failed_in_use"
    FAILED_RESTART_FIRST = "failed_restart_first"


APP_IN_USE_CODE = 0x8A150101
_AGREEMENTS_CODE = 0x8A150041

_OUTCOMES = {
    0x8A150109: Outcome.SUCCESS_RESTART,  # finished, restart to complete
    0x8A15010B: Outcome.SUCCESS_RESTART,  # finished, PC restarting by itself
    0x8A15002B: Outcome.SKIPPED,  # no applicable upgrade
    0x8A150061: Outcome.SKIPPED,  # already installed
    0x8A150041: Outcome.SKIPPED,  # needs agreements the user has not accepted
    0x8A15010A: Outcome.FAILED_RESTART_FIRST,
    APP_IN_USE_CODE: Outcome.FAILED_IN_USE,
    0x8A150103: Outcome.FAILED_IN_USE,  # file in use
    0x8A150111: Outcome.FAILED_IN_USE,  # in use by an application
}


SOURCE_AGREEMENTS_NOT_ACCEPTED = 0x8A150046


@dataclass(frozen=True)
class Explanation:
    outcome: Outcome
    hex_code: str
    message: str


def explain(exit_code: int) -> Explanation:
    code = exit_code & 0xFFFFFFFF
    hex_code = f"0x{code:08X}"
    if code == 0:
        return Explanation(Outcome.SUCCESS, hex_code, "Upgraded")
    entry = CODES.get(code)
    if code == _AGREEMENTS_CODE:
        message = "This package has licence agreements. Turn on accepting agreements in Settings to upgrade it."
    elif entry:
        message = entry[1]
    else:
        message = f"winget stopped with an unknown code {hex_code}"
    return Explanation(_OUTCOMES.get(code, Outcome.FAILED), hex_code, message)
