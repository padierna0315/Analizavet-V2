import os
import tempfile
import shutil
import pytest
import pytest_asyncio
import subprocess
import time
from datetime import datetime, timezone
import requests

from playwright.sync_api import Browser, Page, expect
from app.main import app
from app.database import get_session
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.domains.patients.models import Patient


# Define the base URL for the FastAPI application
BASE_URL = "http://127.0.0.1:8000"

# ── Fixtures for FastAPI application lifecycle ──────────────────────────────────

@pytest.fixture(scope="session") # No longer async
def db_url():
    """Provides a temporary SQLite database URL for the test session."""
    db_dir = tempfile.mkdtemp()
    db_path = os.path.join(db_dir, "test.db")
    url = f"sqlite:///{db_path}" # Use synchronous SQLite for setup
    yield url
    shutil.rmtree(db_dir)

@pytest.fixture(scope="session") # No longer async
def apply_migrations(db_url: str):
    """Applies migrations (creates tables) to the temporary SQLite database."""
    # Use synchronous engine for setup phase
    engine = create_engine(db_url) # Use synchronous engine
    SQLModel.metadata.create_all(engine)
    
    # Patient seeding removed from here
    
    engine.dispose()
    yield

@pytest.fixture(scope="session")
def api_server(db_url: str, apply_migrations):
    """Launches the FastAPI application in a subprocess with a health check."""
    # Set environment variables for the subprocess
    env = os.environ.copy()
    env["ANALIZAVET_ENV"] = "test"
    # IMPORTANT: The FastAPI app will use aiosqlite, so ensure the URL matches
    env["ANALIZAVET_DATABASE_URL"] = db_url.replace("sqlite:///", "sqlite+aiosqlite:///")
    env["ANALIZAVET_IMAGES_DIR"] = tempfile.mkdtemp()

    # Start the Uvicorn server in a subprocess
    process = subprocess.Popen(
        ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "critical"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    try:
        # Implement a health check to wait for the server to be ready
        retries = 20
        for i in range(retries):
            try:
                response = requests.get(f"{BASE_URL}/health", timeout=1)
                if response.status_code == 200:
                    print(f"Server ready after {i+1} retries.")
                    break
            except requests.exceptions.ConnectionError:
                pass
            time.sleep(1)
        else:
            stdout, stderr = process.communicate(timeout=1)
            print("\n--- Uvicorn STDOUT ---")
            print(stdout.decode())
            print("\n--- Uvicorn STDERR ---")
            print(stderr.decode())
            raise RuntimeError("FastAPI application failed to start within timeout.")

        yield process
    finally:
        process.terminate()
        process.wait()

# ── Fixtures for Playwright ─────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def browser_context_args(api_server):
    """Provide browser context args with base_url pointing to the test server."""
    return {"base_url": BASE_URL}

def pytest_collection_modifyitems(config, items):
    """
    Called after test collection has been performed.
    Used to modify the collected test items to prevent pytest-asyncio
    from interfering with pytest-playwright.
    """
    for item in items:
        # Check if the test is an E2E test (e.g., by checking its path)
        if "e2e" in str(item.fspath):
            # Remove any asyncio marker that might have been added automatically by pytest-asyncio
            if hasattr(item, 'own_markers'):
                item.own_markers = [
                    marker for marker in item.own_markers
                    if marker.name != 'asyncio'
                ]
            # If a specific asyncio engine or mode is required for playwright, it would be set here.
            # For now, the goal is to prevent pytest-asyncio from trying to manage the event loop.


