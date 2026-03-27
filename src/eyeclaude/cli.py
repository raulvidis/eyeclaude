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

from eyeclaude.calibration import load_calibration, run_calibration, save_calibration, DEFAULT_CALIBRATION_PATH
from eyeclaude.config import load_config, save_config, EyeClaudeConfig, DEFAULT_CONFIG_PATH
from eyeclaude.eye_tracker import EyeTracker
from eyeclaude.pipe_server import PipeServer, PIPE_NAME, _assign_quadrant_by_position
from eyeclaude.shared_state import SharedState, InstanceStatus
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


def _install_statusline():
    """Replace ccstatusline with eyeclaude-statusline wrapper in settings.json."""
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return

    backup_path = Path.home() / ".eyeclaude" / "statusline_backup.json"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if "statusLine" in settings:
        backup_path.write_text(json.dumps(settings["statusLine"]), encoding="utf-8")

    # Use the same Python interpreter to run the wrapper module directly.
    # This avoids PATH issues with pip-installed scripts on Windows.
    cmd = f'"{sys.executable}" -m eyeclaude.statusline_wrapper'

    settings["statusLine"] = {
        "type": "command",
        "command": cmd,
        "padding": 0,
    }
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    click.echo("Statusline wrapper installed.")


def _restore_statusline():
    """Restore original statusline config."""
    backup_path = Path.home() / ".eyeclaude" / "statusline_backup.json"
    settings_path = Path.home() / ".claude" / "settings.json"
    if not backup_path.exists() or not settings_path.exists():
        return
    try:
        original = json.loads(backup_path.read_text(encoding="utf-8"))
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["statusLine"] = original
        settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        backup_path.unlink()
        click.echo("Statusline restored.")
    except Exception:
        pass


def _update_active_status_files(state: SharedState) -> None:
    """Update the active flag in all terminal status files."""
    status_dir = Path.home() / ".eyeclaude" / "status"
    if not status_dir.exists():
        return
    active_quad = state.active_quadrant
    for terminal in state.get_all_terminals():
        status_file = status_dir / f"{terminal.window_handle}.json"
        if status_file.exists():
            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
                data["active"] = terminal.quadrant == active_quad
                status_file.write_text(json.dumps(data), encoding="utf-8")
            except Exception:
                pass


def _cleanup_status_files() -> None:
    """Remove all status files on shutdown."""
    status_dir = Path.home() / ".eyeclaude" / "status"
    if status_dir.exists():
        for f in status_dir.glob("*.json"):
            f.unlink(missing_ok=True)


@main.command()
def start():
    """Launch EyeClaude with auto-discovery and visual calibration."""
    config = load_config()
    state = SharedState()
    status_monitor = StatusMonitor(state, flash_duration_ms=config.finished_flash_duration_ms)

    # Install hooks globally (idempotent)
    _install_claude_hooks()
    click.echo("Claude Code status hooks verified.")

    # Start pipe server for status messages
    pipe_server = PipeServer(state)
    original_handle = pipe_server.handle_message

    def handle_with_monitor(msg):
        original_handle(msg)
        if msg.type == "status":
            status_map = {"idle": InstanceStatus.IDLE, "working": InstanceStatus.WORKING,
                          "finished": InstanceStatus.FINISHED, "error": InstanceStatus.ERROR}
            new_status = status_map.get(msg.state, InstanceStatus.IDLE)
            if msg.window_handle:
                terminal = state.get_terminal_by_hwnd(msg.window_handle)
                if terminal:
                    status_monitor.on_status_change(pid=terminal.pid, new_status=new_status)
            else:
                status_monitor.on_status_change(pid=msg.pid, new_status=new_status)

    pipe_server.handle_message = handle_with_monitor
    pipe_server.start()
    click.echo(f"Listening on pipe: {PIPE_NAME}")

    # Auto-discover terminals and register them
    from eyeclaude.terminal_discovery import discover_terminals
    discovered = discover_terminals()
    click.echo(f"Found {len(discovered)} terminal window(s).")
    for t in discovered:
        quadrant = _assign_quadrant_by_position(t.hwnd)
        state.register_terminal(pid=t.hwnd, window_handle=t.hwnd, quadrant=quadrant)
        click.echo(f"  Registered: {t.title} ({quadrant.value})")

    # Run visual calibration overlay
    from eyeclaude.calibration_overlay import CalibrationOverlay
    click.echo("Opening calibration overlay...")
    overlay_app = CalibrationOverlay(webcam_index=config.webcam_index)
    calibration = overlay_app.run()

    if calibration is None:
        click.echo("Calibration cancelled or failed. Exiting.")
        pipe_server.stop()
        return

    save_calibration(calibration)
    click.echo(f"Calibration saved — {len(calibration.points)} quadrants.")

    # Start eye tracking
    eye_tracker = EyeTracker(
        state=state,
        calibration=calibration,
        dwell_time_ms=config.dwell_time_ms,
        webcam_index=config.webcam_index,
    )
    window_manager = WindowManager(state)
    eye_tracker.start()

    click.echo("EyeClaude started. Press Ctrl+C to stop.")

    stop_event = threading.Event()

    def handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Main loop
    try:
        while not stop_event.is_set() and not state.shutdown_requested:
            active = state.active_quadrant
            window_manager.update_focus(active)
            status_monitor.tick()
            _update_active_status_files(state)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass

    click.echo("\nShutting down...")
    eye_tracker.stop()
    pipe_server.stop()
    _cleanup_status_files()
    click.echo("EyeClaude stopped.")


