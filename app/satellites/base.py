from abc import ABC, abstractmethod


class SourceAdapter(ABC):
    """Abstract base class for all machine satellites.

    A satellite adapter is responsible for:
    1. Managing its own network connection (TCP server, serial, etc.)
    2. Receiving raw data from the machine
    3. Parsing/validating the data format (e.g., HL7)
    4. Enqueuing the parsed message to Dramatiq for Core processing
    """

    @abstractmethod
    async def start(self) -> None:
        """Start the adapter (e.g., start listening on a port)."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the adapter cleanly."""
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        """Return the PatientSource enum value string (e.g., 'LIS_OZELLE')."""
        pass

    def is_running(self) -> bool:
        """Return True if the adapter is currently running."""
        return False
