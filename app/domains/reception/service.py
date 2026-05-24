from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.reception.schemas import RawPatientInput, BaulResult
from app.shared.models.test_result import TestResult
from app.domains.reception.merge_service import TestResultMergeService
from app.services.appsheet import AppSheetPatient
from app.domains.reception.appsheet_service import AppSheetSyncService
from app.domains.reception.query_service import WaitingRoomQueryService
from app.domains.reception.upload_handler import FileUploadHandler
from app.domains.reception.intake_service import PatientIntakeService


class ReceptionService:
    """Orchestrates the full reception flow:
    RawPatientInput → normalize → Baúl → BaulResult
    """

    def __init__(self):
        from app.domains.reception.archive_service import PatientArchiveService
        from app.domains.reception.delete_service import PatientDeleteService

        self._appsheet = AppSheetSyncService()
        self._archive = PatientArchiveService()
        self._delete = PatientDeleteService()
        self._query = WaitingRoomQueryService()
        self._upload = FileUploadHandler(receive_fn=self.receive)
        self._merge = TestResultMergeService()
        self._intake = PatientIntakeService()

    async def receive(
        self, raw_input: RawPatientInput, session: AsyncSession
    ) -> BaulResult:
        """Delegates to PatientIntakeService."""
        return await self._intake.receive(raw_input, session)

    async def sync_from_appsheet(
        self, patients: list[AppSheetPatient], session: AsyncSession, reset: bool = False
    ) -> int:
        """Delegates to AppSheetSyncService."""
        return await self._appsheet.sync_from_appsheet(patients, session, reset)

    async def clear_all_active_patients(self, session: AsyncSession) -> int:
        """Delegates to AppSheetSyncService."""
        return await self._appsheet.clear_all_active_patients(session)

    async def get_waiting_room_patients(
        self, session: AsyncSession
    ) -> list[dict]:
        """Delegates to WaitingRoomQueryService."""
        return await self._query.get_waiting_room_patients(session)

    async def delete_patient_from_waiting_room(
        self, patient_id: int, session: AsyncSession
    ) -> bool:
        """Delegates to PatientDeleteService."""
        return await self._delete.delete_patient_from_waiting_room(patient_id, session)

    async def inject_patient_to_taller(
        self, patient_id: int, session: AsyncSession
    ) -> TestResult | None:
        """Delegates to TestResultMergeService."""
        return await self._merge.inject_patient_to_taller(patient_id, session)

    async def handle_uploaded_file(self, file_content: bytes, file_type: str, session: AsyncSession) -> str:
        """Delegates to FileUploadHandler."""
        return await self._upload.handle_uploaded_file(file_content, file_type, session)

    # ── Archiving (soft-hide via status flag) ──────────────────────────

    async def archive_all_active(self, session: AsyncSession) -> int:
        """Delegates to PatientArchiveService."""
        return await self._archive.archive_all_active(session)

    async def restore_all_archived(self, session: AsyncSession) -> int:
        """Delegates to PatientArchiveService."""
        return await self._archive.restore_all_archived(session)

    async def restore_single_archived(self, patient_id: int, session: AsyncSession) -> bool:
        """Delegates to PatientArchiveService."""
        return await self._archive.restore_single_archived(patient_id, session)

    async def get_archived_patients(self, session: AsyncSession) -> list[dict]:
        """Delegates to PatientArchiveService."""
        return await self._archive.get_archived_patients(session)

    async def get_single_patient_for_card(
        self, patient_id: int, session: AsyncSession
    ) -> dict | None:
        """Delegates to WaitingRoomQueryService."""
        return await self._query.get_single_patient_for_card(patient_id, session)
