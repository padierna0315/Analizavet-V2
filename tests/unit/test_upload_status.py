import pytest
from unittest.mock import patch, MagicMock
from app.tasks.hl7_processor import set_upload_status, get_upload_status
from app.config import settings

@pytest.fixture
def mock_redis():
    with patch("redis.from_url") as mock_from_url:
        mock_redis_instance = MagicMock()
        mock_from_url.return_value = mock_redis_instance
        yield mock_redis_instance

def test_set_upload_status_processing(mock_redis):
    upload_id = "test_id_processing"
    status = "processing"
    set_upload_status(upload_id, status)
    mock_redis.setex.assert_called_once_with(f"upload:{upload_id}:status", 300, status)

def test_set_upload_status_complete(mock_redis):
    upload_id = "test_id_complete"
    status = "complete:"
    count = 5
    set_upload_status(upload_id, status, count)
    mock_redis.setex.assert_called_once_with(f"upload:{upload_id}:status", 300, f"{status}{count}")

def test_set_upload_status_error(mock_redis):
    upload_id = "test_id_error"
    status = "error:Something went wrong"
    set_upload_status(upload_id, status)
    mock_redis.setex.assert_called_once_with(f"upload:{upload_id}:status", 300, status)

def test_get_upload_status_found(mock_redis):
    upload_id = "test_id_found"
    expected_status = "complete:10"
    mock_redis.get.return_value = expected_status.encode('utf-8')
    
    result = get_upload_status(upload_id)
    mock_redis.get.assert_called_once_with(f"upload:{upload_id}:status")
    assert result == expected_status

def test_get_upload_status_not_found(mock_redis):
    upload_id = "test_id_not_found"
    mock_redis.get.return_value = None
    
    result = get_upload_status(upload_id)
    mock_redis.get.assert_called_once_with(f"upload:{upload_id}:status")
    assert result is None
