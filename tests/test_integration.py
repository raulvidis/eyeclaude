"""Integration tests for pipe server communication."""
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
