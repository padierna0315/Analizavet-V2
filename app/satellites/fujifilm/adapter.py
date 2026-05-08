import asyncio
import logfire
from app.satellites.base import SourceAdapter
from app.domains.reception.schemas import PatientSource


class FujifilmAdapter(SourceAdapter):
    """Stub adapter for the Fujifilm DRI-CHEM NX600 machine.

    Currently only listens on port 6001 and logs received data.
    Full HL7 parsing and Dramatiq enqueuing will be implemented later.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 6001):
        self.host = host
        self.port = port
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        logfire.info(f"Fujifilm Stub Server escuchando en {self.host}:{self.port}")

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logfire.info("Fujifilm Stub Server detenido")

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        logfire.info(f"Nueva conexión Fujifilm desde {addr}")

        try:
            data = await reader.read(4096)
            message = data.decode("utf-8", errors="replace")
            logfire.info(f"Fujifilm stub recibió: {message}")

            # TODO: Implement Fujifilm HL7 parsing and Dramatiq enqueueing
            logfire.warning("Fujifilm adapter es un STUB. Mensaje ignorado.")

        except Exception as e:
            logfire.error(f"Error en conexión Fujifilm con {addr}: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def get_source_name(self) -> str:
        return PatientSource.LIS_FUJIFILM.value

    def is_running(self) -> bool:
        """Return True if the Fujifilm server is currently running."""
        return self._server is not None and self._server.is_serving()
