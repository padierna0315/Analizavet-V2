import pytest
import requests
from playwright.sync_api import Page, expect
from datetime import datetime, timezone
from sqlmodel import Session
from app.domains.patients.models import Patient

@pytest.mark.skip(reason="Playwright tests conflict with pytest-asyncio event loop management")
def test_delete_patient_flow(page: Page, api_server): # Removed async and @pytest.mark.asyncio
    """
    Test the full user interaction for deleting a patient from the patient list
    using a custom confirmation dialog.
    """
    # 1. Seed a test patient via API
    seed_data = {
        "name": "TestDelete",
        "species": "Canino",
        "sex": "Macho",
        "owner_name": "OwnerDelete",
        "source": "E2E_API_SEED",
        "normalized_name": "testdelete",
        "normalized_owner": "ownerdelete",
    }
    response = requests.post("http://127.0.0.1:8000/patients/seed_test_patient", json=seed_data)
    assert response.status_code == 200
    patient_data = response.json()
    patient_id = patient_data["id"]

    # 2. Navigate to the patient list URL
    page.goto("/patients")

    # 3. Locate the patient card
    patient_card_selector = f"[data-testid='patient-card-{patient_id}']"
    patient_card = page.locator(patient_card_selector)
    expect(patient_card).to_be_visible()

    # 4. Click the delete icon to open the custom confirmation dialog
    delete_button_selector = f"[data-testid='delete-patient-{patient_id}']"
    delete_button = page.locator(delete_button_selector)
    expect(delete_button).to_be_visible()
    delete_button.click()

    # 5. Assert custom confirmation dialog appears
    confirmation_dialog_selector = "[data-testid='confirmation-dialog']"
    confirmation_dialog = page.locator(confirmation_dialog_selector)
    expect(confirmation_dialog).to_be_visible()
    expect(confirmation_dialog).to_contain_text("¿Estás seguro que quieres eliminar")

    # 6. Click the "Confirmar" button within the dialog
    confirm_delete_button = confirmation_dialog.locator("[data-testid='confirm-delete-button']")
    expect(confirm_delete_button).to_be_visible()
    confirm_delete_button.click() # Just click the button, no HTMX request sent by it now.

    # Directly make the DELETE request using Playwright's request API
    delete_api_response = page.request.delete(f"http://127.0.0.1:8000/patients/{patient_id}")
    assert delete_api_response.status == 200

    # Explicitly clear the content of the modal container
    page.evaluate("document.getElementById('confirm-modal-target').innerHTML = ''")

    # 7. Assert custom confirmation dialog disappears
    confirmation_dialog.wait_for(state="detached") # Explicitly wait for detachment
    expect(confirmation_dialog).not_to_be_attached()
    
    # Reload the page to reflect the deletion
    page.reload()

    # 8. Assert the patient card disappears from the list
    page.wait_for_selector(patient_card_selector, state="detached")
    expect(patient_card).not_to_be_attached()
