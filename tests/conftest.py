import os
import tempfile
# Must be set BEFORE any app imports
os.environ.setdefault("ANALIZAVET_ENV", "default")
os.environ.setdefault("ANALIZAVET_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ANALIZAVET_IMAGES_DIR", tempfile.mkdtemp())
os.environ.setdefault("TESTING", "True")

import dramatiq
from dramatiq.brokers.stub import StubBroker

# CRITICAL: Set stub broker BEFORE any app imports that register dramatiq actors.
# This ensures actors are registered with the stub broker, not the default Redis broker.
_test_stub_broker = StubBroker()
dramatiq.set_broker(_test_stub_broker)

import pytest
import pytest_asyncio
import asyncio
from httpx import AsyncClient, ASGITransport
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.database import get_session
from app.satellites.ozelle.mllp_server import OzelleMLLPServer


# ── Dramatiq Stub Broker fixture (exposes the broker for tests) ────────────────

@pytest.fixture(scope="session", autouse=True)
def stub_broker():
    """Expose the pre-configured stub broker for test use."""
    yield _test_stub_broker


@pytest.fixture(autouse=True)
def clear_stub_broker_queues():
    """Flush stub broker queues between tests (preserves queue declarations)."""
    yield
    _test_stub_broker.flush_all()


# ── Shared in-memory engine (session scope) ────────────────────────────────────

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    return _engine


@pytest.fixture(scope="session")
def event_loop():
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_db():
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    await engine.dispose()
    global _engine
    _engine = None


async def _override_get_session():
    maker = sessionmaker(_get_engine(), class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest.fixture
def client():
    app.dependency_overrides[get_session] = _override_get_session
    # follow_redirects=True to automatically follow 3xx redirects
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True)


@pytest.fixture(autouse=True)
def cleanup_client():
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="session")
async def ozelle_mllp_server_fixture():
    server = OzelleMLLPServer(port=0)  # Use port 0 for dynamic port assignment
    await server.start()
    yield server
    await server.stop()


@pytest_asyncio.fixture
async def session():
    """Provide a direct AsyncSession for integration tests that need DB access."""
    maker = sessionmaker(_get_engine(), class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        yield sess
