"""
Tests for FileUploadHandler — extracted from ReceptionService.handle_uploaded_file.
Verbatim extraction — zero behavioral change.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestFileUploadHandler:
    """
    Unit tests for FileUploadHandler.handle_uploaded_file.
    Tests the routing logic and error handling.
    """

    # ── RED: test file references code that doesn't exist yet ──────────

    def test_class_exists(self):
        """FileUploadHandler class can be imported."""
        from app.domains.reception.upload_handler import FileUploadHandler  # noqa: F811

        handler = FileUploadHandler()
        assert handler is not None

    @pytest.mark.asyncio
    async def test_unknown_file_type_raises_value_error(self):
        """GIVEN any content with unknown file_type
        WHEN handle_uploaded_file is called
        THEN ValueError is raised with 'Tipo de archivo no soportado' message."""
        from app.domains.reception.upload_handler import FileUploadHandler  # noqa: F811

        handler = FileUploadHandler()
        mock_session = AsyncMock()

        with pytest.raises(ValueError, match="Tipo de archivo no soportado"):
            await handler.handle_uploaded_file(b"dummy", "unknown_type", mock_session)

    @pytest.mark.asyncio
    async def test_ozelle_type_routes_correctly(self):
        """GIVEN Ozelle HL7 batch content
        WHEN handle_uploaded_file is called with file_type='ozelle'
        THEN upload_id is returned and the ozelle parsing pipeline is invoked."""
        from app.domains.reception.upload_handler import FileUploadHandler  # noqa: F811

        handler = FileUploadHandler()
        mock_session = AsyncMock()

        with (
            patch(
                "app.domains.reception.upload_handler.set_upload_status"
            ) as mock_set_status,
            patch(
                "app.domains.reception.upload_handler.split_hl7_batch",
                return_value=["MSH|...", "MSH|..."],
            ),
            patch(
                "app.domains.reception.upload_handler.parse_hl7_message",
            ) as mock_parse,
            patch(
                "app.domains.reception.upload_handler._async_process_pipeline",
            ) as mock_pipeline,
        ):
            mock_parsed = MagicMock()
            mock_parse.return_value = mock_parsed

            upload_id = await handler.handle_uploaded_file(
                b"dummy ozelle content", "ozelle", mock_session
            )

            # upload_id is a UUIDv4 string (36 chars)
            assert upload_id is not None
            assert len(upload_id) == 36

            # set_upload_status called twice: "processing" + "complete:2"
            assert mock_set_status.call_count == 2
            mock_set_status.assert_any_call(upload_id, "processing")

            # parse called for each message
            assert mock_parse.call_count == 2
            # pipeline called for each message
            assert mock_pipeline.call_count == 2
            assert mock_pipeline.await_count == 2

    @pytest.mark.asyncio
    async def test_fujifilm_type_routes_correctly(self):
        """GIVEN Fujifilm content
        WHEN handle_uploaded_file is called with file_type='fujifilm'
        THEN upload_id is returned and Dramatiq actor is invoked per record."""
        from app.domains.reception.upload_handler import FileUploadHandler  # noqa: F811

        handler = FileUploadHandler()
        mock_session = AsyncMock()

        fake_records = [
            MagicMock(internal_id="908", patient_name="POLO",
                       parameter_code="CRE", raw_value="0.87"),
        ]

        with (
            patch(
                "app.domains.reception.upload_handler.set_upload_status"
            ) as mock_set_status,
            patch(
                "app.domains.reception.upload_handler.init_upload_counter"
            ) as mock_init_counter,
            patch(
                "app.satellites.fujifilm.parser.parse_fujifilm_message",
                return_value=fake_records,
            ),
            patch(
                "app.tasks.fujifilm_processor.process_fujifilm_message"
            ) as mock_actor,
        ):
            upload_id = await handler.handle_uploaded_file(
                b"dummy fujifilm content", "fujifilm", mock_session
            )

            assert upload_id is not None
            assert len(upload_id) == 36

            mock_set_status.assert_any_call(upload_id, "processing")
            mock_actor.send.assert_called_once()
            mock_init_counter.assert_called_once_with(upload_id, 1)

    @pytest.mark.asyncio
    async def test_json_type_routes_correctly(self):
        """GIVEN JSON baptism content
        WHEN handle_uploaded_file is called with file_type='json'
        THEN receive callback is invoked and upload_id is returned."""
        from app.domains.reception.upload_handler import FileUploadHandler  # noqa: F811

        mock_receive = AsyncMock()
        handler = FileUploadHandler(receive_fn=mock_receive)
        mock_session = AsyncMock()

        # JSON with raw_string
        json_content = b'{"raw_string": "Canino|Macho|PEPE|...|5|a\\u00f1os"}'

        with patch(
            "app.domains.reception.upload_handler.set_upload_status"
        ) as mock_set_status:
            upload_id = await handler.handle_uploaded_file(
                json_content, "json", mock_session
            )

            assert upload_id is not None
            assert len(upload_id) == 36

            mock_set_status.assert_called_once_with(upload_id, "processing")
            mock_receive.assert_called_once()

    @pytest.mark.asyncio
    async def test_json_missing_raw_string_raises_value_error(self):
        """GIVEN JSON content without 'raw_string' key
        WHEN handle_uploaded_file is called with file_type='json'
        THEN ValueError is raised."""
        from app.domains.reception.upload_handler import FileUploadHandler  # noqa: F811

        handler = FileUploadHandler()
        mock_session = AsyncMock()

        malformed = b'{"other": "data"}'

        with patch("app.domains.reception.upload_handler.set_upload_status"):
            with pytest.raises(ValueError, match="raw_string"):
                await handler.handle_uploaded_file(malformed, "json", mock_session)

    @pytest.mark.asyncio
    async def test_json_malformed_raises_value_error(self):
        """GIVEN malformed JSON content
        WHEN handle_uploaded_file is called with file_type='json'
        THEN ValueError is raised."""
        from app.domains.reception.upload_handler import FileUploadHandler  # noqa: F811

        handler = FileUploadHandler()
        mock_session = AsyncMock()

        bad_json = b"{not valid json}"

        with patch("app.domains.reception.upload_handler.set_upload_status"):
            with pytest.raises(ValueError, match="malformado"):
                await handler.handle_uploaded_file(bad_json, "json", mock_session)
