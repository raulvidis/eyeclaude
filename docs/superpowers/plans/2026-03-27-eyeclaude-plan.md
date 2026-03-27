# EyeClaude Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI app that tracks eye movement via webcam and switches focus between Claude Code terminal windows arranged in screen quadrants, with status-aware colored border overlays.

**Architecture:** Four concurrent threads (eye tracker, pipe server, overlay, main loop) communicating via thread-safe shared state. Claude Code integration via slash commands that register terminals and install hooks that emit status events over a Windows named pipe.

**Tech Stack:** Python 3.13, MediaPipe 0.10.33, OpenCV, pywin32, Click

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/eyeclaude/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "eyeclaude"
version = "0.1.0"
description = "Eye-tracking focus manager for Claude Code"
requires-python = ">=3.12"
dependencies = [
    "mediapipe>=0.10.33",
    "opencv-contrib-python>=4.8",
    "pywin32>=306",
    "click>=8.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.14",
]

[project.scripts]
eyeclaude = "eyeclaude.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Create __init__.py**

```python
"""EyeClaude — Eye-tracking focus manager for Claude Code."""
```

- [ ] **Step 3: Create virtual environment and install dependencies**

Run:
```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
```

Expected: All dependencies install successfully.

- [ ] **Step 4: Verify imports work**

Run:
```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
.venv/Scripts/python -c "import mediapipe; import cv2; import win32gui; import click; print('All imports OK')"
```

Expected: `All imports OK`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/eyeclaude/__init__.py
git commit -m "feat: project scaffolding with dependencies"
```

---

### Task 2: Configuration Module

**Files:**
- Create: `src/eyeclaude/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
import json
import os
from pathlib import Path

import pytest

from eyeclaude.config import EyeClaudeConfig, load_config, save_config, DEFAULT_CONFIG


class TestDefaultConfig:
    def test_default_dwell_time(self):
        config = EyeClaudeConfig()
        assert config.dwell_time_ms == 400

    def test_default_border_thickness(self):
        config = EyeClaudeConfig()
        assert config.border_thickness_px == 4

    def test_default_border_colors(self):
        config = EyeClaudeConfig()
        assert config.border_colors == {
            "idle": "#00FF00",
            "working": "#0088FF",
            "finished": "#FFD700",
            "error": "#FF0000",
        }

    def test_default_finished_flash_duration(self):
        config = EyeClaudeConfig()
        assert config.finished_flash_duration_ms == 2000

    def test_default_webcam_index(self):
        config = EyeClaudeConfig()
        assert config.webcam_index == 0


class TestConfigPersistence:
    def test_save_and_load(self, tmp_path):
        config_path = tmp_path / "config.json"
        config = EyeClaudeConfig(dwell_time_ms=600, webcam_index=2)
        save_config(config, config_path)

        loaded = load_config(config_path)
        assert loaded.dwell_time_ms == 600
        assert loaded.webcam_index == 2
        assert loaded.border_thickness_px == 4  # default preserved

    def test_load_missing_file_returns_default(self, tmp_path):
        config_path = tmp_path / "nonexistent.json"
        config = load_config(config_path)
        assert config.dwell_time_ms == 400

    def test_load_corrupt_file_returns_default(self, tmp_path):
        config_path = tmp_path / "bad.json"
        config_path.write_text("not valid json{{{")
        config = load_config(config_path)
        assert config.dwell_time_ms == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_config.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'eyeclaude.config'`

- [ ] **Step 3: Implement config module**

```python
# src/eyeclaude/config.py
"""Configuration loading and persistence for EyeClaude."""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".eyeclaude"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"

DEFAULT_BORDER_COLORS = {
    "idle": "#00FF00",
    "working": "#0088FF",
    "finished": "#FFD700",
    "error": "#FF0000",
}


@dataclass
class EyeClaudeConfig:
    dwell_time_ms: int = 400
    border_thickness_px: int = 4
    border_colors: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BORDER_COLORS))
    finished_flash_duration_ms: int = 2000
    webcam_index: int = 0


DEFAULT_CONFIG = EyeClaudeConfig()


def save_config(config: EyeClaudeConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2))


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> EyeClaudeConfig:
    try:
        data = json.loads(path.read_text())
        return EyeClaudeConfig(**{
            k: v for k, v in data.items()
            if k in EyeClaudeConfig.__dataclass_fields__
        })
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return EyeClaudeConfig()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_config.py -v`

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eyeclaude/config.py tests/test_config.py
git commit -m "feat: configuration module with persistence"
```

---

### Task 3: Shared State Module

**Files:**
- Create: `src/eyeclaude/shared_state.py`
- Create: `tests/test_shared_state.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_shared_state.py
import threading

from eyeclaude.shared_state import SharedState, Quadrant, InstanceStatus


class TestSharedState:
    def test_initial_state_has_no_active_quadrant(self):
        state = SharedState()
        assert state.active_quadrant is None

    def test_set_and_get_active_quadrant(self):
        state = SharedState()
        state.active_quadrant = Quadrant.TOP_LEFT
        assert state.active_quadrant == Quadrant.TOP_LEFT

    def test_register_terminal(self):
        state = SharedState()
        state.register_terminal(pid=1234, window_handle=5678, quadrant=Quadrant.TOP_RIGHT)
        terminal = state.get_terminal(pid=1234)
        assert terminal is not None
        assert terminal.window_handle == 5678
        assert terminal.quadrant == Quadrant.TOP_RIGHT
        assert terminal.status == InstanceStatus.IDLE

    def test_unregister_terminal(self):
        state = SharedState()
        state.register_terminal(pid=1234, window_handle=5678, quadrant=Quadrant.TOP_LEFT)
        state.unregister_terminal(pid=1234)
        assert state.get_terminal(pid=1234) is None

    def test_update_terminal_status(self):
        state = SharedState()
        state.register_terminal(pid=1234, window_handle=5678, quadrant=Quadrant.BOTTOM_LEFT)
        state.update_status(pid=1234, status=InstanceStatus.WORKING)
        assert state.get_terminal(pid=1234).status == InstanceStatus.WORKING

    def test_get_terminal_for_quadrant(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=10, quadrant=Quadrant.TOP_LEFT)
        state.register_terminal(pid=2, window_handle=20, quadrant=Quadrant.BOTTOM_RIGHT)
        terminal = state.get_terminal_for_quadrant(Quadrant.BOTTOM_RIGHT)
        assert terminal.pid == 2

    def test_get_terminal_for_empty_quadrant_returns_none(self):
        state = SharedState()
        assert state.get_terminal_for_quadrant(Quadrant.TOP_LEFT) is None

    def test_get_all_terminals(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=10, quadrant=Quadrant.TOP_LEFT)
        state.register_terminal(pid=2, window_handle=20, quadrant=Quadrant.TOP_RIGHT)
        terminals = state.get_all_terminals()
        assert len(terminals) == 2

    def test_thread_safety(self):
        state = SharedState()
        errors = []

        def register_many(start_pid):
            try:
                for i in range(100):
                    state.register_terminal(
                        pid=start_pid + i,
                        window_handle=start_pid + i,
                        quadrant=Quadrant.TOP_LEFT,
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_many, args=(i * 1000,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(state.get_all_terminals()) == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_shared_state.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement shared state module**

```python
# src/eyeclaude/shared_state.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_shared_state.py -v`

Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eyeclaude/shared_state.py tests/test_shared_state.py
git commit -m "feat: thread-safe shared state with terminal registry"
```

---

### Task 4: Named Pipe Server

**Files:**
- Create: `src/eyeclaude/pipe_server.py`
- Create: `tests/test_pipe_server.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipe_server.py
import json
import threading
import time