@main.command()
def stop():
    """Send stop signal to a running EyeClaude instance."""
    try:
        _send_pipe_message({"type": "shutdown"})
        click.echo("Stop signal sent.")
    except Exception as e:
        click.echo(f"Could not connect to EyeClaude: {e}")
    _remove_claude_hooks()
    _cleanup_status_files()
    click.echo("Hooks removed, status files cleaned up.")


@main.command()
def calibrate():
    """Run or re-run eye tracking calibration using the visual overlay."""
    config = load_config()
    click.echo("Opening calibration overlay...")
    from eyeclaude.calibration_overlay import CalibrationOverlay
    overlay_app = CalibrationOverlay(webcam_index=config.webcam_index)
    result = overlay_app.run()
    if result:
        save_calibration(result)
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


def _get_hooks_command(status: str) -> str:
    """Get the full path command for eyeclaude-hooks."""
    import shutil
    # Try to find eyeclaude-hooks on PATH first
    hooks_path = shutil.which("eyeclaude-hooks")
    if hooks_path:
        return f'"{hooks_path}" status {status}'
    # Fallback: check common install locations
    from pathlib import Path
    candidates = [
        Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/Scripts/eyeclaude-hooks.exe",
        Path.home() / ".local/bin/eyeclaude-hooks",
    ]
    for c in candidates:
        if c.exists():
            return f'"{c}" status {status}'
    # Last resort — hope it's on PATH at runtime
    return f"eyeclaude-hooks status {status}"


def _build_hooks_config() -> dict:
    return {
        "PreToolUse": {"type": "command", "command": _get_hooks_command("working")},
        "Stop": {"type": "command", "command": _get_hooks_command("finished")},
        "StopFailure": {"type": "command", "command": _get_hooks_command("error")},
        "UserPromptSubmit": {"type": "command", "command": _get_hooks_command("idle")},
    }


def _load_settings() -> tuple[Path, dict]:
    # Install hooks globally so they work in every Claude Code session
    settings_dir = Path.home() / ".claude"
    settings_dir.mkdir(exist_ok=True)
    settings_path = settings_dir / "settings.local.json"
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            settings = {}
    return settings_path, settings


def _install_claude_hooks():
    """Merge EyeClaude hooks into .claude/settings.local.json without overwriting existing hooks."""
    settings_path, settings = _load_settings()

    if "hooks" not in settings:
        settings["hooks"] = {}

    hooks_config = _build_hooks_config()
    for event_name, hook_def in hooks_config.items():
        if event_name not in settings["hooks"]:
            settings["hooks"][event_name] = []
        # Check if an eyeclaude hook is already installed
        already_installed = any(
            any("eyeclaude-hooks" in h.get("command", "") for h in entry.get("hooks", []))
            for entry in settings["hooks"][event_name]
        )
        if not already_installed:
            settings["hooks"][event_name].append({"hooks": [hook_def]})

    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def _remove_claude_hooks():
    """Remove EyeClaude hooks from .claude/settings.local.json."""
    settings_path, settings = _load_settings()

    if "hooks" not in settings:
        return

    for event_name in ["PreToolUse", "Stop", "StopFailure", "UserPromptSubmit"]:
        if event_name in settings["hooks"]:
            settings["hooks"][event_name] = [
                entry for entry in settings["hooks"][event_name]
                if not any("eyeclaude-hooks" in h.get("command", "") for h in entry.get("hooks", []))
            ]
            if not settings["hooks"][event_name]:
                del settings["hooks"][event_name]

    if not settings["hooks"]:
        del settings["hooks"]

    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
