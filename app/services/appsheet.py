import json
from datetime import datetime, timezone
from typing import List, Optional

import httpx
import logfire
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.config import settings
from app.domains.exam_order.service import ExamOrderService
from app.domains.patients.models import Patient
from app.services.provenance_recorder import ProvenanceRecorder
from app.services.session_code_extractor import SessionCodeExtractor
from app.shared.models.data_quarantine import DataQuarantine
from app.shared.models.raw_data_log import RawDataSource


class AppSheetPatient(BaseModel):
    session_code: str = Field(default="", alias="Codigo_Corto")
    vet_name: str = Field(default="", alias="Doctora")
    category: str = Field(default="", alias="Categoria_Examen")
    test_type: str = Field(default="", alias="Examen_Especifico")
    name: str = Field(default="", alias="Nombre_Mascota")
    species: str = Field(default="", alias="Especie")
    gender: str = Field(default="", alias="Sexo")
    age_number: str = Field(default="", alias="Edad_Numero")
    age_unit: str = Field(default="", alias="Edad_Unidad")
    owner_name: str = Field(default="", alias="Nombre_Tutor")
    breed: str = Field(default="", alias="Raza")

    class Config:
        populate_by_name = True


class AppSheetService:
    def __init__(self, api_key: Optional[str] = None, app_id: Optional[str] = None):
        self.api_key = api_key or settings.get("APPSHEET_API_KEY")
        self.app_id = app_id or settings.get("APPSHEET_APP_ID")
        self.table_name = settings.get("APPSHEET_TABLE_NAME", "Muestras_Activas")
        self.base_url = f"https://api.appsheet.com/api/v2/apps/{self.app_id}/tables/{self.table_name}/Action"
        self._exam_order_service = ExamOrderService()

    async def fetch_active_patients(
        self, session: Optional[AsyncSession] = None
    ) -> List[AppSheetPatient]:
        if not self.api_key or not self.app_id:
            raise ValueError("APPSHEET_API_KEY and APPSHEET_APP_ID must be configured")

        headers = {
            "ApplicationAccessKey": self.api_key,
            "Content-Type": "application/json"
        }

        payload = {
            "Action": "Find",
            "Properties": {
                "Locale": "es-CO",
                "Timezone": "SA Pacific Standard Time"
            },
            "Rows": []
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()

            # ── Provenance recording: capture raw JSON BEFORE parsing ──────
            if session is not None:
                try:
                    raw_json = json.dumps(data)
                    await ProvenanceRecorder.record_sync(
                        session=session,
                        source=RawDataSource.APPSHEET,
                        raw_data=raw_json,
                        received_at=datetime.now(timezone.utc),
                    )
                except Exception:
                    pass  # Capture failure must never block processing

            # AppSheet returns a list of rows
            if not isinstance(data, list):
                # Sometimes AppSheet returns a dict with "Rows" or similar depending on the exact action
                # but usually "Find" returns a list directly or a list inside a key.
                # Based on user info, it's a list of patients.
                if isinstance(data, dict) and "Rows" in data:
                    data = data["Rows"]
                else:
                    return []

            # ── Gatekeeper: filter rows without valid session_code ───────────
            parsed = [AppSheetPatient(**row) for row in data]
            valid_patients = []
            for patient in parsed:
                code = SessionCodeExtractor.extract(patient.name)
                if not code:
                    logfire.warning(
                        f"AppSheet gatekeeper rejection: no valid session_code "
                        f"in patient name '{patient.name}' (Codigo_Corto={patient.session_code})"
                    )
                    try:
                        if session is not None:
                            q = DataQuarantine(
                                source="appsheet",
                                raw_data=patient.model_dump_json(by_alias=True),
                                received_at=datetime.now(timezone.utc),
                                rejection_reason="missing_code",
                            )
                            session.add(q)
                            await session.commit()
                    except Exception:
                        logfire.warning(
                            "Failed to insert quarantine record for AppSheet gatekeeper rejection",
                            _exc_info=True,
                        )
                    # Skip this patient — do NOT include in returned list
                    continue
                valid_patients.append(patient)

            return valid_patients

    async def sync_from_appsheet(
        self, patients: List[AppSheetPatient], session: AsyncSession, reset: bool = False
    ) -> int:
        """Synchronize AppSheet patients into ExamOrder records.

        For each AppSheetPatient row, creates or updates an ExamOrder via
        ``ExamOrderService.create_from_appsheet()``.

        Returns the number of successfully processed rows.

        .. note::
           The ``reset`` parameter is accepted for backward compatibility
           with the existing ReceptionService sync. When ``True``, existing
           ExamOrders are not reset — only the create/update logic runs.
        """
        count = 0
        for patient in patients:
            try:
                # Resolve patient_id from the session_code lookup
                stmt = select(Patient).where(Patient.session_code == patient.session_code)
                result = await session.execute(stmt)
                existing_patient = result.scalar_one_or_none()
                patient_id = str(existing_patient.id) if existing_patient else ""

                # Build the raw data dict expected by ExamOrderService
                data = patient.model_dump(by_alias=True)
                row_data = {
                    "Codigo_Corto": data.get("Codigo_Corto", ""),
                    "Examen_Especifico": data.get("Examen_Especifico", ""),
                    "Paciente_ID": patient_id,
                }

                await self._exam_order_service.create_from_appsheet(row_data, session)
                count += 1
            except Exception as e:
                logfire.warning(f"Error syncing AppSheet patient to ExamOrder: {e}")
                # Don't fail the entire batch — log and continue

        logfire.info(f"sync_from_appsheet: processed {count}/{len(patients)} rows")
        return count
