from app.config import settings

def test_appsheet_settings_exist():
    # Law 1: reference production code that doesn't exist yet (settings fields)
    assert hasattr(settings, "APPSHEET_API_KEY")
    assert hasattr(settings, "APPSHEET_APP_ID")
    assert hasattr(settings, "APPSHEET_TABLE_NAME")
