"""Named Python customization loaded locally, outside browser project data."""

from collections.abc import Callable
import importlib.util
from pathlib import Path
import re
from threading import RLock

from .drivers import SimulatorDriver


class Application:
    def __init__(self, driver: SimulatorDriver):
        self.driver = driver
        self.lock = RLock()
        self._actions: dict[str, tuple[str, Callable]] = {}
        self.register_action("toggle_motor", "Toggle simulated motor", self._toggle_motor)
        self.register_action("reset_level", "Reset simulated tank level", self._reset_level)
        self.register_action("toggle_alarm", "Toggle simulated process alarm", self._toggle_alarm)

    def register_action(self, name: str, label: str, callback: Callable):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,99}", name) or name in self._actions:
            raise ValueError(f"Invalid or duplicate action name: {name}")
        if not label or len(label) > 100 or not callable(callback):
            raise ValueError("Actions require a short label and a callable")
        self._actions[name] = (label, callback)

    def actions(self) -> list[dict]:
        return [{"name": name, "label": label} for name, (label, _) in self._actions.items()]

    def invoke(self, name: str):
        with self.lock:
            self._actions[name][1](self)

    @staticmethod
    def _toggle_motor(app):
        app.driver.write("MotorRunning", [not app.driver.read("MotorRunning")[0]])

    @staticmethod
    def _reset_level(app):
        app.driver.write("TankLevel", [0.0])

    @staticmethod
    def _toggle_alarm(app):
        app.driver.write("ProcessAlarm", [not app.driver.read("ProcessAlarm")[0]])

    def load_handlers(self, path: Path):
        spec = importlib.util.spec_from_file_location("openhmi_user_handlers", path.resolve())
        if spec is None or spec.loader is None:
            raise ValueError("Unable to load Python handler module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.register(self)
