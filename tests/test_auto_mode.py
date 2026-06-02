"""Tests for app/auto_mode.py — headless console operator.

Tests core functions: sync, status fetch, report handler,
keypress detection, and stdin setup/restore.
"""

import pytest
import os
import sys
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timezone


# ── _fetch_sync ───────────────────────────────────────────────────────────────


def test_fetch_sync_posts_to_appsheet():
    """_fetch_sync POSTs to /reception/appsheet/sync and returns count."""
    from app.auto_mode import _fetch_sync

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "✅ 3 paciente(s) sincronizado(s)"
    mock_client.post.return_value = mock_response

    count = _fetch_sync(mock_client)

    assert count == 3
    mock_client.post.assert_called_once_with("/reception/appsheet/sync")


def test_fetch_sync_handles_http_error():
    """_fetch_sync returns 0 and logs error on HTTP failure."""
    from app.auto_mode import _fetch_sync

    mock_client = MagicMock()
    mock_client.post.side_effect = Exception("Connection refused")

    count = _fetch_sync(mock_client)

    assert count == 0


def test_fetch_sync_handles_non_200():
    """_fetch_sync returns 0 on non-200 response."""
    from app.auto_mode import _fetch_sync

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_client.post.return_value = mock_response

    count = _fetch_sync(mock_client)

    assert count == 0


def test_fetch_sync_parse_zero():
    """_fetch_sync returns 0 when 0 patients synced."""
    from app.auto_mode import _fetch_sync

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "✅ 0 paciente(s) sincronizado(s)"
    mock_client.post.return_value = mock_response

    count = _fetch_sync(mock_client)

    assert count == 0


# ── _fetch_status ─────────────────────────────────────────────────────────────


def test_fetch_status_returns_dict():
    """_fetch_status GETs /auto/status and returns JSON dict."""
    from app.auto_mode import _fetch_status

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "patients_waiting_count": 5,
        "jornada_entries": 3,
        "last_sync_at": None,
        "last_reprocess_at": None,
    }
    mock_client.get.return_value = mock_response

    status = _fetch_status(mock_client)

    assert status["patients_waiting_count"] == 5
    assert status["jornada_entries"] == 3
    mock_client.get.assert_called_once_with("/auto/status")


def test_fetch_status_handles_error():
    """_fetch_status returns empty dict on HTTP error."""
    from app.auto_mode import _fetch_status

    mock_client = MagicMock()
    mock_client.get.side_effect = Exception("Timeout")

    status = _fetch_status(mock_client)

    assert status == {}


# ── _handle_report ────────────────────────────────────────────────────────────


def test_handle_report_adelanto():
    """_handle_report with 'ADELANTO' calls /jornada/adelanto and prints."""
    from app.auto_mode import _handle_report

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "🐾 Reporte de jornada — adelanto"
    mock_client.get.return_value = mock_response

    with patch("builtins.print") as mock_print:
        _handle_report(mock_client, "ADELANTO")

    mock_client.get.assert_called_once_with("/jornada/adelanto")
    # Verify report was printed
    mock_print.assert_any_call("\n" + "=" * 60)
    mock_print.assert_any_call("🐾 Reporte de jornada — adelanto")


def test_handle_report_final_saves_file():
    """_handle_report with 'FINAL' calls /jornada/resumen and saves .txt."""
    from app.auto_mode import _handle_report

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "🐾 Reporte de jornada — final"
    mock_response.headers = {}
    mock_client.get.return_value = mock_response

    with patch("builtins.print") as mock_print, \
         patch("builtins.open", MagicMock()) as mock_open, \
         patch("pathlib.Path.mkdir") as mock_mkdir:

        _handle_report(mock_client, "FINAL")

    mock_client.get.assert_called_once_with("/jornada/resumen")
    mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_open.assert_called_once()
    # Check that "Reporte FINAL guardado" substring appears in some print call
    found = any(
        "Reporte FINAL guardado" in str(call_args)
        for call_args in mock_print.call_args_list
    )
    assert found, f"Expected 'Reporte FINAL guardado' in print calls, got: {mock_print.call_args_list}"


def test_handle_report_adelanto_http_error():
    """_handle_report handles HTTP error gracefully for adelanto."""
    from app.auto_mode import _handle_report

    mock_client = MagicMock()
    mock_client.get.side_effect = Exception("Network error")

    with patch("builtins.print") as mock_print:
        _handle_report(mock_client, "ADELANTO")

    mock_print.assert_any_call("❌ Error al obtener reporte: Network error")


# ── _check_keypress ───────────────────────────────────────────────────────────


def test_check_keypress_detects_r():
    """_check_keypress returns 'r' when 'r' is pressed."""
    from app.auto_mode import _check_keypress

    with patch("select.select") as mock_select:
        # Simulate stdin has data and the first char is 'r'
        mock_select.return_value = ([sys.stdin], [], [])
        with patch("sys.stdin.read", return_value="r"):
            result = _check_keypress()

    assert result == "r"


def test_check_keypress_ignores_other_keys():
    """_check_keypress returns None for non-'r' keys."""
    from app.auto_mode import _check_keypress

    with patch("select.select") as mock_select:
        mock_select.return_value = ([sys.stdin], [], [])
        with patch("sys.stdin.read", return_value="x"):
            result = _check_keypress()

    assert result is None


def test_check_keypress_no_data():
    """_check_keypress returns None when no stdin data available."""
    from app.auto_mode import _check_keypress

    with patch("select.select") as mock_select:
        mock_select.return_value = ([], [], [])

        result = _check_keypress()

    assert result is None


def test_check_keypress_handles_error():
    """_check_keypress returns None on any exception."""
    from app.auto_mode import _check_keypress

    with patch("select.select", side_effect=OSError("Bad fd")):
        result = _check_keypress()

    assert result is None


# ── _setup_stdin / _restore_stdin ─────────────────────────────────────────────


def test_setup_stdin_saves_terminal_state():
    """_setup_stdin saves termios attrs and sets raw mode."""
    from app.auto_mode import _setup_stdin, _restore_stdin

    with patch("termios.tcgetattr") as mock_get, \
         patch("termios.tcsetattr") as mock_set, \
         patch("tty.setraw") as mock_setraw, \
         patch("sys.stdin.isatty", return_value=True), \
         patch("sys.stdin.fileno", return_value=0):

        mock_get.return_value = [0, 1, 2, 3, 4, 5, 6]
        saved = _setup_stdin()

        assert saved is not None
        mock_get.assert_called_once()
        mock_setraw.assert_called_once()

        # Restore (within same patch context)
        _restore_stdin(saved)
        mock_set.assert_called_once()


def test_setup_stdin_handles_import_error():
    """_setup_stdin returns None when stdin is not a TTY."""
    from app.auto_mode import _setup_stdin

    with patch("sys.stdin.isatty", return_value=False):
        saved = _setup_stdin()
        assert saved is None
