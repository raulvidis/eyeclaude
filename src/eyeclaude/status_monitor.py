"""Monitors Claude Code instance statuses and manages flash transitions."""

import time

from eyeclaude.shared_state import SharedState, InstanceStatus


class StatusMonitor:
    def __init__(self, state: SharedState, flash_duration_ms: int = 2000):
        self._state = state
        self._flash_duration_s = flash_duration_ms / 1000.0
        # pid -> timestamp when FINISHED flash should end
        self._flash_timers: dict[int, float] = {}

    def on_status_change(self, pid: int, new_status: InstanceStatus) -> None:
        if new_status == InstanceStatus.FINISHED:
            self._flash_timers[pid] = time.monotonic() + self._flash_duration_s
        else:
            # Any other status cancels a pending flash
            self._flash_timers.pop(pid, None)

    def tick(self) -> None:
        """Called periodically to check if any FINISHED flashes have expired."""
        now = time.monotonic()
        expired = [pid for pid, deadline in self._flash_timers.items() if now >= deadline]
        for pid in expired:
            del self._flash_timers[pid]
            terminal = self._state.get_terminal(pid)
            if terminal and terminal.status == InstanceStatus.FINISHED:
                self._state.update_status(pid, InstanceStatus.IDLE)
