"""Small typed read/write contract; subscription semantics are still planned."""

from typing import Protocol, TypeAlias
import math

Value: TypeAlias = bool | int | float | str


class Driver(Protocol):
    def read(self, address: str, count: int = 1) -> list[Value]: ...

    def write(self, address: str, values: list[Value]) -> None: ...


class SimulatorDriver:
    """In-memory scalar tags, with no network or controller connection."""

    def __init__(self) -> None:
        self._tags: dict[str, Value] = {"TankLevel": 42.0, "MotorRunning": True, "ProcessAlarm": False, "AlarmWord": 0}

    def read(self, address: str, count: int = 1) -> list[Value]:
        if type(count) is not int or count != 1:
            raise ValueError("The simulator supports one scalar per read")
        return [self._tags[address]]

    def write(self, address: str, values: list[Value]) -> None:
        current = self._tags[address]
        if len(values) != 1 or type(values[0]) is not type(current):
            raise ValueError("Write must contain one value of the tag's exact type")
        if isinstance(values[0], float) and not math.isfinite(values[0]):
            raise ValueError("Numeric values must be finite")
        self._tags[address] = values[0]

    def snapshot(self) -> dict[str, Value]:
        return self._tags.copy()
