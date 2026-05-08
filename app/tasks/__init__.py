# NOTE: Do NOT import app.tasks.broker here.
# broker.py calls dramatiq.set_broker(RedisBroker) at import time,
# which would overwrite the StubBroker set by conftest.py during tests.
# Actors are auto-registered when their modules are imported directly.
from app.tasks.hl7_processor import process_hl7_message

__all__ = ["process_hl7_message"]
