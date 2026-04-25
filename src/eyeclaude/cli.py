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

from eyeclaude.calibration import load_calibration, save_calibration, DEFAULT_CALIBRATION_PATH
from eyeclaude.config import load_config, save_config, EyeClaudeConfig, DEFAULT_CONFIG_PATH
from eyeclaude.eye_tracker import EyeTracker
from eyeclaude.pipe_server import PipeServer, PIPE_NAME, _assign_quadrant_by_position
from eyeclaude.shared_state import SharedState, InstanceStatus
from eyeclaude.status_monitor import StatusMonitor
from eyeclaude.window_manager import WindowManager

logger = logging.getLogger("eyeclaude")


# Force stdout/stderr to UTF-8 with replace-on-error before click runs.
# Otherwise click + colorama crash with `OSError: Windows error 6` when writing
# em-dashes, emoji, or geometric characters to the Windows console — which
# happens during help formatting before any command callback executes.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """EyeClaude - Eye-tracking focus manager for Claude Code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # When invoked with no subcommand, print help on stdout. This avoids
    # click's NoArgsIsHelpError path which writes to stderr via colorama's
    # _winconsole — that path crashes on Python 3.13 + Windows with
    # "OSError: Windows error 6" regardless of the characters being written.
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        ctx.exit(0)


