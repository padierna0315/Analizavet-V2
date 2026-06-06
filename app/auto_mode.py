"""Headless console operator for Analizavet V2.

Foreground polling loop that:
- Syncs AppSheet every 30s via POST /reception/appsheet/sync
- Fetches status via GET /auto/status
- Listens for 'r' keypress to generate jornada reports (adelanto/final)
- Clean Ctrl+C exit with terminal restoration

Run via: uv run python -m app.auto_mode
"""

import os
import re
import sys
import time
import select
import termios
import tty
from datetime import datetime, timezone
from pathlib import Path

import httpx
import logfire

from app.domains.auto.router import set_last_sync_at


# Default polling interval in seconds
DEFAULT_POLL_INTERVAL = 30

# Base URL for the FastAPI server
BASE_URL = os.environ.get("ANALIZAVET_BASE_URL", "http://localhost:8000")

# Download directory for final reports
DOWNLOADS_DIR = Path("data/descargas")


# ── Terminal control ──────────────────────────────────────────────────────────


def _setup_stdin() -> tuple | None:
    """Save current terminal attributes and set raw mode.

    Returns the saved attributes for later restoration,
    or None if stdin is not a TTY.
    """
    if not sys.stdin.isatty():
        return None
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setraw(fd)
    mode = termios.tcgetattr(fd)
    mode[1] |= termios.ONLCR  # re-enable NL→CR+NL to prevent staircase output
    termios.tcsetattr(fd, termios.TCSADRAIN, mode)
    return saved


def _restore_stdin(saved: tuple | None) -> None:
    """Restore terminal attributes to saved state."""
    if saved is None:
        return
    try:
        fd = sys.stdin.fileno()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    except Exception as e:
        logfire.warning(f"Failed to restore terminal attributes: {e}")


# ── Keypress detection ────────────────────────────────────────────────────────

_check_keypress_error_logged = False


def _check_keypress() -> str | None:
    """Non-blocking check for 'r' keypress on stdin.

    Returns 'r' if pressed, None otherwise.
    Raises KeyboardInterrupt on Ctrl+C (0x03) since raw mode disables ISIG.
    """
    global _check_keypress_error_logged
    try:
        if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
            char = sys.stdin.read(1)
            if char == "\x03":
                raise KeyboardInterrupt
            if char and char.lower() == "r":
                return "r"
        return None
    except Exception as e:
        if not _check_keypress_error_logged:
            logfire.warning(f"_check_keypress error (suppressing further): {e}")
            _check_keypress_error_logged = True
        return None


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def _fetch_sync(client: httpx.Client) -> tuple[int, bool]:
    """POST /reception/appsheet/sync and return (count, success).

    success is True when the HTTP request returned 200 (even with 0 patients).
    success is False on HTTP errors, timeouts, or parse failures.
    Errors are logged to stderr.
    """
    try:
        response = client.post("/reception/appsheet/sync")
        if response.status_code != 200:
            print(f"[{datetime.now(timezone.utc).isoformat()}] Sync error: HTTP {response.status_code}", file=sys.stderr)
            return 0, False
        # Parse "✅ N paciente(s) sincronizado(s)"
        match = re.search(r"(\d+)\s*paciente", response.text)
        count = int(match.group(1)) if match else 0
        return count, True
    except Exception as e:
        print(f"[{datetime.now(timezone.utc).isoformat()}] Sync failed: {e}", file=sys.stderr)
        return 0, False


def _fetch_status(client: httpx.Client) -> dict:
    """GET /auto/status and return the JSON response as a dict.

    Returns an empty dict on any error (logged to stderr).
    """
    try:
        response = client.get("/auto/status")
        if response.status_code != 200:
            print(f"[{datetime.now(timezone.utc).isoformat()}] Status error: HTTP {response.status_code}", file=sys.stderr)
            return {}
        return response.json()
    except Exception as e:
        print(f"[{datetime.now(timezone.utc).isoformat()}] Status fetch failed: {e}", file=sys.stderr)
        return {}


