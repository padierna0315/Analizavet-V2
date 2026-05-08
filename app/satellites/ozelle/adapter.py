from app.satellites.base import SourceAdapter
from app.satellites.ozelle.mllp_server import OzelleMLLPServer
from app.domains.reception.schemas import PatientSource


class OzelleAdapter(SourceAdapter):
    """Adapter for the Ozelle EHVT-50 machine."""

    def __init__(self, port: int = 6000):
        self.port = port
        self._server = OzelleMLLPServer(port=port)

    async def start(self) -> None:
        await self._server.start()

    async def stop(self) -> None:
        await self._server.stop()

    def get_source_name(self) -> str:
        return PatientSource.LIS_OZELLE.value

    def is_running(self) -> bool:
        """Return True if the Ozelle server is currently running."""
        return self._server.is_running()