import pytest

from eyeclaude.pipe_server import PipeServer, PipeMessage, parse_message
from eyeclaude.shared_state import SharedState, Quadrant, InstanceStatus


class TestParseMessage:
    def test_parse_register(self):
        raw = '{"type": "register", "window_handle": 123, "pid": 456}'
        msg = parse_message(raw)
        assert msg.type == "register"
        assert msg.window_handle == 123
        assert msg.pid == 456

    def test_parse_unregister(self):
        raw = '{"type": "unregister", "pid": 456}'
        msg = parse_message(raw)
        assert msg.type == "unregister"
        assert msg.pid == 456

    def test_parse_status(self):
        raw = '{"type": "status", "pid": 456, "state": "working"}'
        msg = parse_message(raw)
        assert msg.type == "status"
        assert msg.pid == 456
        assert msg.state == "working"

    def test_parse_status_with_error_message(self):
        raw = '{"type": "status", "pid": 456, "state": "error", "message": "something broke"}'
        msg = parse_message(raw)
        assert msg.state == "error"
        assert msg.message == "something broke"

    def test_parse_invalid_json_raises(self):
        with pytest.raises(ValueError):
            parse_message("not json{{{")

    def test_parse_missing_type_raises(self):
        with pytest.raises(ValueError):
            parse_message('{"pid": 123}')


class TestPipeServerMessageHandling:
    def test_handle_register(self):
        state = SharedState()
        server = PipeServer(state, pipe_name=r"\\.\pipe\eyeclaude_test_reg")
        msg = parse_message('{"type": "register", "window_handle": 100, "pid": 200}')
        server.handle_message(msg)
        terminal = state.get_terminal(pid=200)
        assert terminal is not None
        assert terminal.window_handle == 100

    def test_handle_unregister(self):
        state = SharedState()
        server = PipeServer(state, pipe_name=r"\\.\pipe\eyeclaude_test_unreg")
        state.register_terminal(pid=200, window_handle=100, quadrant=Quadrant.TOP_LEFT)
        msg = parse_message('{"type": "unregister", "pid": 200}')
        server.handle_message(msg)
        assert state.get_terminal(pid=200) is None

    def test_handle_status_update(self):
        state = SharedState()
        server = PipeServer(state, pipe_name=r"\\.\pipe\eyeclaude_test_status")
        state.register_terminal(pid=200, window_handle=100, quadrant=Quadrant.TOP_LEFT)
        msg = parse_message('{"type": "status", "pid": 200, "state": "working"}')
        server.handle_message(msg)
        assert state.get_terminal(pid=200).status == InstanceStatus.WORKING

    def test_handle_error_status(self):
        state = SharedState()
        server = PipeServer(state, pipe_name=r"\\.\pipe\eyeclaude_test_err")
        state.register_terminal(pid=200, window_handle=100, quadrant=Quadrant.TOP_LEFT)
        msg = parse_message('{"type": "status", "pid": 200, "state": "error", "message": "fail"}')
        server.handle_message(msg)
        terminal = state.get_terminal(pid=200)
        assert terminal.status == InstanceStatus.ERROR
        assert terminal.error_message == "fail"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_pipe_server.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement pipe server**

```python
# src/eyeclaude/pipe_server.py
"""Named pipe server for receiving registration and status messages."""

import json
import logging
import struct
import threading
from dataclasses import dataclass

import win32api
import win32file
import win32pipe

from eyeclaude.shared_state import SharedState, InstanceStatus, Quadrant

logger = logging.getLogger(__name__)

PIPE_NAME = r"\\.\pipe\eyeclaude"
BUFFER_SIZE = 4096


@dataclass
class PipeMessage:
    type: str  # "register", "unregister", "status"
    pid: int = 0
    window_handle: int = 0
    state: str = ""
    message: str = ""


def parse_message(raw: str) -> PipeMessage:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    if "type" not in data:
        raise ValueError("Message missing 'type' field")

    return PipeMessage(
        type=data["type"],
        pid=data.get("pid", 0),
        window_handle=data.get("window_handle", 0),
        state=data.get("state", ""),
        message=data.get("message", ""),
    )


def _assign_quadrant_by_position(window_handle: int) -> Quadrant:
    """Determine which screen quadrant a window occupies based on its center position."""
    try:
        import win32gui
        left, top, right, bottom = win32gui.GetWindowRect(window_handle)
        center_x = (left + right) / 2
        center_y = (top + bottom) / 2

        screen_w = win32api.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_h = win32api.GetSystemMetrics(1)  # SM_CYSCREEN

        mid_x = screen_w / 2
        mid_y = screen_h / 2

        if center_x < mid_x:
            if center_y < mid_y:
                return Quadrant.TOP_LEFT
            return Quadrant.BOTTOM_LEFT
        else:
            if center_y < mid_y:
                return Quadrant.TOP_RIGHT
            return Quadrant.BOTTOM_RIGHT
    except Exception:
        logger.warning("Could not determine window position, defaulting to TOP_LEFT")
        return Quadrant.TOP_LEFT


STATUS_MAP = {
    "idle": InstanceStatus.IDLE,
    "working": InstanceStatus.WORKING,
    "finished": InstanceStatus.FINISHED,
    "error": InstanceStatus.ERROR,
}


class PipeServer:
    def __init__(self, state: SharedState, pipe_name: str = PIPE_NAME):
        self._state = state
        self._pipe_name = pipe_name
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        # Connect to our own pipe to unblock the waiting ConnectNamedPipe
        try:
            handle = win32file.CreateFile(
                self._pipe_name,
                win32file.GENERIC_WRITE,
                0, None,
                win32file.OPEN_EXISTING,
                0, None,
            )
            win32file.CloseHandle(handle)
        except Exception:
            pass

    def handle_message(self, msg: PipeMessage) -> None:
        if msg.type == "register":
            quadrant = _assign_quadrant_by_position(msg.window_handle)
            self._state.register_terminal(
                pid=msg.pid,
                window_handle=msg.window_handle,
                quadrant=quadrant,
            )
            logger.info(f"Registered terminal pid={msg.pid} in {quadrant.value}")

        elif msg.type == "unregister":
            self._state.unregister_terminal(pid=msg.pid)
            logger.info(f"Unregistered terminal pid={msg.pid}")

        elif msg.type == "status":
            status = STATUS_MAP.get(msg.state, InstanceStatus.IDLE)
            self._state.update_status(
                pid=msg.pid,
                status=status,
                error_message=msg.message,
            )
            logger.debug(f"Status update pid={msg.pid} -> {msg.state}")

    def _listen_loop(self) -> None:
        while self._running:
            try:
                pipe_handle = win32pipe.CreateNamedPipe(
                    self._pipe_name,
                    win32pipe.PIPE_ACCESS_INBOUND,
                    (
                        win32pipe.PIPE_TYPE_MESSAGE
                        | win32pipe.PIPE_READMODE_MESSAGE
                        | win32pipe.PIPE_WAIT
                    ),
                    win32pipe.PIPE_UNLIMITED_INSTANCES,
                    BUFFER_SIZE,
                    BUFFER_SIZE,
                    0,
                    None,
                )

                win32pipe.ConnectNamedPipe(pipe_handle, None)

                if not self._running:
                    win32file.CloseHandle(pipe_handle)
                    break

                data = b""
                while True:
                    try:
                        hr, chunk = win32file.ReadFile(pipe_handle, BUFFER_SIZE)
                        data += chunk
                        if hr == 0:
                            break
                    except Exception:
                        break

                win32file.CloseHandle(pipe_handle)

                if data:
                    try:
                        msg = parse_message(data.decode("utf-8"))
                        self.handle_message(msg)
                    except ValueError as e:
                        logger.warning(f"Bad message: {e}")

            except Exception as e:
                if self._running:
                    logger.error(f"Pipe error: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_pipe_server.py -v`

