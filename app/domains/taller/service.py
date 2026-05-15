import re
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select
import logfire

from app.shared.models.test_result import TestResult
from app.shared.models.lab_value import LabValue
from app.shared.models.patient_image import PatientImage
from app.domains.patients.models import Patient
from app.domains.exam_order.service import ExamOrderService
from app.domains.taller.schemas import (
    FlagBatchRequest, FlagBatchResult,
    ImageUploadRequest, ImageUploadResult,
    RawLabValueInput,
)
from app.domains.taller.engine import TallerFlaggingEngine
from app.domains.taller.images import ImageHandlingService
from app.domains.taller.flagging import ClinicalFlaggingService
from app.core.reference import get_reference_range
from clinical_standards import (
    get_parameter_group, get_parameter_name, PARAMETER_GROUPS, PARAMETER_GROUPS_ORDER, STANDARDS_MAPPING
)
from app.shared.algorithms.registry import AlgorithmRegistry
from app.shared.algorithms.interpretations import INTERPRETATIONS

_PART_PATTERN = re.compile(r"_Part\d+$")
_KNOWN_SUFFIXES = {"Main", "Histo", "Distribution"}


def _clean_parameter_code(raw_code: str) -> str:
    """Strip machine suffixes and resolve aliases to get canonical parameter code.

    Examples:
        "WBC_Main" → "WBC"
        "LYM_Part3" → "LYM"
        "NSG#" → "NSG#" (keep #, it's part of the code)
        "NEU%" → "NEU%" (keep %, it's part of the code)
    """
    code = raw_code

    # Strip known suffixes
    for suffix in _KNOWN_SUFFIXES:
        if code.endswith(f"_{suffix}"):
            code = code[:-(len(suffix) + 1)]
            break

    # Strip _PartN suffix
    part_match = _PART_PATTERN.search(code)
    if part_match:
        code = code[:part_match.start()]

    # Resolve alias
    return STANDARDS_MAPPING.get(code, code)


