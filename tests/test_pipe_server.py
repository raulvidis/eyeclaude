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


class TestStatusFileWriter:
    def test_writes_status_file_on_status_message(self, tmp_path):
        from eyeclaude.pipe_server import PipeServer, PipeMessage
        from eyeclaude.shared_state import SharedState, Quadrant

        state = SharedState()
        state.register_terminal(pid=1001, window_handle=1001, quadrant=Quadrant.TOP_LEFT)

        server = PipeServer(state, status_dir=tmp_path)
        msg = PipeMessage(type="status", window_handle=1001, state="working")
        server.handle_message(msg)

        status_file = tmp_path / "1001.json"
        assert status_file.exists()
        data = json.loads(status_file.read_text())
        assert data["status"] == "working"

    def test_writes_active_flag(self, tmp_path):
        from eyeclaude.pipe_server import PipeServer, PipeMessage
        from eyeclaude.shared_state import SharedState, Quadrant

        state = SharedState()
        state.register_terminal(pid=1001, window_handle=1001, quadrant=Quadrant.TOP_LEFT)
        state.active_quadrant = Quadrant.TOP_LEFT

        server = PipeServer(state, status_dir=tmp_path)
        msg = PipeMessage(type="status", window_handle=1001, state="idle")
        server.handle_message(msg)

        data = json.loads((tmp_path / "1001.json").read_text())
        assert data["active"] is True

    def test_inactive_terminal(self, tmp_path):
        from eyeclaude.pipe_server import PipeServer, PipeMessage
        from eyeclaude.shared_state import SharedState, Quadrant

        state = SharedState()
        state.register_terminal(pid=1001, window_handle=1001, quadrant=Quadrant.TOP_LEFT)
        state.active_quadrant = Quadrant.BOTTOM_RIGHT  # Different quadrant

        server = PipeServer(state, status_dir=tmp_path)
        msg = PipeMessage(type="status", window_handle=1001, state="idle")
        server.handle_message(msg)

        data = json.loads((tmp_path / "1001.json").read_text())
        assert data["active"] is False
