"""Headless console operator for Analizavet V2.

Foreground polling loop that:
- Syncs AppSheet every 30s via POST /reception/appsheet/sync
- Fetches status via GET /auto/status
- Listens for 'r' keypress to generate jornada reports (adelanto/final)
- Clean Ctrl+C exit with terminal restoration

Run via: uv run python app/auto_mode.py
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


def _check_keypress() -> str | None:
    """Non-blocking check for 'r' keypress on stdin.

    Returns 'r' if pressed, None otherwise.
    """
    try:
        if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
            char = sys.stdin.read(1)
            if char and char.lower() == "r":
                return "r"
        return None
    except Exception:
        return None


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def _fetch_sync(client: httpx.Client) -> int:
    """POST /reception/appsheet/sync and return the count of synced patients.

    Returns 0 on any error (logged to stderr).
    """
    try:
        response = client.post("/reception/appsheet/sync")
        if response.status_code != 200:
            print(f"[{datetime.now(timezone.utc).isoformat()}] Sync error: HTTP {response.status_code}", file=sys.stderr)
            return 0
        # Parse "✅ N paciente(s) sincronizado(s)"
        match = re.search(r"(\d+)\s*paciente", response.text)
        count = int(match.group(1)) if match else 0
        return count
    except Exception as e:
        print(f"[{datetime.now(timezone.utc).isoformat()}] Sync failed: {e}", file=sys.stderr)
        return 0


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
            print("\n" + "=" * 60)
            print(response.text)
            print("=" * 60 + "\n")
        elif mode == "FINAL":
            response = client.get("/jornada/resumen")
            DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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

    client = httpx.Client(base_url=BASE_URL, timeout=30.0)
    tick = 0

    print("🚀 Modo Automático — Analizavet V2")
    print(f"   Base URL: {BASE_URL}")
    print(f"   Poll: cada {poll_interval}s | 'r' = reporte | Ctrl+C = salir")
    print("-" * 60)

    try:
        while True:
            # ── Poll ─────────────────────────────────────────────
            tick += 1
            now_iso = datetime.now(timezone.utc).isoformat()
            now_display = datetime.now().strftime("%H:%M:%S")

            count = _fetch_sync(client)
            set_last_sync_at(now_iso)

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
                    print("\n📄 Reporte de jornada")
                    # Restore terminal to cooked mode before input()
                    _restore_stdin(saved_attrs)
                    try:
                        mode = input("¿ADELANTO o FINAL? ").strip().upper()
                        if mode in ("ADELANTO", "FINAL"):
                            _handle_report(client, mode)
                        else:
                            print("⚠️  Opción no válida. Usá ADELANTO o FINAL.")
                    finally:
                        # Re-enter raw mode for key detection
                        saved_attrs = _setup_stdin()
                    break  # Restart tick after report
                time.sleep(0.1)
                elapsed += 0.1

    except KeyboardInterrupt:
        print("\n\n👋 Cerrando modo automático...")
    finally:
        _restore_stdin(saved_attrs)
        client.close()
        print("✅ Terminal restaurada. ¡Hasta luego!")


if __name__ == "__main__":
    main()