def _install_statusline():
    """Add EyeClaude indicator to statusline via shell one-liner.

    Reads a tiny indicator file and prepends it to ccstatusline output.
    No Python wrapper, no subprocess — just shell + npx in the same context
    where ccstatusline was already working.
    """
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

    # Shell one-liner: read indicator file, pipe stdin to ccstatusline, combine
    indicator_dir = Path.home() / ".eyeclaude" / "status"
    indicator_dir_str = str(indicator_dir).replace("\\", "/")
    cmd = (
        f'bash -c \'INPUT=$(cat); '
        f'IND=$(cat "{indicator_dir_str}/indicator" 2>/dev/null || echo ""); '
        f'OUT=$(echo "$INPUT" | npx -y ccstatusline@latest 2>/dev/null); '
        f'if [ -n "$IND" ] && [ -n "$OUT" ]; then echo "$IND $OUT"; '
        f'elif [ -n "$IND" ]; then echo "$IND"; '
        f'elif [ -n "$OUT" ]; then echo "$OUT"; fi\''
    )

    settings["statusLine"] = {
        "type": "command",
        "command": cmd,
        "padding": 0,
    }
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    click.echo("Statusline indicator installed.")


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
    """Update per-terminal status files and the statusline indicator file."""
    status_dir = Path.home() / ".eyeclaude" / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    active_quad = state.active_quadrant

    # Update per-terminal JSON files — always write current status from state
    for terminal in state.get_all_terminals():
        status_file = status_dir / f"{terminal.window_handle}.json"
        data = {"status": terminal.status.value, "active": terminal.quadrant == active_quad}
        try:
            status_file.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    # Write statusline indicator file: emoji showing active terminal's status
    # This is read by the shell one-liner in the statusline command
    active_terminal = state.get_terminal_for_quadrant(active_quad) if active_quad else None
    if active_terminal:
        status_emoji = {
            "idle": "\U0001f7e2",       # 🟢
            "working": "\U0001f535",     # 🔵
            "finished": "\U0001f7e1",    # 🟡
            "error": "\U0001f534",       # 🔴
        }
        emoji = status_emoji.get(active_terminal.status.value, "\U0001f7e2")
        indicator = f"{emoji}\u25c0"  # emoji + ◀
    else:
        indicator = ""
    try:
        (status_dir / "indicator").write_text(indicator, encoding="utf-8")
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
    click.echo(f"Calibration saved - {len(calibration.points)} points captured.")
    for step, (gx, gy) in calibration.points.items():
        click.echo(f"  {step}: gaze=({gx:.4f}, {gy:.4f})")

    # Reuse webcam + landmarker from calibration overlay (avoids 30-60s reinit)
    cap, landmarker = overlay_app.get_resources()

    # Install statusline indicator
    _install_statusline()

    eye_tracker = EyeTracker(
        state=state,
        calibration=calibration,
        dwell_time_ms=config.dwell_time_ms,
        webcam_index=config.webcam_index,
        cap=cap,
        landmarker=landmarker,
    )
    window_manager = WindowManager(state)
    eye_tracker.start()

    click.echo("EyeClaude started.")
    click.echo("  Ctrl+C = stop | F8 = pause/resume | F9 = recalibrate")

    stop_event = threading.Event()
    paused = False

    def handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Register global hotkeys (F8=pause, F9=recalibrate)
    import ctypes
    import ctypes.wintypes

    VK_F8 = 0x77
    VK_F9 = 0x78
    HOTKEY_PAUSE = 1
    HOTKEY_RECALIBRATE = 2

    try:
        ctypes.windll.user32.RegisterHotKey(None, HOTKEY_PAUSE, 0, VK_F8)
        ctypes.windll.user32.RegisterHotKey(None, HOTKEY_RECALIBRATE, 0, VK_F9)
    except Exception as e:
        click.echo(f"  Warning: Could not register global hotkeys: {e}")
        logger.warning("RegisterHotKey failed: %s", e)

    def _poll_hotkeys():
        """Check for global hotkey messages (non-blocking)."""
        msg = ctypes.wintypes.MSG()
        while ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), None, 0x0312, 0x0312, 0x0001):
            if msg.message == 0x0312:  # WM_HOTKEY
                if msg.wParam == HOTKEY_PAUSE:
                    return "pause"
                elif msg.wParam == HOTKEY_RECALIBRATE:
                    return "recalibrate"
        return None

    # Main loop
    last_active = None
    try:
        while not stop_event.is_set() and not state.shutdown_requested:
            # Check hotkeys
            hotkey = _poll_hotkeys()
            if hotkey == "pause":
                paused = not paused
                if paused:
                    click.echo("  [PAUSED] Tracking paused (F8 to resume)")
                else:
                    click.echo("  [RESUMED] Tracking resumed")
            elif hotkey == "recalibrate":
                click.echo("  Recalibrating...")
                # Steal webcam + landmarker from eye tracker (already initialized)
                reuse_cap = eye_tracker._cap
                reuse_lm = eye_tracker._landmarker
                eye_tracker._cap = None
                eye_tracker._landmarker = None
                eye_tracker.stop()

                from eyeclaude.calibration_overlay import CalibrationOverlay
                recal_overlay = CalibrationOverlay(webcam_index=config.webcam_index)
                recal_overlay._cap = reuse_cap
                recal_overlay._landmarker = reuse_lm
                new_cal = recal_overlay.run()

                # Get resources back (overlay may have kept or replaced them)
                cap_back, lm_back = recal_overlay.get_resources()

                if new_cal:
                    calibration = new_cal
                    save_calibration(calibration)
                    click.echo(f"  Recalibrated - {len(calibration.points)} points captured.")
                else:
                    click.echo("  Recalibration cancelled, resuming with old calibration.")

                eye_tracker = EyeTracker(
                    state=state, calibration=calibration,
                    dwell_time_ms=config.dwell_time_ms,
                    webcam_index=config.webcam_index,
                    cap=cap_back, landmarker=lm_back,
                )
                eye_tracker.start()
                continue

            if paused:
                # Write paused indicator
                status_dir = Path.home() / ".eyeclaude" / "status"
                status_dir.mkdir(parents=True, exist_ok=True)
                try:
                    (status_dir / "indicator").write_text("\u23f8", encoding="utf-8")  # ⏸
                except Exception:
                    pass
            else:
                active = state.active_quadrant
                if active != last_active:
                    if active:
                        terminal = state.get_terminal_for_quadrant(active)
                        title = ""
                        if terminal:
                            try:
                                import win32gui
                                title = win32gui.GetWindowText(terminal.window_handle)
                            except Exception:
                                pass
                        click.echo(f"  Focus → {active.value} {title}")
                    last_active = active
                window_manager.update_focus(active)
                status_monitor.tick()
                _update_active_status_files(state)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass

    # Cleanup hotkeys
    try:
        ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_PAUSE)
        ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_RECALIBRATE)
    except Exception as e:
        logger.debug("UnregisterHotKey failed: %s", e)

    click.echo("\nShutting down...")
    eye_tracker.stop()
    pipe_server.stop()
    _restore_statusline()
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