# ── Report handler ────────────────────────────────────────────────────────────


def _handle_report(client: httpx.Client, mode: str) -> None:
    """Handle 'r' keypress report generation.

    Args:
        client: httpx.Client pointed at the server.
        mode: "ADELANTO" (print-only preview) or "FINAL" (save to .txt).
    """
    try:
        if mode == "ADELANTO":
            response = client.get("/jornada/adelanto")
            response.raise_for_status()
            print("\n" + "=" * 60)
            print(response.text)
            print("=" * 60 + "\n")
        elif mode == "FINAL":
            response = client.get("/jornada/resumen")
            response.raise_for_status()
            DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filepath = DOWNLOADS_DIR / f"resumen-jornada_{timestamp}.txt"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(response.text)
            print(f"\n✅ Reporte FINAL guardado en {filepath}\n")
    except Exception as e:
        print(f"❌ Error al obtener reporte: {e}")


# ── Main loop ─────────────────────────────────────────────────────────────────


def main() -> None:
    """Run the headless operator polling loop.

    Every 30s: sync AppSheet, fetch status, display results.
    On 'r' keypress: prompt for ADELANTO/FINAL and generate report.
    Ctrl+C: clean exit.
    """
    poll_interval = int(os.environ.get("AUTO_POLL_INTERVAL", DEFAULT_POLL_INTERVAL))

    # Setup terminal for raw keypress detection
    saved_attrs = _setup_stdin()

    client = None
    try:
        client = httpx.Client(base_url=BASE_URL, timeout=30.0)
        tick = 0
        print("🚀 Modo Automático — Analizavet V2")
        print(f"   Base URL: {BASE_URL}")
        print(f"   Poll: cada {poll_interval}s | 'r' = reporte | Ctrl+C = salir")
        print("-" * 60)
        while True:
            # ── Poll ─────────────────────────────────────────────
            tick += 1
            now_iso = datetime.now(timezone.utc).isoformat()
            now_display = datetime.now().strftime("%H:%M:%S")

            count, sync_ok = _fetch_sync(client)
            if sync_ok:
                try:
                    set_last_sync_at(now_iso)
                except Exception as e:
                    print(f"[{now_display}] Redis update failed: {e}", file=sys.stderr)

            status = _fetch_status(client)

            # Display tick info
            print(
                f"[{now_display}] Tick #{tick} | "
                f"Sync: {count} pacientes | "
                f"Espera: {status.get('patients_waiting_count', '?')} | "
                f"Jornada: {status.get('jornada_entries', '?')}"
            )

            # ── Keypress check (non-blocking during sleep) ────────
            elapsed = 0
            while elapsed < poll_interval:
                key = _check_keypress()
                if key == "r":
                    # Restore terminal to cooked mode before printing and input
                    _restore_stdin(saved_attrs)
                    print("\n📄 Reporte de jornada")
                    try:
                        if saved_attrs is not None:
                            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
                        try:
                            mode = input("¿ADELANTO o FINAL? ").strip().upper()
                        except (EOFError, KeyboardInterrupt):
                            mode = ""
                            print("\n⚠️  Entrada cancelada.")
                        if mode in ("ADELANTO", "FINAL"):
                            _handle_report(client, mode)
                        elif mode:
                            print("⚠️  Opción no válida. Usá ADELANTO o FINAL.")
                    finally:
                        # Re-enter raw mode for key detection
                        _setup_stdin()
                        if saved_attrs is not None:
                            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
                    break  # Restart tick after report
                time.sleep(0.1)
                elapsed += 0.1

    except KeyboardInterrupt:
        print("\n\n👋 Cerrando modo automático...")
    finally:
        _restore_stdin(saved_attrs)
        if client is not None:
            client.close()
        print("✅ Terminal restaurada. ¡Hasta luego!")


if __name__ == "__main__":
    main()
