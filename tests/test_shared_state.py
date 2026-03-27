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
