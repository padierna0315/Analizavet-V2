from fastapi.testclient import TestClient
from app.shared.models.test_result import TestResult
from app.shared.models.lab_value import LabValue
from app.main import app
from app.domains.patients.models import Patient
from app.database import get_session, create_db_and_tables # create_db_and_tables is not used in test, but good for context
from fastapi.templating import Jinja2Templates # Added for Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape # Added for Jinja2 Environment, FileSystemLoader, select_autoescape
from fastapi.responses import HTMLResponse # Added for HTMLResponse in NoCacheJinja2Templates
from unittest.mock import patch # Added for patching Jinja2Templates

import pytest
import asyncio
import re # Added for regex in test_patient_card_display_states
import json # Added for json.dumps in create_patient
from typing import AsyncGenerator, Optional, List
from app.domains.reception.router import router as reception_router # Import the reception router module
from sqlmodel import Session, select, SQLModel # Added SQLModel import
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker # Added sessionmaker
from sqlalchemy import text # Added text for raw SQL execution # Added SQLAlchemy async imports
from datetime import datetime, timezone, timedelta

# Override the database URL for testing to use an in-memory SQLite database
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db" # Using a file-based SQLite for easier debugging if needed, though in-memory is also an option "sqlite+aiosqlite:///:memory:"


@pytest.fixture(name="test_engine", scope="session")
async def test_engine_fixture():
    # Use the test database URL for the engine
    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield test_engine
    # Drop tables after tests are done
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await test_engine.dispose()

@pytest.fixture(name="session", scope="function")
async def session_fixture(test_engine) -> AsyncGenerator[AsyncSession, None]: # Changed return type hint
    TestAsyncSessionLocal = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with TestAsyncSessionLocal() as session:
        yield session

@pytest.fixture(name="client")
async def client_fixture(session: Session):
    def get_session_override():
        return session
    
    app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# Helper function to create mock patients
