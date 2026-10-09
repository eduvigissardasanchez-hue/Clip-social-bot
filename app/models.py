from dataclasses import dataclass
from enum import StrEnum

PLATFORMS = ("youtube", "instagram", "tiktok")

class State(StrEnum):
    LOCAL = "local"
    UPLOADED = "uploaded"
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    SENT = "sent"
    ERROR = "error"

@dataclass(frozen=True)
class Clip:
    sha256: str
    filename: str
    path: str
    position: int


def final_state(states):
    values = tuple(states)
    if len(values) != 3:
        raise ValueError("Se requieren los estados de las tres plataformas")
    if all(s == State.SENT for s in values):
        return State.SENT
    if State.ERROR in values:
        return State.ERROR
    if all(s in (State.SCHEDULED, State.SENT) for s in values):
        return State.SCHEDULED
    if State.QUEUED in values:
        return State.QUEUED
    if State.UPLOADED in values:
        return State.UPLOADED
    return State.LOCAL
