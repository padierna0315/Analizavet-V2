"""
Fujifilm DRI-CHEM NX600 TCP Adapter.

AsyncIO TCP server that listens for connections from the Fujifilm NX600,
receives raw data, parses it using the Fujifilm parser, and enqueues
each reading to Dramatiq for background processing.
"""

import asyncio
from datetime import datetime, timezone
import logfire

from app.satellites.base import SourceAdapter
from app.domains.reception.schemas import PatientSource
from app.satellites.fujifilm.parser import parse_fujifilm_message


class FujifilmAdapter(SourceAdapter):
    """Adapter for the Fujifilm DRI-CHEM NX600 machine.

    Listens on a dedicated ethernet interface (default: 192.168.100.2:6001)
    for incoming data from the Fujifilm analyzer. Raw messages are parsed
    and each chemistry reading is enqueued to Dramatiq for processing.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 6001):
        self.host = host
        self.port = port
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        logfire.info(
            "Fujifilm Adapter escuchando en {host}:{port}",
            host=self.host,
            port=self.port,
        )

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logfire.info("Fujifilm Adapter detenido")

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """Handle an incoming TCP connection from the Fujifilm machine.

        Soporta DOS modos de operación:

        Modo vivo (automático):
          La máquina envía múltiples líneas delimitadas por \\n,
          cada una con un mensaje S... (procesando) o R... (resultado).
          Se procesan línea por línea a medida que llegan.

        Modo manual (prueba):
          El usuario envía datos desde la máquina de forma manual.
          El mensaje llega en una sola trama STX...ETX sin \\n.
          Al cerrarse la conexión, se procesa lo acumulado en el buffer.
        """
        addr = writer.get_extra_info("peername")
        logfire.info("Nueva conexión Fujifilm desde {addr}", addr=addr)

        buffer = bytearray()
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break  # Connection closed

                buffer.extend(chunk)

                # Modo vivo: procesar líneas completas delimitadas por newline
                while b"\n" in buffer:
                    line_bytes, buffer = buffer.split(b"\n", 1)
                    line = line_bytes.decode("utf-8", errors="replace").strip("\r")

                    if not line:
                        continue

                    await self._process_message(line)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logfire.error(
                "Error en conexión Fujifilm con {addr}: {e}",
                addr=addr,
                e=e,
            )
        finally:
            # Modo manual: procesar datos residuales sin newline (STX...ETX)
            if buffer:
                raw = buffer.decode("utf-8", errors="replace").strip()
                if raw:
                    logfire.debug(
                        "Procesando datos residuales (modo manual): {raw}",
                        raw=raw,
                    )
                    await self._process_message(raw)

            logfire.debug("Cerrando conexión Fujifilm con {addr}", addr=addr)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _process_message(self, raw: str):
        """Parse a Fujifilm message and enqueue readings to Dramatiq."""
        logfire.debug("Fujifilm mensaje crudo recibido: {raw}", raw=raw)

        readings = parse_fujifilm_message(raw)

        if not readings:
            logfire.debug(
                "Mensaje Fujifilm no produjo lecturas válidas (heartbeat o formato no reconocido): {raw}",
                raw=raw,
            )
            return

        now_iso = datetime.now(timezone.utc).isoformat()

        for reading in readings:
            logfire.info(
                "Fujifilm lectura parseada: {param}={value} para paciente {name} (id={id})",
                param=reading.parameter_code,
                value=reading.raw_value,
                name=reading.patient_name,
                id=reading.internal_id,
            )

            # Enqueue to Dramatiq for background processing
            from app.tasks.fujifilm_processor import process_fujifilm_message

            process_fujifilm_message.send(
                {
                    "internal_id": reading.internal_id,
                    "patient_name": reading.patient_name,
                    "parameter_code": reading.parameter_code,
                    "raw_value": reading.raw_value,
                    "source": PatientSource.LIS_FUJIFILM.value,
                    "received_at": now_iso,
                }
            )

            logfire.debug(
                "Lectura Fujifilm encolada en Dramatiq: {param}={value}",
                param=reading.parameter_code,
                value=reading.raw_value,
            )

    def get_source_name(self) -> str:
        return PatientSource.LIS_FUJIFILM.value

    def is_running(self) -> bool:
        return self._server is not None and self._server.is_serving()
