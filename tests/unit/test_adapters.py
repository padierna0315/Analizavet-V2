import pytest
import pytest_asyncio
import asyncio
from app.satellites.base import SourceAdapter
from app.satellites.ozelle import OzelleAdapter
from app.satellites.fujifilm import FujifilmAdapter


def test_ozelle_adapter_implements_interface():
    adapter = OzelleAdapter()
    assert isinstance(adapter, SourceAdapter)
    assert adapter.get_source_name() == "LIS_OZELLE"


def test_fujifilm_adapter_implements_interface():
    adapter = FujifilmAdapter()
    assert isinstance(adapter, SourceAdapter)
    assert adapter.get_source_name() == "LIS_FUJIFILM"


@pytest.mark.asyncio
async def test_fujifilm_stub_receives_data():
    """Test that the Fujifilm stub can start, receive a connection, and stop cleanly."""
    adapter = FujifilmAdapter(host="127.0.0.1", port=0)
    await adapter.start()

    # Get actual port
    actual_port = adapter._server.sockets[0].getsockname()[1]

    # Connect and send data
    reader, writer = await asyncio.open_connection("127.0.0.1", actual_port)
    writer.write(b"HELLO FUJIFILM")
    await writer.drain()

    # Wait a tiny bit for the server to process it
    await asyncio.sleep(0.1)

    writer.close()
    await writer.wait_closed()

    await adapter.stop()
