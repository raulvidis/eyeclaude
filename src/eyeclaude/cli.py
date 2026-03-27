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


@main.command("config")
@click.option("--dwell-time", type=int, help="Dwell time in ms")
@click.option("--border-thickness", type=int, help="Border thickness in px")
@click.option("--webcam-index", type=int, help="Webcam device index")
def config_cmd(dwell_time, border_thickness, webcam_index):
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


if __name__ == "__main__":
    main()