class TallerService:
    """Orchestrates the Taller: flagging + image handling."""

    def __init__(self):
        self._engine = TallerFlaggingEngine()
        self._images = ImageHandlingService()
        self._flagging = ClinicalFlaggingService()

    async def create_test_result(
        self,
        patient_id: int,
        test_type: str,
        test_type_code: str,
        source: str,
        received_at: datetime,
        session: AsyncSession,
    ) -> TestResult:
        """Create a new TestResult record for a patient."""
        tr = TestResult(
            patient_id=patient_id,
            test_type=test_type,
            test_type_code=test_type_code,
            source=source,
            status="pendiente",
            received_at=received_at,
        )
        session.add(tr)
        await session.commit()
        await session.refresh(tr)
        logfire.info(f"TestResult creado: id={tr.id} patient={patient_id} tipo={test_type}")
        return tr

    async def flag_and_store(
        self,
        test_result_id: int,
        species: str,
        values: list[RawLabValueInput],
        session: AsyncSession,
    ) -> FlagBatchResult:
        """Flag all lab values and store in DB."""
        request = FlagBatchRequest(
            test_result_id=test_result_id,
            species=species,
            values=values,
        )
        return await self._engine.flag_test_result(request, session)

    async def save_images(
        self,
        request: ImageUploadRequest,
        session: AsyncSession,
    ) -> ImageUploadResult:
        return await self._images.save_images(request, session)

    async def update_test_result_metadata(
        self,
        test_result_id: int,
        form_data: dict,
        session: AsyncSession,
    ) -> TestResult:
        tr = await session.get(TestResult, test_result_id)
        if not tr:
            raise ValueError(f"TestResult con ID {test_result_id} no encontrado")

        tr.doctor_name = form_data.get("doctor_name") or None
        tr.copro_color = form_data.get("copro_color") or None
        tr.copro_consistencia = form_data.get("copro_consistencia") or None
        tr.copro_olor = form_data.get("copro_olor") or None
        moco_val = form_data.get("copro_moco")
        tr.copro_moco = True if moco_val == "true" else (False if moco_val == "false" else None)
        tr.cito_color = form_data.get("cito_color") or None
        tr.cito_turbidez = form_data.get("cito_turbidez") or None
        tr.cito_aspecto = form_data.get("cito_aspecto") or None

        session.add(tr)
        await session.commit()
        await session.refresh(tr)
        logfire.info(f"TestResult {tr.id} metadata updated.")
        return tr

    async def update_lab_values_from_form(
        self,
        test_result_id: int,
        form_data: dict,
        session: AsyncSession,
    ) -> None:
        """Update lab values and recalculate their flags based on form data."""
        result = await session.execute(
            select(TestResult)
            .where(TestResult.id == test_result_id)
            .options(
                selectinload(TestResult.patient),
                selectinload(TestResult.lab_values)
            )
        )
        tr = result.scalars().first()
        if not tr:
            raise ValueError(f"TestResult {test_result_id} no encontrado")

        species = tr.patient.species if tr.patient else "Canino"

        for lv in tr.lab_values:
            form_key = f"value_{lv.parameter_code}"
            if form_key in form_data:
                raw_val = form_data[form_key]
                lv.raw_value = str(raw_val)
                try:
                    lv.numeric_value = float(raw_val) if str(raw_val).strip() else None
                except (ValueError, TypeError):
                    lv.numeric_value = None

                clean_code = _clean_parameter_code(lv.parameter_code)
                if lv.numeric_value is not None:
                    try:
                        flag_result = self._flagging.flag_value(
                            parameter=clean_code,
                            value=lv.numeric_value,
                            unit=lv.unit,
                            species=species,
                        )
                        lv.flag = flag_result.flag
                    except ValueError:
                        lv.flag = "NORMAL"
                else:
                    lv.flag = "NORMAL"
                
                session.add(lv)
        
        await session.commit()
        logfire.info(f"Lab values for TestResult {test_result_id} updated from form.")


    async def get_test_result_full(
        self,
        test_result_id: int,
        session: AsyncSession,
    ) -> dict | None:
        """Get TestResult with all LabValues, images, and patient info.

        Usa una sola consulta con eager loading (Tubería Maestra) para evitar
        el problema N+1. La regla de "Estricto con el paciente" garantiza
        que solo traemos resultados que tengan paciente asociado.
        """
        # Una sola consulta que trae TODO: TestResult + Patient + LabValues + Images
        result = await session.execute(
            select(TestResult)
            .where(TestResult.id == test_result_id)
            .join(Patient)  # Regla: estricto con el paciente
            .options(
                selectinload(TestResult.patient),
                selectinload(TestResult.lab_values),
                selectinload(TestResult.images),
            )
        )
        tr = result.scalars().first()
        if not tr:
            return None

        # Los datos ya vienen precargados gracias a selectinload
        patient = tr.patient
        lab_values = tr.lab_values
        images = tr.images

        species = patient.species if patient else "Canino"

        lab_values_list = []
        new_summary = {"ALTO": 0, "NORMAL": 0, "BAJO": 0}

        for lv in lab_values:
            clean_code = _clean_parameter_code(lv.parameter_code)

            # Dynamic resolution from clinical_standards.py
            param_name = get_parameter_name(clean_code, short=False)
            ref_range = get_reference_range(clean_code, species)
            group = get_parameter_group(clean_code)

            # Recompute flag
            if lv.numeric_value is not None:
                try:
                    flag_result = self._flagging.flag_value(
                        parameter=clean_code,
                        value=lv.numeric_value,
                        unit=lv.unit,
                        species=species,
                    )
                    flag = flag_result.flag
                except ValueError:
                    flag = "NORMAL"
            else:
                flag = "NORMAL"

            new_summary[flag] += 1

            lab_values_list.append({
                "id": lv.id,
                "parameter_code": lv.parameter_code,
                "parameter_name_es": param_name,
                "raw_value": lv.raw_value,
                "numeric_value": lv.numeric_value,
                "unit": lv.unit,
                "reference_range": ref_range,
                "flag": flag,
                "machine_flag": lv.machine_flag,
                "group": group,
            })

        # ── Inject BUN/CRE ratio virtual value if both present ────────
        cre_lv = next(
            (lv for lv in lab_values if _clean_parameter_code(lv.parameter_code) == "CRE"),
            None,
        )
        bun_lv_check = next(
            (lv for lv in lab_values if _clean_parameter_code(lv.parameter_code) == "BUN"),
            None,
        )
        if bun_lv_check and cre_lv and bun_lv_check.numeric_value and cre_lv.numeric_value and cre_lv.numeric_value > 0:
            bun_cre_ratio = round(bun_lv_check.numeric_value / cre_lv.numeric_value, 2)
            ratio_ref = get_reference_range("BUNCRE", species)
            try:
                ratio_flag_result = self._flagging.flag_value(
                    parameter="BUNCRE",
                    value=bun_cre_ratio,
                    unit="",
                    species=species,
                )
                ratio_flag = ratio_flag_result.flag
            except ValueError:
                ratio_flag = "NORMAL"

            new_summary[ratio_flag] += 1

            lab_values_list.append({
                "id": None,  # virtual
                "parameter_code": "BUN/CRE",
                "parameter_name_es": "Relación BUN/CRE",
                "raw_value": str(bun_cre_ratio),
                "numeric_value": bun_cre_ratio,
                "unit": "",
                "reference_range": ratio_ref,
                "flag": ratio_flag,
                "machine_flag": None,
                "group": get_parameter_group("BUNCRE"),
            })

        # ── Inject UREA virtual value if BUN is present ──────────────
        bun_lv = next(
            (lv for lv in lab_values if _clean_parameter_code(lv.parameter_code) == "BUN"),
            None,
        )
        if bun_lv and bun_lv.numeric_value is not None:
            urea_value = round(bun_lv.numeric_value * 2.14, 2)
            urea_ref = get_reference_range("UREA", species)
            try:
                urea_flag_result = self._flagging.flag_value(
                    parameter="UREA",
                    value=urea_value,
                    unit="mg/dL",
                    species=species,
                )
                urea_flag = urea_flag_result.flag
            except ValueError:
                urea_flag = "NORMAL"

            new_summary[urea_flag] += 1

            lab_values_list.append({
                "id": None,  # virtual — no DB row
                "parameter_code": "UREA",
                "parameter_name_es": get_parameter_name("UREA", short=False),
                "raw_value": str(urea_value),
                "numeric_value": urea_value,
                "unit": "mg/dL",
                "reference_range": urea_ref,
                "flag": urea_flag,
                "machine_flag": None,
                "group": get_parameter_group("UREA"),
            })

        # Ordenar lab_values por grupo (orden del PDF)
        def sort_key(lv_dict):
            group = lv_dict.get("group", "OTROS")
            try:
                return PARAMETER_GROUPS_ORDER.index(group)
            except ValueError:
                return len(PARAMETER_GROUPS_ORDER)  # OTROS al final

        lab_values_sorted = sorted(lab_values_list, key=sort_key)

        # ── Generate clinical interpretations from flagged values ──────────
        # Run the AlgorithmRegistry in-memory (no DB writes — pure computation)
        # to produce interpretations for derived values (ratios, indices, etc.).
        registry = AlgorithmRegistry()
        algo_results, _algo_errors = registry.run_all(lab_values)

        interpretations = []
        for ar in algo_results:
            interp = INTERPRETATIONS.get(ar.interpretation_key)
            if interp:
                interpretations.append({
                    "parameter_code": ar.lab_value.parameter_code,
                    "parameter_name_es": ar.lab_value.parameter_name_es,
                    "flag": ar.lab_value.flag,
                    "text_es": interp["text_es"],
                    "severity": interp["severity"],
                })

        # ── Look up active ExamOrders for this patient ────────────────
        exam_orders_info: list[dict] = []
        if patient:
            exam_svc = ExamOrderService()
            orders = await exam_svc.get_by_patient(patient.id, session)
            for order in orders:
                exam_orders_info.append({
                    "id": order.id,
                    "session_code": order.session_code,
                    "exam_types": order.exam_types,
                    "status": order.status,
                    "created_at": order.created_at.isoformat() if order.created_at else None,
                })

        return {
            "test_result": {
                "id": tr.id,
                "patient_id": tr.patient_id,
                "test_type": tr.test_type,
                "test_type_code": tr.test_type_code,
                "source": tr.source,
                "status": tr.status,
                "flag_alto_count": new_summary["ALTO"],
                "flag_normal_count": new_summary["NORMAL"],
                "flag_bajo_count": new_summary["BAJO"],
                "received_at": tr.received_at.isoformat(),
                "processed_at": tr.processed_at.isoformat() if tr.processed_at else None,
                "doctor_name": tr.doctor_name,
                "copro_color": tr.copro_color,
                "copro_consistencia": tr.copro_consistencia,
                "copro_olor": tr.copro_olor,
                "copro_moco": tr.copro_moco,
                "cito_color": tr.cito_color,
                "cito_turbidez": tr.cito_turbidez,
                "cito_aspecto": tr.cito_aspecto,
            },
            "patient": {
                "id": patient.id,
                "name": patient.name,
                "species": patient.species,
                "sex": patient.sex,
                "age_display": patient.age_display,
                "owner_name": patient.owner_name,
                "breed": patient.breed,
                "doctor_name": patient.doctor_name,
            } if patient else None,
            "lab_values": lab_values_sorted,
            "images": [
                {
                    "id": img.id,
                    "obs_identifier": img.parameter_code,
                    "parameter_name_es": get_parameter_name(_clean_parameter_code(img.parameter_code), short=False),
                    "image_type": img.image_type,
                    "file_path": img.file_path,
                    "is_included_in_report": img.is_included_in_report,
                }
                for img in images
            ],
            "summary": new_summary,
            "interpretations": interpretations,
            "exam_orders": exam_orders_info,
        }