Expected: All 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eyeclaude/pipe_server.py tests/test_pipe_server.py
git commit -m "feat: named pipe server for registration and status events"
```

---

### Task 5: Status Monitor

**Files:**
- Create: `src/eyeclaude/status_monitor.py`
- Create: `tests/test_status_monitor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_status_monitor.py
import time

from eyeclaude.shared_state import SharedState, Quadrant, InstanceStatus
from eyeclaude.status_monitor import StatusMonitor


class TestStatusMonitor:
    def test_finished_flash_transitions_to_idle(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=10, quadrant=Quadrant.TOP_LEFT)
        monitor = StatusMonitor(state, flash_duration_ms=100)

        state.update_status(pid=1, status=InstanceStatus.FINISHED)
        monitor.on_status_change(pid=1, new_status=InstanceStatus.FINISHED)

        # Should still be FINISHED immediately
        assert state.get_terminal(pid=1).status == InstanceStatus.FINISHED

        # After the flash duration, should transition to IDLE
        time.sleep(0.2)
        monitor.tick()
        assert state.get_terminal(pid=1).status == InstanceStatus.IDLE

    def test_working_status_no_auto_transition(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=10, quadrant=Quadrant.TOP_LEFT)
        monitor = StatusMonitor(state, flash_duration_ms=100)

        state.update_status(pid=1, status=InstanceStatus.WORKING)
        monitor.on_status_change(pid=1, new_status=InstanceStatus.WORKING)

        time.sleep(0.2)
        monitor.tick()
        assert state.get_terminal(pid=1).status == InstanceStatus.WORKING

    def test_error_status_no_auto_transition(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=10, quadrant=Quadrant.TOP_LEFT)
        monitor = StatusMonitor(state, flash_duration_ms=100)

        state.update_status(pid=1, status=InstanceStatus.ERROR)
        monitor.on_status_change(pid=1, new_status=InstanceStatus.ERROR)

        time.sleep(0.2)
        monitor.tick()
        assert state.get_terminal(pid=1).status == InstanceStatus.ERROR

    def test_new_status_cancels_pending_flash(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=10, quadrant=Quadrant.TOP_LEFT)
        monitor = StatusMonitor(state, flash_duration_ms=500)

        # Trigger a flash
        monitor.on_status_change(pid=1, new_status=InstanceStatus.FINISHED)
        state.update_status(pid=1, status=InstanceStatus.FINISHED)

        # Before flash expires, change to WORKING
        time.sleep(0.05)
        monitor.on_status_change(pid=1, new_status=InstanceStatus.WORKING)
        state.update_status(pid=1, status=InstanceStatus.WORKING)

        # After flash would have expired, status should still be WORKING
        time.sleep(0.6)
        monitor.tick()
        assert state.get_terminal(pid=1).status == InstanceStatus.WORKING
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_status_monitor.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement status monitor**

```python
# src/eyeclaude/status_monitor.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_status_monitor.py -v`

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eyeclaude/status_monitor.py tests/test_status_monitor.py
git commit -m "feat: status monitor with finished flash timer"
```

---

### Task 6: Eye Tracker (MediaPipe Iris)

**Files:**
- Create: `src/eyeclaude/eye_tracker.py`
- Create: `tests/test_eye_tracker.py`

- [ ] **Step 1: Write the failing tests**

The eye tracker has two testable parts: the quadrant mapping logic (testable) and the webcam/MediaPipe capture (hardware-dependent, manual test only). We test the mapping logic.

```python
# tests/test_eye_tracker.py
from eyeclaude.eye_tracker import (
    map_gaze_to_quadrant,
    CalibrationData,
    DwellTracker,
)
from eyeclaude.shared_state import Quadrant


class TestMapGazeToQuadrant:
    def setup_method(self):
        # Simulated calibration: iris positions when looking at each quadrant center
        self.calibration = CalibrationData(
            points={
                Quadrant.TOP_LEFT: (0.3, 0.3),
                Quadrant.TOP_RIGHT: (0.7, 0.3),
                Quadrant.BOTTOM_LEFT: (0.3, 0.7),
                Quadrant.BOTTOM_RIGHT: (0.7, 0.7),
            }
        )

    def test_gaze_near_top_left(self):
        result = map_gaze_to_quadrant((0.32, 0.28), self.calibration)
        assert result == Quadrant.TOP_LEFT

    def test_gaze_near_top_right(self):
        result = map_gaze_to_quadrant((0.68, 0.31), self.calibration)
        assert result == Quadrant.TOP_RIGHT

    def test_gaze_near_bottom_left(self):
        result = map_gaze_to_quadrant((0.29, 0.72), self.calibration)
        assert result == Quadrant.BOTTOM_LEFT

    def test_gaze_near_bottom_right(self):
        result = map_gaze_to_quadrant((0.71, 0.69), self.calibration)
        assert result == Quadrant.BOTTOM_RIGHT

    def test_gaze_at_exact_calibration_point(self):
        result = map_gaze_to_quadrant((0.3, 0.3), self.calibration)
        assert result == Quadrant.TOP_LEFT

    def test_gaze_at_center_returns_nearest(self):
        # Dead center (0.5, 0.5) is equidistant from all — any quadrant is acceptable
        result = map_gaze_to_quadrant((0.5, 0.5), self.calibration)
        assert result in list(Quadrant)


