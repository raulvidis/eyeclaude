"""Named pipe server for receiving registration and status messages."""

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

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
    def __init__(self, state: SharedState, pipe_name: str = PIPE_NAME, status_dir: Path | None = None):
        self._state = state
        self._pipe_name = pipe_name
        self._status_dir = status_dir or (Path.home() / ".eyeclaude" / "status")
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
        except Exception as e:
            logger.debug("Pipe-unblock connect failed: %s", e)
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _write_status_file(self, window_handle: int, state: str) -> None:
        """Write per-terminal status JSON for the statusline wrapper."""
        self._status_dir.mkdir(parents=True, exist_ok=True)
        terminal = self._state.get_terminal_by_hwnd(window_handle)
        active = False
        if terminal:
            active_quad = self._state.active_quadrant
            active = terminal.quadrant == active_quad
        data = {"status": state, "active": active}
        status_file = self._status_dir / f"{window_handle}.json"
        status_file.write_text(json.dumps(data), encoding="utf-8")

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
            # Status updates from hooks use window_handle (HWND) as identifier
            # since each hook invocation spawns a new process with a different PID
            if msg.window_handle:
                self._state.update_status_by_hwnd(
                    window_handle=msg.window_handle,
                    status=status,
                    error_message=msg.message,
                )
                logger.debug(f"Status update hwnd={msg.window_handle} -> {msg.state}")
                self._write_status_file(msg.window_handle, msg.state)
            else:
                self._state.update_status(
                    pid=msg.pid,
                    status=status,
                    error_message=msg.message,
                )
                logger.debug(f"Status update pid={msg.pid} -> {msg.state}")

        elif msg.type == "shutdown":
            self._state.request_shutdown()
            logger.info("Shutdown requested via pipe")

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
