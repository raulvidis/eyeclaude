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
            new_status = status_map.get(msg.state, InstanceStatus.IDLE)
            # Resolve the pid from window_handle for the status monitor
            if msg.window_handle:
                terminal = state.get_terminal_by_hwnd(msg.window_handle)
                if terminal:
                    status_monitor.on_status_change(pid=terminal.pid, new_status=new_status)
            else:
                status_monitor.on_status_change(pid=msg.pid, new_status=new_status)

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
        while not stop_event.is_set() and not state.shutdown_requested:
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
@click.option("--all", "register_all", is_flag=True, help="Register all visible Windows Terminal windows")
def register(register_all):
    """Register terminal(s) with EyeClaude and install Claude Code hooks."""
    import win32gui

    if register_all:
        terminals = _find_all_terminal_windows()
        if not terminals:
            click.echo("No Windows Terminal windows found.")
            return
        for hwnd in terminals:
            _register_one_window(hwnd)
    else:
        # The foreground window is the terminal the user is interacting with.
        # This works because the user just pressed Enter to run this command.
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            click.echo("Error: Could not determine terminal window handle.")
            return
        cls = win32gui.GetClassName(hwnd)
        if "CASCADIA" not in cls.upper() and "TERMINAL" not in cls.upper():
            click.echo(f"Warning: Foreground window ({cls}) may not be a terminal.")
        _register_one_window(hwnd)

    _install_claude_hooks()
    click.echo("Claude Code status hooks installed.")


def _register_one_window(hwnd: int) -> None:
    """Register a single window with EyeClaude."""
    import win32gui
    try:
        _send_pipe_message({
            "type": "register",
            "window_handle": hwnd,
            "pid": hwnd,  # Use hwnd as unique ID (PID is shared across WT windows)
        })
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        click.echo(f"Registered HWND={hwnd} at ({left},{top})-({right},{bottom})")
    except Exception as e:
        click.echo(f"Failed to register HWND={hwnd}: {e}. Is EyeClaude running?")


def _find_all_terminal_windows() -> list[int]:
    """Find all visible Windows Terminal (CASCADIA) windows."""
    import win32gui
    terminals = []
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            if "CASCADIA" in win32gui.GetClassName(hwnd).upper():
                terminals.append(hwnd)
        return True
    win32gui.EnumWindows(callback, None)
    return terminals


@main.command()
def unregister():
    """Unregister the current terminal from EyeClaude and remove hooks."""
    import os
    import win32console

    hwnd = win32console.GetConsoleWindow()
    pid = os.getpid()
    try:
        _send_pipe_message({"type": "unregister", "pid": pid})
        click.echo(f"Unregistered from EyeClaude (pid={pid})")
    except Exception as e:
        click.echo(f"Failed to unregister: {e}. Is EyeClaude running?")

    _remove_claude_hooks()
    click.echo("Claude Code status hooks removed.")


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


EYECLAUDE_HOOKS = {
    "PreToolUse": {"type": "command", "command": "eyeclaude-hooks status working"},
    "Stop": {"type": "command", "command": "eyeclaude-hooks status finished"},
    "StopFailure": {"type": "command", "command": "eyeclaude-hooks status error"},
    "UserPromptSubmit": {"type": "command", "command": "eyeclaude-hooks status idle"},
}


def _load_settings() -> tuple[Path, dict]:
    # Install hooks globally so they work in every Claude Code session
    settings_dir = Path.home() / ".claude"
    settings_dir.mkdir(exist_ok=True)
    settings_path = settings_dir / "settings.local.json"
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            settings = {}
    return settings_path, settings


def _install_claude_hooks():
    """Merge EyeClaude hooks into .claude/settings.local.json without overwriting existing hooks."""
    settings_path, settings = _load_settings()

    if "hooks" not in settings:
        settings["hooks"] = {}

    for event_name, hook_def in EYECLAUDE_HOOKS.items():
        if event_name not in settings["hooks"]:
            settings["hooks"][event_name] = []
        # Check if our hook is already installed
        already_installed = any(
            any(h.get("command") == hook_def["command"] for h in entry.get("hooks", []))
            for entry in settings["hooks"][event_name]
        )
        if not already_installed:
            settings["hooks"][event_name].append({"hooks": [hook_def]})

    settings_path.write_text(json.dumps(settings, indent=2))


def _remove_claude_hooks():
    """Remove EyeClaude hooks from .claude/settings.local.json."""
    settings_path, settings = _load_settings()

    if "hooks" not in settings:
        return

    for event_name, hook_def in EYECLAUDE_HOOKS.items():
        if event_name in settings["hooks"]:
            settings["hooks"][event_name] = [
                entry for entry in settings["hooks"][event_name]
                if not any(h.get("command") == hook_def["command"] for h in entry.get("hooks", []))
            ]
            if not settings["hooks"][event_name]:
                del settings["hooks"][event_name]

    if not settings["hooks"]:
        del settings["hooks"]

    settings_path.write_text(json.dumps(settings, indent=2))


if __name__ == "__main__":
    main()
