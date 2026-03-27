"""Thread-safe shared state between EyeClaude modules."""

import threading
from dataclasses import dataclass
from enum import Enum


class Quadrant(Enum):
    TOP_LEFT = "top-left"
    TOP_RIGHT = "top-right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_RIGHT = "bottom-right"


class InstanceStatus(Enum):
    IDLE = "idle"
    WORKING = "working"
    FINISHED = "finished"
    ERROR = "error"


@dataclass
class TerminalInfo:
    pid: int
    window_handle: int
    quadrant: Quadrant
    status: InstanceStatus = InstanceStatus.IDLE
    error_message: str = ""


class SharedState:
    def __init__(self):
        self._lock = threading.Lock()
        self._terminals: dict[int, TerminalInfo] = {}
        self._active_quadrant: Quadrant | None = None

    @property
    def active_quadrant(self) -> Quadrant | None:
        with self._lock:
            return self._active_quadrant

    @active_quadrant.setter
    def active_quadrant(self, quadrant: Quadrant | None) -> None:
        with self._lock:
            self._active_quadrant = quadrant

    def register_terminal(self, pid: int, window_handle: int, quadrant: Quadrant) -> None:
        with self._lock:
            self._terminals[pid] = TerminalInfo(
                pid=pid, window_handle=window_handle, quadrant=quadrant
            )

    def unregister_terminal(self, pid: int) -> None:
        with self._lock:
            self._terminals.pop(pid, None)

    def update_status(self, pid: int, status: InstanceStatus, error_message: str = "") -> None:
        with self._lock:
            if pid in self._terminals:
                self._terminals[pid].status = status
                self._terminals[pid].error_message = error_message

    def get_terminal(self, pid: int) -> TerminalInfo | None:
        with self._lock:
            info = self._terminals.get(pid)
            if info is None:
                return None
            return TerminalInfo(
                pid=info.pid,
                window_handle=info.window_handle,
                quadrant=info.quadrant,
                status=info.status,
                error_message=info.error_message,
            )

    def get_terminal_for_quadrant(self, quadrant: Quadrant) -> TerminalInfo | None:
        with self._lock:
            for info in self._terminals.values():
                if info.quadrant == quadrant:
                    return TerminalInfo(
                        pid=info.pid,
                        window_handle=info.window_handle,
                        quadrant=info.quadrant,
                        status=info.status,
                        error_message=info.error_message,
                    )
            return None

    def get_all_terminals(self) -> list[TerminalInfo]:
        with self._lock:
            return [
                TerminalInfo(
                    pid=info.pid,
                    window_handle=info.window_handle,
                    quadrant=info.quadrant,
                    status=info.status,
                    error_message=info.error_message,
                )
                for info in self._terminals.values()
            ]