async def create_patient(
    session: Session,
    name: str,
    initial_waiting_room_status: str,
    sources_received: list[str],
    is_active: bool = True,
    session_code: str | None = None,
) -> Patient:
    actual_waiting_room_status = initial_waiting_room_status if is_active else "inactive"
    patient = Patient(
        name=name,
        species="Canino",
        sex="Macho",
        owner_name="Test Owner",
        has_age=True,
        age_value=5,
        age_unit="años",
        age_display="5 años",
        source="ozelle", # Default source
        session_code=session_code,
        waiting_room_status=actual_waiting_room_status,
        sources_received=sources_received,
        normalized_name=name.lower() if name else "sin_nombre", # Required by model
        normalized_owner="test owner", # Required by model
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(patient)
    await session.commit()
    await session.refresh(patient)
    return patient

async def create_test_result(
    session: Session,
    patient_id: int,
    status: str,
    test_type: str = "Hemograma",
    source: str = "LIS_OZELLE",
    received_at: datetime | None = None,
    internal_code: str | None = None,
    lab_values_data: Optional[List[dict]] = None,
) -> TestResult:
    if received_at is None:
        received_at = datetime.now(timezone.utc)
    if internal_code is None:
        internal_code = f"CODE-{patient_id}-{status}-{received_at.timestamp()}"

    test_result = TestResult(
        patient_id=patient_id,
        test_type=test_type,
        test_type_code="HEM",
        source=source,
        status=status,
        internal_code=internal_code,
        received_at=received_at,
    )
    session.add(test_result)
    await session.commit()
    await session.refresh(test_result)

    if lab_values_data:
        for lv_data in lab_values_data:
            lab_value = LabValue(test_result_id=test_result.id, **lv_data)
            session.add(lab_value)
        await session.commit()
        await session.refresh(test_result) # Refresh again to load lab values

    return test_result

@pytest.mark.asyncio
async def test_reception_waiting_room_display(client: TestClient, session: Session):
    # Setup: Clear database before starting tests
    await session.execute(text("DELETE FROM patient;"))
    await session.commit()

    # Create mock patient objects
    patient_active_ozelle = await create_patient(
        session,
        "Buddy Ozelle",
        "active",
        ["LIS_OZELLE"]
    )
    patient_active_ozelle_json = await create_patient(
        session,
        "Max Ozelle Json",
        "active",
        ["LIS_OZELLE", "LIS_FILE"]
    )
    patient_done = await create_patient(
        session,
        "Charlie Done",
        "done",
        ["LIS_OZELLE"]
    )
    patient_inactive = await create_patient(
        session,
        "Daisy Inactive",
        "active",
        ["LIS_OZELLE"],
        is_active=False
    )

    # Action: Make GET request to the reception endpoint
    response = client.get("/reception/taller/reception") # Corrected path to /reception as per router mounting

    # Assertions
    assert response.status_code == 200
    content = response.text

    # Assert that the response content contains the names of the two "active" patients
    assert patient_active_ozelle.name in content
    assert patient_active_ozelle_json.name in content

    # Assert that the response content does NOT contain the name of the "done" patient
    assert patient_done.name not in content
    assert patient_inactive.name not in content # Should not appear because is_active is False

    # The cleanup after test runs is handled by the `test_engine_fixture` dropping all tables.
    # No need for explicit delete_many here.

@pytest.mark.asyncio
async def test_patient_card_display_states(client: TestClient, session: Session):
    # Setup: Clear database before starting tests
    await session.execute(text("DELETE FROM patient;"))
    await session.commit()

    # Create mock patient objects
    # Patient A (Code Only): name='', code='A1', sources_received=[]
    patient_a = await create_patient(
        session,
        "", # empty name = code-only state
        "active", # waiting_room_status
        [], # sources_received
        session_code="A1",
    )

    # Patient B (Baptized): name='Tommy', species='Canino', code='B1', sources_received=['json']
    patient_b = await create_patient(
        session,
        "Tommy", # name
        "active", # waiting_room_status
        ["json"], # sources_received
        session_code="B1",
    )

    # Patient C (Partial Labs): name='', code='C1', sources_received=['LIS_OZELLE', 'LIS_FUJIFILM']
    patient_c = await create_patient(
        session,
        "", # empty name
        "active", # waiting_room_status
        ["LIS_OZELLE", "LIS_FUJIFILM"], # sources_received
        session_code="C1",
    )

    # Action: Make GET request to the reception endpoint
    response = client.get("/reception/taller/reception")

    # Assertions
    assert response.status_code == 200
    content = response.text

    # Assert Patient A: A1 but not A1 -
    assert f"{patient_a.session_code}" in content
    assert f"{patient_a.session_code} -" not in content

    # Assert Patient B: B1 - Tommy in <strong>, Canino in separate <p>
    assert f"{patient_b.session_code} - {patient_b.name}" in content
    assert patient_b.species in content

    # Assert Patient C: green CSS class twice for Ozelle and Fujifilm dots
    # This requires looking for the specific HTML structure. Assuming it looks something like:
    # <div class="source-dot ozelle green"></div>
    # <div class="source-dot fujifilm green"></div>
    # Or similar structure within the patient card HTML.
    # I'll need to locate the patient card for C1 first, then search within it.

    # Find the HTML section for Patient C's card
    # This is a placeholder regex, might need adjustment based on actual HTML rendering
    # Assuming patient card has a div with id like 'patient-card-<session_code>' or contains the session_code clearly
    # Updated regex to be more specific to a patient card div. Assuming a structure like:
    # <div class="patient-card" ...>
    #   ...
    #   <div class="source-indicator">
    #     <span class="source-dot ozelle green"></span>
    #     <span class="source-dot fujifilm green"></span>
    #   </div>
    #   ...
    # </div>
    # For now, I'll search for the session_code within a general patient card structure, then look for 'green' inside.
    # The regex needs to capture the entire patient card to count greens correctly within its scope.
    # A more robust approach might look for a div with a specific class for the patient card,
    # then check its content for the sources.

    # This regex attempts to find a block that contains the session_code C1
    # and then count the occurrences of 'green' within that block.
    # This assumes the HTML structure around the session_code for the patient card is consistent.
    # It attempts to capture a larger HTML block that would contain the source dots.
    # The `.*?` makes it non-greedy.
    patient_c_card_pattern = re.compile(rf'<div.*?id="patient-card-{patient_c.session_code}".*?>(.*?)</div>', re.DOTALL)
    match = patient_c_card_pattern.search(content)

    if not match:
        # Fallback if id is not present, trying to capture any div containing the code
        patient_c_card_pattern = re.compile(rf'<div.*?>(.*?)?{patient_c.session_code}(.*?)</div', re.DOTALL)
        match = patient_c_card_pattern.search(content)

    assert match, f"Could not find patient card for {patient_c.session_code} in content.\nContent:\n{content}"
    patient_c_card_html = match.group(0) if match.groups() == 0 else "".join(match.groups())

    # Count 'green' class occurrences for sources_received within Patient C's card
    # This will count the string 'green' directly.
    green_class_count = patient_c_card_html.count('green')
    assert green_class_count == 2, f"Expected 2 'green' classes for patient C, found {green_class_count}. Card HTML:\n{patient_c_card_html}"


@pytest.mark.asyncio
async def test_inject_patient_with_listo_status_succeeds(client: TestClient, session: Session):
    # Setup
    await session.execute(text("DELETE FROM patient;"))
    await session.execute(text("DELETE FROM testresult;"))
    await session.commit()

    patient = await create_patient(session, "Ready Patient", "active", ["MANUAL"])
    test_result = await create_test_result(session, patient.id, "listo")

    # Action: Attempt to inject patient to Taller
    response = client.post(f"/reception/patient/{patient.id}/inject-to-taller")

    # Assertions
    assert response.status_code == 200
    assert patient.name in response.text
    assert test_result.test_type in response.text


@pytest.mark.asyncio
async def test_inject_patient_no_test_results_returns_404(client: TestClient, session: Session):
    # Setup
    await session.execute(text("DELETE FROM patient;"))
    await session.execute(text("DELETE FROM testresult;"))
    await session.commit()

    patient = await create_patient(session, "No Results Patient", "active", ["MANUAL"])
    # No TestResult created for this patient

    # Action: Attempt to inject patient to Taller
    response = client.post(f"/reception/patient/{patient.id}/inject-to-taller")

    # Assertions - the simplified service now returns 200 with an empty body
    # if no TestResult is found, and the router handles the 404.
    # Let's adjust this test to expect a specific message if no TestResult is found
    # (which is what the service returns, then the router logic determines HTTP status).
    # Assuming the router now correctly returns 404 if the service returns None.
    assert response.status_code == 404
    assert '{"detail":"No pending/received test results found for this patient."}' in response.text


@pytest.mark.asyncio
async def test_inject_patient_uses_latest_test_result(client: TestClient, session: Session):
    # Setup
    await session.execute(text("DELETE FROM patient;"))
    await session.execute(text("DELETE FROM testresult;"))
    await session.commit()

    patient = await create_patient(session, "Multiple Results Patient", "active", ["MANUAL"])

    # Create older TestResult
    old_test_result_time = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(hours=1)
    old_test_result = await create_test_result(session, patient.id, "pendiente", received_at=old_test_result_time, internal_code="OLD_TR")

    # Create newer TestResult
    new_test_result_time = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    new_test_result = await create_test_result(session, patient.id, "listo", received_at=new_test_result_time, internal_code="NEW_TR")

    # Action: Attempt to inject patient to Taller
    response = client.post(f"/reception/patient/{patient.id}/inject-to-taller")

    # Assertions
    assert response.status_code == 200
    # The response text should contain information about the NEW_TR, not the OLD_TR
    assert patient.name in response.text
    assert new_test_result.test_type in response.text
    assert f"patient-form-{new_test_result.id}" in response.text
    assert f"patient-form-{old_test_result.id}" not in response.text