class TestDwellTracker:
    def test_no_dwell_on_first_gaze(self):
        tracker = DwellTracker(dwell_time_ms=400)
        result = tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        assert result is None

    def test_dwell_activates_after_duration(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        result = tracker.update(Quadrant.TOP_LEFT, timestamp_ms=500)
        assert result == Quadrant.TOP_LEFT

    def test_dwell_resets_on_quadrant_change(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        tracker.update(Quadrant.TOP_RIGHT, timestamp_ms=300)
        result = tracker.update(Quadrant.TOP_RIGHT, timestamp_ms=600)
        # 600 - 300 = 300ms, not enough yet
        assert result is None

    def test_dwell_activates_after_reset_and_enough_time(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        tracker.update(Quadrant.TOP_RIGHT, timestamp_ms=300)
        result = tracker.update(Quadrant.TOP_RIGHT, timestamp_ms=800)
        # 800 - 300 = 500ms, enough
        assert result == Quadrant.TOP_RIGHT

    def test_none_gaze_does_not_activate(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        result = tracker.update(None, timestamp_ms=500)
        assert result is None

    def test_does_not_re_trigger_same_quadrant(self):
        tracker = DwellTracker(dwell_time_ms=400)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=0)
        tracker.update(Quadrant.TOP_LEFT, timestamp_ms=500)  # activates
        result = tracker.update(Quadrant.TOP_LEFT, timestamp_ms=1000)
        # Should not re-trigger since we're already focused here
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_eye_tracker.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement eye tracker**

```python
# src/eyeclaude/eye_tracker.py
"""MediaPipe iris tracking and gaze-to-quadrant mapping."""

import logging
import math
import threading
import time
from dataclasses import dataclass, field

import cv2
import mediapipe as mp

from eyeclaude.shared_state import Quadrant, SharedState

logger = logging.getLogger(__name__)

# MediaPipe iris landmark indices (refine_landmarks=True required)
LEFT_IRIS_CENTER = 468
RIGHT_IRIS_CENTER = 473


@dataclass
class CalibrationData:
    """Maps each quadrant to its calibrated iris position (normalized x, y)."""
    points: dict[Quadrant, tuple[float, float]] = field(default_factory=dict)


def map_gaze_to_quadrant(
    gaze: tuple[float, float], calibration: CalibrationData
) -> Quadrant:
    """Find the nearest calibrated quadrant to the current gaze position."""
    gx, gy = gaze
    best_quadrant = Quadrant.TOP_LEFT
    best_dist = float("inf")

    for quadrant, (cx, cy) in calibration.points.items():
        dist = math.hypot(gx - cx, gy - cy)
        if dist < best_dist:
            best_dist = dist
            best_quadrant = quadrant

    return best_quadrant


class DwellTracker:
    """Tracks gaze dwell time to avoid accidental focus switches."""

    def __init__(self, dwell_time_ms: int = 400):
        self._dwell_time_ms = dwell_time_ms
        self._current_quadrant: Quadrant | None = None
        self._dwell_start_ms: float = 0
        self._last_activated: Quadrant | None = None

    def update(
        self, quadrant: Quadrant | None, timestamp_ms: float
    ) -> Quadrant | None:
        """Update with current gaze quadrant. Returns quadrant if dwell threshold met."""
        if quadrant is None:
            self._current_quadrant = None
            return None

        if quadrant != self._current_quadrant:
            self._current_quadrant = quadrant
            self._dwell_start_ms = timestamp_ms
            return None

        elapsed = timestamp_ms - self._dwell_start_ms
        if elapsed >= self._dwell_time_ms and quadrant != self._last_activated:
            self._last_activated = quadrant
            return quadrant

        return None


def _get_iris_center(landmarks) -> tuple[float, float] | None:
    """Extract averaged iris center from both eyes."""
    try:
        left = landmarks[LEFT_IRIS_CENTER]
        right = landmarks[RIGHT_IRIS_CENTER]
        return ((left.x + right.x) / 2, (left.y + right.y) / 2)
    except (IndexError, AttributeError):
        return None


class EyeTracker:
    """Captures webcam feed and tracks iris position using MediaPipe."""

    def __init__(
        self,
        state: SharedState,
        calibration: CalibrationData,
        dwell_time_ms: int = 400,
        webcam_index: int = 0,
    ):
        self._state = state
        self._calibration = calibration
        self._dwell = DwellTracker(dwell_time_ms=dwell_time_ms)
        self._webcam_index = webcam_index
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._track_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _track_loop(self) -> None:
        cap = cv2.VideoCapture(self._webcam_index)
        if not cap.isOpened():
            logger.error("Cannot open webcam %d", self._webcam_index)
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        mp_face_mesh = mp.solutions.face_mesh

        with mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        ) as face_mesh:
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    continue

                frame = cv2.flip(frame, 1)  # Mirror for natural feel
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb)

                gaze = None
                if results.multi_face_landmarks:
                    landmarks = results.multi_face_landmarks[0].landmark
                    gaze = _get_iris_center(landmarks)

                timestamp_ms = time.monotonic() * 1000
                quadrant = None
                if gaze and self._calibration.points:
                    quadrant = map_gaze_to_quadrant(gaze, self._calibration)

                activated = self._dwell.update(quadrant, timestamp_ms)
                if activated:
                    self._state.active_quadrant = activated

        cap.release()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_eye_tracker.py -v`

Expected: All 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eyeclaude/eye_tracker.py tests/test_eye_tracker.py
git commit -m "feat: eye tracker with iris detection and dwell-based quadrant mapping"
```

---

### Task 7: Calibration Engine

**Files:**
- Create: `src/eyeclaude/calibration.py`
- Create: `tests/test_calibration.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_calibration.py
import json

from eyeclaude.calibration import save_calibration, load_calibration
from eyeclaude.eye_tracker import CalibrationData
from eyeclaude.shared_state import Quadrant


class TestCalibrationPersistence:
    def test_save_and_load(self, tmp_path):
        path = tmp_path / "calibration.json"
        data = CalibrationData(points={
            Quadrant.TOP_LEFT: (0.3, 0.3),
            Quadrant.TOP_RIGHT: (0.7, 0.3),
            Quadrant.BOTTOM_LEFT: (0.3, 0.7),
            Quadrant.BOTTOM_RIGHT: (0.7, 0.7),
        })
        save_calibration(data, path)
        loaded = load_calibration(path)
        assert loaded.points[Quadrant.TOP_LEFT] == (0.3, 0.3)
        assert loaded.points[Quadrant.BOTTOM_RIGHT] == (0.7, 0.7)
        assert len(loaded.points) == 4

    def test_load_missing_file_returns_empty(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        data = load_calibration(path)
        assert len(data.points) == 0

    def test_load_corrupt_file_returns_empty(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json{{{")
        data = load_calibration(path)
        assert len(data.points) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_calibration.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement calibration module**

```python
# src/eyeclaude/calibration.py
"""Calibration flow and persistence for EyeClaude."""

import json
import logging
import time
from pathlib import Path

import cv2
import mediapipe as mp

from eyeclaude.eye_tracker import CalibrationData, _get_iris_center
from eyeclaude.shared_state import Quadrant

logger = logging.getLogger(__name__)

DEFAULT_CALIBRATION_PATH = Path.home() / ".eyeclaude" / "calibration.json"

QUADRANT_ORDER = [
    Quadrant.TOP_LEFT,
    Quadrant.TOP_RIGHT,
    Quadrant.BOTTOM_LEFT,
    Quadrant.BOTTOM_RIGHT,
]

QUADRANT_LABELS = {
    Quadrant.TOP_LEFT: "TOP-LEFT",
    Quadrant.TOP_RIGHT: "TOP-RIGHT",
    Quadrant.BOTTOM_LEFT: "BOTTOM-LEFT",
    Quadrant.BOTTOM_RIGHT: "BOTTOM-RIGHT",
}


def save_calibration(data: CalibrationData, path: Path = DEFAULT_CALIBRATION_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = {q.value: list(pos) for q, pos in data.points.items()}
    path.write_text(json.dumps(serialized, indent=2))


def load_calibration(path: Path = DEFAULT_CALIBRATION_PATH) -> CalibrationData:
    try:
        raw = json.loads(path.read_text())
        points = {}
        for q in Quadrant:
            if q.value in raw:
                x, y = raw[q.value]
                points[q] = (float(x), float(y))
        return CalibrationData(points=points)
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return CalibrationData()


def _quadrant_screen_center(quadrant: Quadrant, screen_w: int, screen_h: int) -> tuple[int, int]:
    """Get the pixel center of a quadrant on screen."""
    half_w = screen_w // 2
    half_h = screen_h // 2
    centers = {
        Quadrant.TOP_LEFT: (half_w // 2, half_h // 2),
        Quadrant.TOP_RIGHT: (half_w + half_w // 2, half_h // 2),
        Quadrant.BOTTOM_LEFT: (half_w // 2, half_h + half_h // 2),
        Quadrant.BOTTOM_RIGHT: (half_w + half_w // 2, half_h + half_h // 2),
    }
    return centers[quadrant]


def run_calibration(webcam_index: int = 0) -> CalibrationData | None:
    """Run interactive calibration. Returns CalibrationData or None if cancelled."""
    import win32api
    import win32con

    screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

    cap = cv2.VideoCapture(webcam_index)
    if not cap.isOpened():
        logger.error("Cannot open webcam %d", webcam_index)
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    mp_face_mesh = mp.solutions.face_mesh
    calibration = CalibrationData()

    window_name = "EyeClaude Calibration"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    with mp_face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as face_mesh:

        for quadrant in QUADRANT_ORDER:
            dot_x, dot_y = _quadrant_screen_center(quadrant, screen_w, screen_h)
            label = QUADRANT_LABELS[quadrant]
            collecting = True

            while collecting:
                ret, frame = cap.read()
                if not ret:
                    continue

                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb)

                # Draw calibration screen
                canvas = cv2.Mat(screen_h, screen_w, cv2.CV_8UC3) if hasattr(cv2, 'Mat') else \
                    __import__('numpy').zeros((screen_h, screen_w, 3), dtype=__import__('numpy').uint8)

                # Draw all dots (grey for pending, green for current)
                for q in QUADRANT_ORDER:
                    dx, dy = _quadrant_screen_center(q, screen_w, screen_h)
                    color = (0, 255, 0) if q == quadrant else (80, 80, 80)
                    # Draw completed dots in blue
                    if q in calibration.points:
                        color = (255, 150, 0)
                    if q == quadrant:
                        color = (0, 255, 0)
                    cv2.circle(canvas, (dx, dy), 20, color, -1)

                # Instructions
                cv2.putText(
                    canvas,
                    f"Look at the GREEN dot ({label}) and press SPACE",
                    (screen_w // 2 - 350, screen_h - 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2,
                )
                cv2.putText(
                    canvas,
                    "Press ESC to cancel",
                    (screen_w // 2 - 150, screen_h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1,
                )

                cv2.imshow(window_name, canvas)
                key = cv2.waitKey(1) & 0xFF

                if key == 27:  # ESC
                    cap.release()
                    cv2.destroyAllWindows()
                    return None

                if key == 32:  # SPACE
                    if results.multi_face_landmarks:
                        landmarks = results.multi_face_landmarks[0].landmark
                        iris_pos = _get_iris_center(landmarks)
                        if iris_pos:
                            calibration.points[quadrant] = iris_pos
                            logger.info(f"Calibrated {label}: {iris_pos}")
                            collecting = False
                        else:
                            logger.warning("No iris detected — try again")
                    else:
                        logger.warning("No face detected — try again")

    cap.release()
    cv2.destroyAllWindows()

    save_calibration(calibration)
    return calibration
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_calibration.py -v`

Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eyeclaude/calibration.py tests/test_calibration.py
git commit -m "feat: calibration engine with persistence and interactive flow"
```

---

### Task 8: Overlay (Win32 Transparent Window)

**Files:**
- Create: `src/eyeclaude/overlay.py`
- Create: `tests/test_overlay.py`

- [ ] **Step 1: Write the failing tests**

The overlay is mostly Win32 UI code. We test the border computation logic.

```python
# tests/test_overlay.py
from eyeclaude.overlay import compute_quadrant_rect
from eyeclaude.shared_state import Quadrant


class TestComputeQuadrantRect:
    def test_top_left(self):
        x, y, w, h = compute_quadrant_rect(Quadrant.TOP_LEFT, 1920, 1080)
        assert x == 0
        assert y == 0
        assert w == 960
        assert h == 540

    def test_top_right(self):
        x, y, w, h = compute_quadrant_rect(Quadrant.TOP_RIGHT, 1920, 1080)
        assert x == 960
        assert y == 0
        assert w == 960
        assert h == 540

    def test_bottom_left(self):
        x, y, w, h = compute_quadrant_rect(Quadrant.BOTTOM_LEFT, 1920, 1080)
        assert x == 0
        assert y == 540
        assert w == 960
        assert h == 540

    def test_bottom_right(self):
        x, y, w, h = compute_quadrant_rect(Quadrant.BOTTOM_RIGHT, 1920, 1080)
        assert x == 960
        assert y == 540
        assert w == 960
        assert h == 540

    def test_odd_resolution(self):
        x, y, w, h = compute_quadrant_rect(Quadrant.TOP_LEFT, 1921, 1081)
        assert x == 0
        assert y == 0
        assert w == 960
        assert h == 540
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_overlay.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement overlay module**

```python
# src/eyeclaude/overlay.py
"""Transparent click-through overlay for drawing colored borders around quadrants."""

import ctypes
import ctypes.wintypes
import logging
import threading
import time

import win32api
import win32con
import win32gui

from eyeclaude.shared_state import Quadrant, InstanceStatus, SharedState

logger = logging.getLogger(__name__)

TRANSPARENT_COLOR = win32api.RGB(255, 0, 255)  # Magenta = transparent
WM_USER_UPDATE = win32con.WM_USER + 1
PS_INSIDEFRAME = 6
NULL_BRUSH = 5


def compute_quadrant_rect(
    quadrant: Quadrant, screen_w: int, screen_h: int
) -> tuple[int, int, int, int]:
    """Return (x, y, width, height) for a quadrant."""
    half_w = screen_w // 2
    half_h = screen_h // 2
    rects = {
        Quadrant.TOP_LEFT: (0, 0, half_w, half_h),
        Quadrant.TOP_RIGHT: (half_w, 0, screen_w - half_w, half_h),
        Quadrant.BOTTOM_LEFT: (0, half_h, half_w, screen_h - half_h),
        Quadrant.BOTTOM_RIGHT: (half_w, half_h, screen_w - half_w, screen_h - half_h),
    }
    return rects[quadrant]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert '#RRGGBB' to (R, G, B)."""
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _status_to_color(
    status: InstanceStatus, border_colors: dict[str, str], pulse_phase: float
) -> int:
    """Convert status to a win32 RGB color value."""
    if status == InstanceStatus.WORKING:
        # Pulsing blue: oscillate brightness
        r, g, b = _hex_to_rgb(border_colors["working"])
        factor = 0.5 + 0.5 * abs((pulse_phase % 1.0) * 2 - 1)
        return win32api.RGB(int(r * factor), int(g * factor), int(b * factor))

    color_key = {
        InstanceStatus.IDLE: "idle",
        InstanceStatus.FINISHED: "finished",
        InstanceStatus.ERROR: "error",
    }.get(status, "idle")

    r, g, b = _hex_to_rgb(border_colors[color_key])
    return win32api.RGB(r, g, b)


class Overlay:
    """Transparent, click-through, always-on-top overlay that draws colored borders."""

    CLASS_NAME = "EyeClaudeOverlay"

    def __init__(self, state: SharedState, border_colors: dict[str, str], border_thickness: int = 4):
        self._state = state
        self._border_colors = border_colors
        self._border_thickness = border_thickness
        self._hwnd = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._running = False
        self._pulse_phase = 0.0

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self) -> None:
        self._running = False
        if self._hwnd:
            win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
        if self._thread:
            self._thread.join(timeout=3)

    def request_repaint(self) -> None:
        if self._hwnd:
            win32gui.PostMessage(self._hwnd, WM_USER_UPDATE, 0, 0)

    def _run(self) -> None:
        hinstance = win32api.GetModuleHandle(None)

        wc = win32gui.WNDCLASS()
        wc.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
        wc.lpfnWndProc = self._wnd_proc
        wc.hInstance = hinstance
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32gui.GetStockObject(NULL_BRUSH)
        wc.lpszClassName = self.CLASS_NAME

        try:
            win32gui.RegisterClass(wc)
        except win32gui.error:
            pass

        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        ex_style = (
            win32con.WS_EX_LAYERED
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_TOPMOST
            | win32con.WS_EX_TOOLWINDOW
        )

        self._hwnd = win32gui.CreateWindowEx(
            ex_style,
            self.CLASS_NAME,
            "EyeClaude Overlay",
            win32con.WS_POPUP,
            0, 0, screen_w, screen_h,
            0, 0, hinstance, None,
        )

        win32gui.SetLayeredWindowAttributes(
            self._hwnd, TRANSPARENT_COLOR, 0, win32con.LWA_COLORKEY,
        )

        win32gui.ShowWindow(self._hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.UpdateWindow(self._hwnd)

        # Set a timer for periodic repaint (for pulsing animation + state updates)
        TIMER_ID = 1
        ctypes.windll.user32.SetTimer(self._hwnd, TIMER_ID, 50, None)  # 50ms = 20fps

        self._ready.set()

        msg = ctypes.wintypes.MSG()
        while self._running:
            result = ctypes.windll.user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if result <= 0:
                break
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_PAINT:
            self._on_paint(hwnd)
            return 0

        if msg == WM_USER_UPDATE or msg == win32con.WM_TIMER:
            self._pulse_phase += 0.05
            win32gui.InvalidateRect(hwnd, None, True)
            return 0

        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _on_paint(self, hwnd):
        hdc, ps = win32gui.BeginPaint(hwnd)
        rect = win32gui.GetClientRect(hwnd)
        screen_w = rect[2]
        screen_h = rect[3]

        # Fill with transparent color
        brush = win32gui.CreateSolidBrush(TRANSPARENT_COLOR)
        win32gui.FillRect(hdc, rect, brush)
        win32gui.DeleteObject(brush)

        # Draw borders for registered terminals
        old_brush = win32gui.SelectObject(hdc, win32gui.GetStockObject(NULL_BRUSH))

        active_quadrant = self._state.active_quadrant
        terminals = self._state.get_all_terminals()

        for terminal in terminals:
            if terminal.quadrant != active_quadrant:
                continue

            x, y, w, h = compute_quadrant_rect(terminal.quadrant, screen_w, screen_h)
            color = _status_to_color(
                terminal.status, self._border_colors, self._pulse_phase
            )
            pen = win32gui.CreatePen(PS_INSIDEFRAME, self._border_thickness, color)
            old_pen = win32gui.SelectObject(hdc, pen)
            win32gui.Rectangle(hdc, x, y, x + w, y + h)
            win32gui.SelectObject(hdc, old_pen)
            win32gui.DeleteObject(pen)

        win32gui.SelectObject(hdc, old_brush)
        win32gui.EndPaint(hwnd, ps)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_overlay.py -v`

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eyeclaude/overlay.py tests/test_overlay.py
git commit -m "feat: transparent click-through overlay with status-colored borders"
```

---

### Task 9: Window Manager (Focus Switching)

**Files:**
- Create: `src/eyeclaude/window_manager.py`
- Create: `tests/test_window_manager.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_window_manager.py
from unittest.mock import patch, MagicMock

from eyeclaude.shared_state import SharedState, Quadrant, InstanceStatus
from eyeclaude.window_manager import WindowManager


class TestWindowManager:
    def test_focus_switches_on_new_quadrant(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=111, quadrant=Quadrant.TOP_LEFT)
        manager = WindowManager(state)

        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus:
            manager.update_focus(Quadrant.TOP_LEFT)
            mock_focus.assert_called_once_with(111)

    def test_no_switch_when_same_quadrant(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=111, quadrant=Quadrant.TOP_LEFT)
        manager = WindowManager(state)

        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus:
            manager.update_focus(Quadrant.TOP_LEFT)
            manager.update_focus(Quadrant.TOP_LEFT)
            # Should only be called once
            assert mock_focus.call_count == 1

    def test_switch_to_different_quadrant(self):
        state = SharedState()
        state.register_terminal(pid=1, window_handle=111, quadrant=Quadrant.TOP_LEFT)
        state.register_terminal(pid=2, window_handle=222, quadrant=Quadrant.TOP_RIGHT)
        manager = WindowManager(state)

        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus:
            manager.update_focus(Quadrant.TOP_LEFT)
            manager.update_focus(Quadrant.TOP_RIGHT)
            assert mock_focus.call_count == 2
            mock_focus.assert_called_with(222)

    def test_no_switch_when_no_terminal_in_quadrant(self):
        state = SharedState()
        manager = WindowManager(state)

        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus:
            manager.update_focus(Quadrant.TOP_LEFT)
            mock_focus.assert_not_called()

    def test_none_quadrant_does_nothing(self):
        state = SharedState()
        manager = WindowManager(state)

        with patch("eyeclaude.window_manager.set_foreground_window") as mock_focus:
            manager.update_focus(None)
            mock_focus.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_window_manager.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement window manager**

```python
# src/eyeclaude/window_manager.py
"""Win32 window focus management."""

import logging

import win32gui
import win32con

from eyeclaude.shared_state import SharedState, Quadrant

logger = logging.getLogger(__name__)


def set_foreground_window(hwnd: int) -> None:
    """Attempt to bring a window to the foreground."""
    try:
        # Windows restricts SetForegroundWindow — use AllowSetForegroundWindow workaround
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        logger.warning("Failed to set foreground window %d: %s", hwnd, e)


class WindowManager:
    """Manages focus switching between registered terminal windows."""

    def __init__(self, state: SharedState):
        self._state = state
        self._current_quadrant: Quadrant | None = None

    def update_focus(self, quadrant: Quadrant | None) -> None:
        """Switch focus to the terminal in the given quadrant, if different from current."""
        if quadrant is None:
            return

        if quadrant == self._current_quadrant:
            return

        terminal = self._state.get_terminal_for_quadrant(quadrant)
        if terminal is None:
            return

        self._current_quadrant = quadrant
        set_foreground_window(terminal.window_handle)
        logger.debug("Focused quadrant %s (hwnd=%d)", quadrant.value, terminal.window_handle)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_window_manager.py -v`

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eyeclaude/window_manager.py tests/test_window_manager.py
git commit -m "feat: window manager with dwell-based focus switching"
```

---

### Task 10: CLI (Click Entry Point)

**Files:**
- Create: `src/eyeclaude/cli.py`

- [ ] **Step 1: Implement CLI**

```python
# src/eyeclaude/cli.py
"""CLI entry point for EyeClaude."""

import json
import logging
import signal
import sys
import threading
import time
from pathlib import Path

import click
import win32file
import win32pipe

from eyeclaude.calibration import load_calibration, run_calibration, DEFAULT_CALIBRATION_PATH
from eyeclaude.config import load_config, save_config, EyeClaudeConfig, DEFAULT_CONFIG_PATH
from eyeclaude.eye_tracker import EyeTracker
from eyeclaude.overlay import Overlay
from eyeclaude.pipe_server import PipeServer, PIPE_NAME
from eyeclaude.shared_state import SharedState
from eyeclaude.status_monitor import StatusMonitor
from eyeclaude.window_manager import WindowManager

logger = logging.getLogger("eyeclaude")


@click.group()
def main():
    """EyeClaude — Eye-tracking focus manager for Claude Code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@main.command()
def start():
    """Launch EyeClaude (webcam + eye tracking + pipe listener + overlay)."""
    config = load_config()
    calibration = load_calibration()

    if not calibration.points:
        click.echo("No calibration data found. Running calibration first...")
        calibration = run_calibration(webcam_index=config.webcam_index)
        if calibration is None:
            click.echo("Calibration cancelled. Exiting.")
            return

    state = SharedState()
    status_monitor = StatusMonitor(state, flash_duration_ms=config.finished_flash_duration_ms)

    # Wire status monitor into pipe server's message handling
    pipe_server = PipeServer(state)
    original_handle = pipe_server.handle_message

    def handle_with_monitor(msg):
        original_handle(msg)
        if msg.type == "status":
            from eyeclaude.shared_state import InstanceStatus
            status_map = {"idle": InstanceStatus.IDLE, "working": InstanceStatus.WORKING,
                          "finished": InstanceStatus.FINISHED, "error": InstanceStatus.ERROR}
            status = status_map.get(msg.state, InstanceStatus.IDLE)
            status_monitor.on_status_change(pid=msg.pid, new_status=status)

    pipe_server.handle_message = handle_with_monitor

    eye_tracker = EyeTracker(
        state=state,
        calibration=calibration,
        dwell_time_ms=config.dwell_time_ms,
        webcam_index=config.webcam_index,
    )
    overlay = Overlay(
        state=state,
        border_colors=config.border_colors,
        border_thickness=config.border_thickness_px,
    )
    window_manager = WindowManager(state)

    # Start all components
    pipe_server.start()
    eye_tracker.start()
    overlay.start()

    click.echo("EyeClaude started. Press Ctrl+C to stop.")
    click.echo(f"Listening on pipe: {PIPE_NAME}")
    click.echo(f"Registered quadrants: {len(calibration.points)}")

    stop_event = threading.Event()

    def handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Main loop: update focus + status monitor tick
    try:
        while not stop_event.is_set():
            active = state.active_quadrant
            window_manager.update_focus(active)
            status_monitor.tick()
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass

    click.echo("\nShutting down...")
    eye_tracker.stop()
    overlay.stop()
    pipe_server.stop()
    click.echo("EyeClaude stopped.")


@main.command()
def stop():
    """Send stop signal to a running EyeClaude instance."""
    try:
        _send_pipe_message({"type": "shutdown"})
        click.echo("Stop signal sent.")
    except Exception as e:
        click.echo(f"Could not connect to EyeClaude: {e}")


@main.command()
def calibrate():
    """Run or re-run eye tracking calibration."""
    config = load_config()
    click.echo("Starting calibration...")
    result = run_calibration(webcam_index=config.webcam_index)
    if result:
        click.echo(f"Calibration saved to {DEFAULT_CALIBRATION_PATH}")
    else:
        click.echo("Calibration cancelled.")


@main.command()
def status():
    """Show registered terminals and their current states."""
    click.echo("Note: Status is only available when queried from the running process.")
    click.echo("This command currently verifies the pipe is reachable.")
    try:
        handle = win32file.CreateFile(
            PIPE_NAME,
            win32file.GENERIC_WRITE,
            0, None,
            win32file.OPEN_EXISTING,
            0, None,
        )
        win32file.CloseHandle(handle)
        click.echo("EyeClaude is running and reachable.")
    except Exception:
        click.echo("EyeClaude is not running.")


@main.command()
@click.option("--dwell-time", type=int, help="Dwell time in ms")
@click.option("--border-thickness", type=int, help="Border thickness in px")
@click.option("--webcam-index", type=int, help="Webcam device index")
def config(dwell_time, border_thickness, webcam_index):
    """View or adjust EyeClaude configuration."""
    cfg = load_config()

    if dwell_time is None and border_thickness is None and webcam_index is None:
        click.echo(json.dumps({
            "dwell_time_ms": cfg.dwell_time_ms,
            "border_thickness_px": cfg.border_thickness_px,
            "border_colors": cfg.border_colors,
            "finished_flash_duration_ms": cfg.finished_flash_duration_ms,
            "webcam_index": cfg.webcam_index,
        }, indent=2))
        return

    if dwell_time is not None:
        cfg.dwell_time_ms = dwell_time
    if border_thickness is not None:
        cfg.border_thickness_px = border_thickness
    if webcam_index is not None:
        cfg.webcam_index = webcam_index

    save_config(cfg)
    click.echo(f"Configuration saved to {DEFAULT_CONFIG_PATH}")


@main.command()
def register():
    """Register the current terminal with EyeClaude and install Claude Code hooks."""
    import os
    import win32console

    pid = os.getpid()

    # Get the console window handle
    hwnd = win32console.GetConsoleWindow()
    if not hwnd:
        click.echo("Error: Could not determine console window handle.")
        return

    try:
        _send_pipe_message({
            "type": "register",
            "window_handle": hwnd,
            "pid": pid,
        })
        click.echo(f"Registered with EyeClaude (pid={pid}, hwnd={hwnd})")
    except Exception as e:
        click.echo(f"Failed to register: {e}. Is EyeClaude running?")
        return

    # Install Claude Code hooks in project-local settings
    _install_claude_hooks()
    click.echo("Claude Code status hooks installed.")


def _install_claude_hooks():
    """Write Claude Code hooks to .claude/settings.local.json for status reporting."""
    settings_dir = Path(".claude")
    settings_dir.mkdir(exist_ok=True)
    settings_path = settings_dir / "settings.local.json"

    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            settings = {}

    settings["hooks"] = {
        "PreToolUse": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "eyeclaude-hooks status working",
                    }
                ]
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "eyeclaude-hooks status finished",
                    }
                ]
            }
        ],
        "StopFailure": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "eyeclaude-hooks status error",
                    }
                ]
            }
        ],
        "UserPromptSubmit": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "eyeclaude-hooks status idle",
                    }
                ]
            }
        ],
    }

    settings_path.write_text(json.dumps(settings, indent=2))


@main.command()
def unregister():
    """Unregister the current terminal from EyeClaude."""
    import os

    pid = os.getpid()
    try:
        _send_pipe_message({"type": "unregister", "pid": pid})
        click.echo(f"Unregistered from EyeClaude (pid={pid})")
    except Exception as e:
        click.echo(f"Failed to unregister: {e}. Is EyeClaude running?")


def _send_pipe_message(data: dict) -> None:
    """Send a JSON message to the EyeClaude named pipe."""
    handle = win32file.CreateFile(
        PIPE_NAME,
        win32file.GENERIC_WRITE,
        0, None,
        win32file.OPEN_EXISTING,
        0, None,
    )
    try:
        message = json.dumps(data).encode("utf-8")
        win32file.WriteFile(handle, message)
    finally:
        win32file.CloseHandle(handle)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify CLI loads**

Run:
```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
.venv/Scripts/eyeclaude --help
```

Expected:
```
Usage: eyeclaude [OPTIONS] COMMAND [ARGS]...

  EyeClaude — Eye-tracking focus manager for Claude Code.

Options:
  --help  Show this message and exit.

Commands:
  calibrate   Run or re-run eye tracking calibration.
  config      View or adjust EyeClaude configuration.
  register    Register the current terminal with EyeClaude.
  start       Launch EyeClaude (webcam + eye tracking + pipe listener + overlay).
  status      Show registered terminals and their current states.
  stop        Send stop signal to a running EyeClaude instance.
  unregister  Unregister the current terminal from EyeClaude.
```

- [ ] **Step 3: Commit**

```bash
git add src/eyeclaude/cli.py
git commit -m "feat: CLI entry point with all commands"
```

---

### Task 11: Claude Code Slash Commands & Hooks

**Files:**
- Create: `commands/eyeclaude-register.md`
- Create: `commands/eyeclaude-unregister.md`
- Create: `hooks/eyeclaude-status.sh`

- [ ] **Step 1: Create the register slash command**

```markdown
<!-- commands/eyeclaude-register.md -->
Register this terminal with EyeClaude for eye-tracking focus management.

Run the following command to register this terminal and install status hooks:

```bash
eyeclaude register
```

Confirm registration was successful by telling me the output.
```

- [ ] **Step 2: Create the unregister slash command**

```markdown
<!-- commands/eyeclaude-unregister.md -->
Unregister this terminal from EyeClaude and remove status hooks.

Run the following command to unregister:

```bash
eyeclaude unregister
```

Confirm the unregistration was successful by telling me the output.
```

- [ ] **Step 3: Create the hooks helper script**

```python
# src/eyeclaude/hooks.py
"""Hook helper — sends status events to EyeClaude from Claude Code hooks."""

import json
import os
import sys

import win32file


PIPE_NAME = r"\\.\pipe\eyeclaude"


def main():
    if len(sys.argv) < 3:
        print("Usage: eyeclaude-hooks status <idle|working|finished|error>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    if command != "status":
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)

    state = sys.argv[2]
    pid = os.getpid()

    # Read stdin for hook input (Claude Code sends JSON)
    stdin_data = ""
    try:
        if not sys.stdin.isatty():
            stdin_data = sys.stdin.read()
    except Exception:
        pass

    # Detect error state from hook input
    if stdin_data:
        try:
            hook_input = json.loads(stdin_data)
            event = hook_input.get("hook_event_name", "")
            if event == "StopFailure":
                state = "error"
        except json.JSONDecodeError:
            pass

    message = json.dumps({
        "type": "status",
        "pid": pid,
        "state": state,
    }).encode("utf-8")

    try:
        handle = win32file.CreateFile(
            PIPE_NAME,
            win32file.GENERIC_WRITE,
            0, None,
            win32file.OPEN_EXISTING,
            0, None,
        )
        win32file.WriteFile(handle, message)
        win32file.CloseHandle(handle)
    except Exception:
        pass  # EyeClaude may not be running — fail silently

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add hooks entry point to pyproject.toml**

Add to the `[project.scripts]` section in `pyproject.toml`:

```toml
[project.scripts]
eyeclaude = "eyeclaude.cli:main"
eyeclaude-hooks = "eyeclaude.hooks:main"
```

- [ ] **Step 5: Reinstall to pick up new entry point**

Run:
```bash
cd C:/Users/raul/Documents/GitHub/eyeclaude
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/eyeclaude-hooks --help 2>&1 || echo "OK - no --help, but script exists"
```

- [ ] **Step 6: Commit**

```bash
git add commands/ src/eyeclaude/hooks.py pyproject.toml
git commit -m "feat: Claude Code slash commands and status hook helper"
```

---

### Task 12: Integration — Wire Everything Together

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test for pipe server ↔ status monitor**

```python
# tests/test_integration.py
import json
import threading
import time

import win32file
import win32pipe

from eyeclaude.pipe_server import PipeServer, PIPE_NAME, parse_message
from eyeclaude.shared_state import SharedState, Quadrant, InstanceStatus
from eyeclaude.status_monitor import StatusMonitor


TEST_PIPE = r"\\.\pipe\eyeclaude_integration_test"


def send_pipe_message(pipe_name: str, data: dict) -> None:
    handle = win32file.CreateFile(
        pipe_name,
        win32file.GENERIC_WRITE,
        0, None,
        win32file.OPEN_EXISTING,
        0, None,
    )
    message = json.dumps(data).encode("utf-8")
    win32file.WriteFile(handle, message)
    win32file.CloseHandle(handle)


class TestPipeServerIntegration:
    def test_register_via_pipe(self):
        state = SharedState()
        server = PipeServer(state, pipe_name=TEST_PIPE)
        server.start()
        time.sleep(0.2)  # Let pipe server start

        try:
            send_pipe_message(TEST_PIPE, {
                "type": "register",
                "window_handle": 999,
                "pid": 1234,
            })
            time.sleep(0.3)  # Let message be processed

            terminal = state.get_terminal(pid=1234)
            assert terminal is not None
            assert terminal.window_handle == 999
        finally:
            server.stop()

    def test_status_update_via_pipe(self):
        state = SharedState()
        state.register_terminal(pid=1234, window_handle=999, quadrant=Quadrant.TOP_LEFT)
        server = PipeServer(state, pipe_name=TEST_PIPE)
        server.start()
        time.sleep(0.2)

        try:
            send_pipe_message(TEST_PIPE, {
                "type": "status",
                "pid": 1234,
                "state": "working",
            })
            time.sleep(0.3)

            terminal = state.get_terminal(pid=1234)
            assert terminal.status == InstanceStatus.WORKING
        finally:
            server.stop()

    def test_unregister_via_pipe(self):
        state = SharedState()
        state.register_terminal(pid=1234, window_handle=999, quadrant=Quadrant.TOP_LEFT)
        server = PipeServer(state, pipe_name=TEST_PIPE)
        server.start()
        time.sleep(0.2)

        try:
            send_pipe_message(TEST_PIPE, {
                "type": "unregister",
                "pid": 1234,
            })
            time.sleep(0.3)

            assert state.get_terminal(pid=1234) is None
        finally:
            server.stop()
```

- [ ] **Step 2: Run integration tests**

Run: `.venv/Scripts/pytest tests/test_integration.py -v`

Expected: All 3 tests PASS.

- [ ] **Step 3: Run full test suite**

Run: `.venv/Scripts/pytest tests/ -v`

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "feat: integration tests for pipe server communication"
```

---

### Task 13: Add .gitignore and Final Cleanup

**Files:**
- Create: `.gitignore`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create .gitignore**

```
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/
build/
.pytest_cache/
```

- [ ] **Step 2: Create test infrastructure files**

```python
# tests/__init__.py
```

```python
# tests/conftest.py
"""Shared test fixtures for EyeClaude tests."""
```

- [ ] **Step 3: Run full test suite one final time**

Run: `.venv/Scripts/pytest tests/ -v --tb=short`

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add .gitignore tests/__init__.py tests/conftest.py
git commit -m "chore: add gitignore and test infrastructure"
```
