"""
Tests for app.satellites.ozelle.hl7_parser — Phase 13
"""

import pytest
from datetime import datetime, timezone

from app.satellites.ozelle.hl7_parser import (
    parse_hl7_message,
    HL7ParsingError,
    HeartbeatMessageException,
    ParsedOzelleMessage,
)


# ── Realistic HL7 fixture from Ozelle EHVT-50 ────────────────────────────────


REAL_HL7 = (
    "MSH|^~\\&|EHVT-50|HUELLAS LAB|||20260414164534||ORU^R01||P|2.3.1||||||UNICODE UTF-8\n"
    "PID|1||||||20240414|F|kitty felina 2a Laura Cepeda|DOG|||\n"
    "PV1|1|O|||||||||||||||||\n"
    "OBR|1|||CBC^Complete Blood Count|R|20260414164017|20260414164017|20260414164017|||||||\n"
    "OBX|1|ST|WBC^||11.02|10*9/L|5.05 - 16.76|N|||F\n"
    "OBX|2|ST|NEU#^||4.96|10*9/L|2.95 - 11.64|N|||F\n"
    "OBX|3|ST|NST/WBC%^||0.66|%|0.00 - 10.00|N|||F\n"
    "OBX|4|ED|WBC_Main^||base64imagedata==|||||F\n"
)


HEARTBEAT_HL7 = (
    "MSH|^~\\&|HEARTBEAT|SENDER|RECEIVER|SYSTEM|20260416211909||ZHB^H00|HB000001|P|2.3.1"
)


HEARTBEAT_HL7_ALT = (
    "MSH|^~\\&|EHVT-50|HUELLAS LAB|||20260417004110||ZHB^H00|HB000001|P|2.3.1"
)


# ── Tests ────────────────────────────────────────────────────────────────────


def test_parse_valid_message():
    """Full HL7 message parses correctly into all fields."""
    parsed = parse_hl7_message(REAL_HL7)

    # Patient
    assert parsed.raw_patient_string == "kitty felina 2a Laura Cepeda"

    # Test type
    assert parsed.test_type_code == "CBC"
    assert parsed.test_type_name == "Hemograma"

    # Received at — extracted from MSH[6]
    assert parsed.received_at.year == 2026
    assert parsed.received_at.month == 4
    assert parsed.received_at.day == 14
    assert parsed.received_at.hour == 16
    assert parsed.received_at.minute == 45
    assert parsed.received_at.second == 34
    assert parsed.received_at.tzinfo == timezone.utc

    # Lab values
    assert len(parsed.lab_values) == 3

    wbc = parsed.lab_values[0]
    assert wbc.parameter_code == "WBC"
    assert wbc.parameter_name_es == "Leucocitos"
    assert wbc.raw_value == "11.02"
    assert wbc.numeric_value == 11.02
    assert wbc.unit == "10*9/L"
    assert wbc.reference_range == "5.05 - 16.76"
    assert wbc.machine_flag == "N"

    neu = parsed.lab_values[1]
    assert neu.parameter_code == "NEU#"
    # NEU resolves to NEU# → full Spanish name
    assert neu.parameter_name_es == "Neutrófilos"
    assert neu.raw_value == "4.96"
    assert neu.numeric_value == 4.96
    assert neu.unit == "10*9/L"
    assert neu.reference_range == "2.95 - 11.64"
    assert neu.machine_flag == "N"

    nst_wbc = parsed.lab_values[2]
    assert nst_wbc.parameter_code == "NST/WBC%"
    # NST/WBC resolves to NST/WBC% → full Spanish name
    assert nst_wbc.parameter_name_es == "Relación bandas/Leucocitos totales %"
    assert nst_wbc.raw_value == "0.66"
    assert nst_wbc.numeric_value == 0.66
    assert nst_wbc.unit == "%"
    assert nst_wbc.reference_range == "0.00 - 10.00"
    assert nst_wbc.machine_flag == "N"

    # Images
    assert len(parsed.images) == 1
    img = parsed.images[0]
    assert img.obs_identifier == "WBC_Main"
    assert img.base64_data == "base64imagedata=="


def test_parse_heartbeat_raises_exception():
    """Heartbeat messages raise HeartbeatMessageException."""
    with pytest.raises(HeartbeatMessageException):
        parse_hl7_message(HEARTBEAT_HL7)


def test_parse_heartbeat_alt_raises_exception():
    """Alternate heartbeat format also raises."""
    with pytest.raises(HeartbeatMessageException):
        parse_hl7_message(HEARTBEAT_HL7_ALT)


def test_parse_malformed_message_raises_error():
    """Malformed HL7 without PID raises parsing error."""
    malformed = (
        "MSH|^~\\&|TEST|LAB|||20260414120000||ORU^R01|1|P|2.3.1\r\n"
        "OBX|1|ST|TEST^Test||value|unit|ref|||F\r\n"
    )
    with pytest.raises(HL7ParsingError):
        parse_hl7_message(malformed)


