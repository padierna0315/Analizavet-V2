"""
Ozelle MLLP Server — Phase 14/15

AsyncIO TCP server that listens for MLLP-framed HL7 messages from the Ozelle EHVT-50,
parses them for validation, enqueues them to Dramatiq for background processing,
and sends MLLP-framed HL7 ACKs back.
"""

import asyncio
from datetime import datetime
import logfire

from app.satellites.ozelle.hl7_parser import parse_hl7_message, HL7ParsingError, HeartbeatMessageException
from app.domains.reception.schemas import PatientSource


# MLLP Framing characters
SB = b"\x0b"  # <VT> - Start Block
EB = b"\x1c"  # <FS> - End Block
CR = b"\x0d"  # <CR> - Carriage Return


class OzelleMLLPServer:
    """AsyncIO TCP server for the Ozelle EHVT-50.

    Listens for MLLP-framed HL7 messages, parses them,
    and sends MLLP-framed HL7 ACKs back.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 6000):
        self.host = host
        self.port = port
        self._server: asyncio.Server | None = None

    async def start(self):
        """Start the TCP server."""
        self._server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        logfire.info(f"Ozelle MLLP Server escuchando en {self.host}:{self.port}")

    async def stop(self):
        """Stop the TCP server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logfire.info("Ozelle MLLP Server detenido")

    def is_running(self) -> bool:
        """Return True if the server is currently running."""
        return self._server is not None and self._server.is_serving()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle an incoming TCP connection."""
        addr = writer.get_extra_info("peername")
        logfire.debug(f"Nueva conexión Ozelle desde {addr}")

        buffer = bytearray()
        try:
            while True:
                # Read chunk
                chunk = await reader.read(4096)
                if not chunk:
                    break  # Connection closed by client

                buffer.extend(chunk)

                # Check if we have a complete message (SB ... EB CR)
                while SB in buffer and EB + CR in buffer:
                    start_idx = buffer.find(SB)
                    end_idx = buffer.find(EB + CR, start_idx)

                    if start_idx != -1 and end_idx != -1:
                        # Extract the HL7 payload
                        hl7_bytes = buffer[start_idx + 1 : end_idx]
                        # Remove the processed message from buffer
                        buffer = buffer[end_idx + 2 :]

                        try:
                            hl7_str = hl7_bytes.decode("utf-8", errors="replace")
                            await self._process_message(hl7_str, writer)
                        except Exception as e:
                            logfire.error(f"Error procesando mensaje: {e}")
                            # Try to send AE (Application Error) with whatever we have
                            await self._send_ack(writer, hl7_str, ack_code="AE", error_msg=str(e))
                    else:
                        break  # Wait for more data

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logfire.error(f"Error en conexión MLLP con {addr}: {e}")
        finally:
            logfire.debug(f"Cerrando conexión con {addr}")
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _process_message(self, hl7_str: str, writer: asyncio.StreamWriter):
        """Parse the HL7 string (for validation) and send ACK."""
        try:
            # We parse it here JUST to validate it's not garbage and detect heartbeats.
            # If it fails, it raises before we enqueue.
            parsed = parse_hl7_message(hl7_str)

            # Enqueue to Dramatiq!
            # send() is synchronous but fast, it just puts it in Redis.
            # Lazy import to break circular dependency
            from app.tasks.hl7_processor import process_hl7_message
            process_hl7_message.send(hl7_str, PatientSource.LIS_OZELLE.value)

            logfire.info("Mensaje HL7 encolado en Dramatiq exitosamente.")

            # Send ACK
            await self._send_ack(writer, hl7_str, ack_code="AA")

        except HeartbeatMessageException:
            logfire.debug("Heartbeat de Ozelle recibido y respondido")
            await self._send_ack(writer, hl7_str, ack_code="AA")

        except HL7ParsingError as e:
            logfire.error(f"Error de parseo HL7: {e}")
            await self._send_ack(writer, hl7_str, ack_code="AE", error_msg=str(e))

    async def _send_ack(
        self, writer: asyncio.StreamWriter, original_hl7: str, ack_code: str = "AA", error_msg: str = ""
    ):
        """Generate and send an MLLP-framed HL7 ACK."""
        # Very basic MSH parsing to get sender/receiver and msg control ID
        lines = original_hl7.strip().split("\n")
        if not lines:
            lines = original_hl7.strip().split("\r")

        msh_fields = []
        for line in lines:
            if line.startswith("MSH|"):
                msh_fields = line.split("|")
                break

        # Default fallback values
        sending_app = msh_fields[2] if len(msh_fields) > 2 else "OZELLE"
        sending_fac = msh_fields[3] if len(msh_fields) > 3 else ""
        msg_control_id = msh_fields[9] if len(msh_fields) > 9 else "UNKNOWN_ID"

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        ack_id = f"ACK{timestamp}"

        # Build ACK message
        # Flip sender (us) and receiver (them)
        ack_msh = f"MSH|^~\\&|ANALIZAVET|HUELLAS_LAB|{sending_app}|{sending_fac}|{timestamp}||ACK^R01|{ack_id}|P|2.3.1\r"
        ack_msa = f"MSA|{ack_code}|{msg_control_id}|{error_msg}\r"

        ack_hl7 = ack_msh + ack_msa

        # Frame with MLLP
        framed_ack = SB + ack_hl7.encode("utf-8") + EB + CR

        writer.write(framed_ack)
        await writer.drain()
