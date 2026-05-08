import pytest
from unittest.mock import patch, MagicMock
from app.tasks.hl7_processor import process_uploaded_batch
from app.domains.reception.schemas import PatientSource

# Mock the dramatiq.actor decorator to allow direct calling of the function
@pytest.fixture(autouse=True)
def mock_dramatiq_actor():
    with patch("dramatiq.actor", lambda **kwargs: lambda fn: fn):
        yield

# Mock the Redis set_upload_status
@pytest.fixture(autouse=True)
def mock_set_upload_status():
    with patch("app.tasks.hl7_processor.set_upload_status") as mock_set:
        yield mock_set

# Mock process_hl7_message.send
@pytest.fixture
def mock_process_hl7_message_send():
    with patch("app.tasks.hl7_processor.process_hl7_message.send") as mock_send:
        yield mock_send

def test_process_uploaded_batch_splits_and_sends_messages(mock_process_hl7_message_send, mock_set_upload_status):
    # Simulate a batch file with multiple HL7 messages
    hl7_message_1 = "MSH|^~\\&|LIS|OZELLE|HOSPITAL|LAB|202301011200||ORU^R01|MSG001|P|2.5\nPID|1||PATIENT1"
    hl7_message_2 = "MSH|^~\\&|LIS|OZELLE|HOSPITAL|LAB|202301011201||ORU^R01|MSG002|P|2.5\nPID|1||PATIENT2"
    
    batch_content = f"{hl7_message_1}\n{hl7_message_2}"
    
    upload_id = "test_upload_id_1"
    file_type = "ozelle"
    
    process_uploaded_batch(batch_content, file_type, upload_id)
    
    # Assert that process_hl7_message.send was called for each message
    assert mock_process_hl7_message_send.call_count == 2
    mock_process_hl7_message_send.assert_any_call(hl7_message_1, PatientSource.LIS_OZELLE.value)
    mock_process_hl7_message_send.assert_any_call(hl7_message_2, PatientSource.LIS_OZELLE.value)
    
    # Assert that status was set to complete with correct count
    mock_set_upload_status.assert_called_with(upload_id, "complete:", 2)

def test_process_uploaded_batch_filters_heartbeat_messages(mock_process_hl7_message_send, mock_set_upload_status):
    # Simulate a batch file with one normal and one heartbeat message
    hl7_message_normal = "MSH|^~\\&|LIS|OZELLE|HOSPITAL|LAB|202301011200||ORU^R01|MSG001|P|2.5\nPID|1||PATIENT1"
    hl7_message_heartbeat = "MSH|^~\\&|LIS|OZELLE|HOSPITAL|LAB|202301011205||ZHB^H00|HB001|P|2.5\n" # MSH-9 contains ZHB^H00
    
    batch_content = f"{hl7_message_normal}\n{hl7_message_heartbeat}"
    
    upload_id = "test_upload_id_2"
    file_type = "ozelle"
    
    process_uploaded_batch(batch_content, file_type, upload_id)
    
    # Assert that process_hl7_message.send was called only for the normal message
    assert mock_process_hl7_message_send.call_count == 1
    mock_process_hl7_message_send.assert_any_call(hl7_message_normal, PatientSource.LIS_OZELLE.value)
    
    # Assert that status was set to complete with correct count (only 1 message processed)
    mock_set_upload_status.assert_called_with(upload_id, "complete:", 1)

def test_process_uploaded_batch_handles_empty_content(mock_process_hl7_message_send, mock_set_upload_status):
    upload_id = "test_upload_id_empty"
    file_type = "ozelle"
    
    process_uploaded_batch("", file_type, upload_id)
    
    # No messages should be sent
    assert mock_process_hl7_message_send.call_count == 0
    # Status should reflect 0 processed messages
    mock_set_upload_status.assert_called_with(upload_id, "complete:", 0)

def test_process_uploaded_batch_handles_parsing_errors_gracefully(mock_process_hl7_message_send, mock_set_upload_status):
    # Simulate a batch with one valid and one malformed message
    hl7_message_valid = "MSH|^~\\&|LIS|OZELLE|HOSPITAL|LAB|202301011200||ORU^R01|MSG001|P|2.5\nPID|1||PATIENT1"
    hl7_message_malformed_trailing = "\nTHIS IS NOT A VALID HL7 MESSAGE" # Content after valid HL7 message
    
    batch_content = f"{hl7_message_valid}{hl7_message_malformed_trailing}"
    
    upload_id = "test_upload_id_error"
    file_type = "ozelle"
    
    # We expect process_uploaded_batch to send the entire chunk it received from the splitter
    # even if it contains malformed trailing data, as the splitter doesn't filter that out.
    # The actual parsing error would occur within the process_hl7_message actor.
    
    process_uploaded_batch(batch_content, file_type, upload_id)
    
    # Assert that process_hl7_message.send was called exactly once, with the combined message
    assert mock_process_hl7_message_send.call_count == 1
    mock_process_hl7_message_send.assert_any_call(batch_content, PatientSource.LIS_OZELLE.value)
    
    # Assert that status was set to complete with count of attempted messages
    # Even if process_hl7_message fails, the batch processor considers it "processed" (attempted)
    mock_set_upload_status.assert_called_with(upload_id, "complete:", 1)

@pytest.mark.asyncio
async def test_process_uploaded_batch_overall_error_handling(mock_process_hl7_message_send, mock_set_upload_status):
    # Simulate an error during splitting or initial processing
    def faulty_split(*args, **kwargs):
        raise Exception("Simulated critical splitting error")

    # Temporarily patch the split_hl7_batch function
    with patch("app.tasks.hl7_processor.split_hl7_batch", side_effect=faulty_split):
        upload_id = "test_upload_id_critical_error"
        file_type = "ozelle"
        
        process_uploaded_batch("some content", file_type, upload_id)
        
        # Should not call process_hl7_message.send
        mock_process_hl7_message_send.assert_not_called()
        
        # Should set an error status
        mock_set_upload_status.assert_called_once()
        args, _ = mock_set_upload_status.call_args
        assert args[0] == upload_id
        assert args[1].startswith("error:")
        assert "Simulated critical splitting error" in args[1]