def test_parse_with_source_lis_file_uses_current_time():
    """When source is LIS_FILE, received_at uses datetime.now() not MSH[6]."""
    from datetime import datetime, timezone

    msg = (
        "MSH|^~\\&|EHVT-50|HUELLAS LAB|||20260414164534||ORU^R01||P|2.3.1|\n"
        "PID|1||||||20240414|F|kitty felina 2a Laura Cepeda|DOG|||\n"
        "OBR|1|||CBC^Complete Blood Count|R|20260414164017|\n"
        "OBX|1|ST|WBC^||11.02|10*9/L|5.05 - 16.76|N|||F\n"
    )

    # Parse with LIS_FILE source - received_at should be very recent
    t_before = datetime.now(timezone.utc)
    parsed = parse_hl7_message(msg, source="LIS_FILE")
    t_after = datetime.now(timezone.utc)

    # received_at should be between t_before and t_after (current time)
    assert t_before <= parsed.received_at <= t_after


def test_parse_without_source_uses_msh6():
    """Without source parameter (default), received_at comes from MSH[6]."""
    msg = (
        "MSH|^~\\&|EHVT-50|HUELLAS LAB|||20260414164534||ORU^R01||P|2.3.1|\n"
        "PID|1||||||20240414|F|kitty felina 2a Laura Cepeda|DOG|||\n"
        "OBR|1|||CBC^Complete Blood Count|R|20260414164017|\n"
        "OBX|1|ST|WBC^||11.02|10*9/L|5.05 - 16.76|N|||F\n"
    )

    parsed = parse_hl7_message(msg)

    assert parsed.received_at.year == 2026
    assert parsed.received_at.month == 4
    assert parsed.received_at.day == 14
    assert parsed.received_at.hour == 16
    assert parsed.received_at.minute == 45
    assert parsed.received_at.second == 34
    assert parsed.received_at.tzinfo == timezone.utc


def test_parse_with_source_lis_ozelle_uses_msh6():
    """When source is LIS_OZELLE, received_at still comes from MSH[6]."""
    msg = (
        "MSH|^~\\&|EHVT-50|HUELLAS LAB|||20260414164534||ORU^R01||P|2.3.1|\n"
        "PID|1||||||20240414|F|kitty felina 2a Laura Cepeda|DOG|||\n"
        "OBR|1|||CBC^Complete Blood Count|R|20260414164017|\n"
        "OBX|1|ST|WBC^||11.02|10*9/L|5.05 - 16.76|N|||F\n"
    )

    parsed = parse_hl7_message(msg, source="LIS_OZELLE")

    assert parsed.received_at.year == 2026
    assert parsed.received_at.month == 4
    assert parsed.received_at.day == 14
    assert parsed.received_at.hour == 16
    assert parsed.received_at.minute == 45
    assert parsed.received_at.second == 34
    assert parsed.received_at.tzinfo == timezone.utc




def test_parse_removes_base64_prefix_from_ed():
    """Base64^ prefix should be removed from ED (image) segments."""
    msg = (
        "MSH|^~\\&|EHVT-50|HUELLAS LAB|||20260414164534||ORU^R01||P|2.3.1|\n"
        "PID|1||||||20240414|F|kitty felina 2a Laura Cepeda|DOG|||\n"
        "OBR|1|||CBC^Complete Blood Count|R|20260414164017|\n"
        "OBX|1|ED|WBC_Main||Base64^/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAEBAQE|\n"
    )

    parsed = parse_hl7_message(msg)

    assert len(parsed.images) == 1
    # The Base64^ prefix should be stripped
    assert parsed.images[0].base64_data == "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAEBAQE"
    assert not parsed.images[0].base64_data.startswith("Base64^")


def test_parse_keeps_base64_data_without_prefix():
    """ED segment without Base64^ prefix should be kept as-is."""
    msg = (
        "MSH|^~\\&|EHVT-50|HUELLAS LAB|||20260414164534||ORU^R01||P|2.3.1|\n"
        "PID|1||||||20240414|F|kitty felina 2a Laura Cepeda|DOG|||\n"
        "OBR|1|||CBC^Complete Blood Count|R|20260414164017|\n"
        "OBX|1|ED|WBC_Main||/9j/4AAQSkZJRgABAQAAAQABAAD|\n"
    )

    parsed = parse_hl7_message(msg)

    assert len(parsed.images) == 1
    # Should be unchanged when no prefix
    assert parsed.images[0].base64_data == "/9j/4AAQSkZJRgABAQAAAQABAAD"


def test_parse_numeric_obx_with_suffix_identifier():
    """Numeric OBX with identifier containing a suffix should translate base correctly."""
    msg = (
        "MSH|^~\\&|EHVT-50|HUELLAS LAB|||20260414164534||ORU^R01||P|2.3.1|\n"
        "PID|1||||||20240414|F|kitty felina 2a Laura Cepeda|DOG|||\n"
        "OBR|1|||CBC^Complete Blood Count|R|20260414164017|\n"
        "OBX|1|ST|WBC_Main^||11.02|10*9/L|5.05 - 16.76|N|||F\n"
    )
    parsed = parse_hl7_message(msg)

    assert len(parsed.lab_values) == 1
    wbc = parsed.lab_values[0]
    assert wbc.parameter_code == "WBC_Main"
    assert wbc.parameter_name_es == "Leucocitos"
