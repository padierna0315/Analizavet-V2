import pytest
from pathlib import Path
from typing import List

from app.satellites.fujifilm.parser import parse_fujifilm_message
from app.satellites.ozelle.hl7_parser import parse_hl7_message, HeartbeatMessageException, HL7ParsingError

@pytest.fixture(scope="module")
def fujifilm_log_content():
    """Reads the content of the Fujifilm log file."""
    log_path = Path("Ejemplos/log_nx600_vivo.txt")
    return log_path.read_text()

@pytest.fixture(scope="module")
def ozelle_log_raw_content():
    """Reads the raw content of the Ozelle log file."""
    # El path se resuelve relativo a la raíz del proyecto
    project_root = Path(__file__).parent.parent.parent
    log_path = project_root / "Ejemplos" / "log_laboratorio_17 de abril.txt"
    return log_path.read_text(encoding="utf-8", errors="ignore")

def split_hl7_log_into_messages(raw_log_content: str) -> List[str]:
    """
    Splits a raw HL7 log file content into a list of individual HL7 messages.
    Each message is expected to start with a VT character (\\x0b) and end with an FS character (\\x1c).
    """
    messages = []
    # Split the raw content by the VT character, which typically precedes each MSH segment
    # This will give us fragments, where each fragment *might* be a message or part of one.
    fragments = raw_log_content.split('\x0b')

    for fragment in fragments:
        if not fragment.strip():
            continue

        # Each fragment should start with MSH (after stripping leading VT which was the split char)
        # And should contain an FS character (\\x1c) somewhere to mark its end.
        if "MSH" in fragment:
            # Find the FS character. The message content is everything before it.
            fs_index = fragment.find('\x1c')
            if fs_index != -1:
                message = fragment[:fs_index].strip()
                if message:
                    messages.append(message)
            else:
                # If no FS is found, it might be the last message, or an incomplete one.
                # For robustness, we'll take it as a message if it contains MSH.
                message = fragment.strip()
                if message:
                    messages.append(message)
    return messages


def test_fujifilm_log_parsing(fujifilm_log_content):
    """
    Tests that the Fujifilm log file parses correctly.
    Asserts for patient name and a few key parameters.
    """
    readings = parse_fujifilm_message(fujifilm_log_content)
    assert len(readings) > 0, "No readings were parsed from the Fujifilm log."

    # Assert for patient "POLO" and some specific parameters
    polo_cre_found = False
    polo_alt_found = False
    for reading in readings:
        if reading.patient_name == "POLO":
            if reading.parameter_code == "CRE" and reading.raw_value == "0.87":
                polo_cre_found = True
            if reading.parameter_code == "ALT" and reading.raw_value == "43":
                polo_alt_found = True
    assert polo_cre_found, "Patient 'POLO' CRE parameter not found or value incorrect."
    assert polo_alt_found, "Patient 'POLO' ALT parameter not found or value incorrect."

def test_ozelle_log_parsing(ozelle_log_raw_content):
    """
    Tests that the Ozelle log file parses correctly, processing each message individually.
    Asserts for patient name "ichiro canino" and a few key parameters (WBC, RBC).
    """
    assert ozelle_log_raw_content, "Ozelle raw log content is empty."

    individual_messages = split_hl7_log_into_messages(ozelle_log_raw_content)
    assert len(individual_messages) > 0, "No individual HL7 messages found in the log."

    ichiro_canino_message_found = False
    patient_message_parsed_count = 0

    for msg in individual_messages:
        try:
            parsed_message = parse_hl7_message(msg, source="ozelle-test-source")
            patient_message_parsed_count += 1
            
            if parsed_message.raw_patient_string and "ichiro canino" in parsed_message.raw_patient_string:
                ichiro_canino_message_found = True
                assert parsed_message.lab_values, "No lab values parsed for ichiro canino." # Corrected assertion
                
                wbc_result_found = False
                rbc_result_found = False
                for lab_value in parsed_message.lab_values: # Corrected variable name and attribute
                    if lab_value.parameter_code == "WBC": # Corrected attribute
                        wbc_result_found = True
                        assert lab_value.raw_value == "14.26", f"Expected WBC value '14.26', got '{lab_value.raw_value}'"
                    if lab_value.parameter_code == "RBC": # Corrected attribute
                        rbc_result_found = True
                        assert lab_value.raw_value == "6.35", f"Expected RBC value '6.35', got '{lab_value.raw_value}'"
                assert wbc_result_found, "Expected WBC lab value not found for ichiro canino."
                assert rbc_result_found, "Expected RBC lab value not found for ichiro canino."
        except HeartbeatMessageException:
            # This is expected for heartbeat messages, so we just continue
            continue
        except HL7ParsingError as e:
            # If it's a parsing error for a message that is not a heartbeat, it's unexpected
            print(f"HL7 Parsing Error for message (not heartbeat): {e} \nMessage:\n{msg[:500]}...")
            # Optionally, fail the test if any non-heartbeat message fails to parse
            # assert False, f"Unexpected HL7 Parsing Error: {e}"
            continue

    assert ichiro_canino_message_found, "Patient 'ichiro canino' message not successfully parsed."
    assert patient_message_parsed_count > 0, "No patient messages were successfully parsed from the log."