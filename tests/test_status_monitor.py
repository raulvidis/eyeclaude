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
