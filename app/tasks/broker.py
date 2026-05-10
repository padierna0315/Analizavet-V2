"""
Broker Configuration — Phase 15

Dramatiq + Redis broker setup. Loaded once at application startup.
"""

import dramatiq
from app.config import settings

if settings.MLLP_ENABLED:
    from dramatiq.brokers.redis import RedisBroker
    broker = RedisBroker(url=settings.REDIS_URL)
else:
    from dramatiq.brokers.stub import StubBroker
    broker = StubBroker()

dramatiq.set_broker(broker)

# Import actors after broker is set to ensure they are registered
# This prevents "actor not registered" errors when consuming messages
import app.tasks.hl7_processor  # noqa: F401
import app.tasks.fujifilm_processor  # noqa: F401

# Prometheus middleware is enabled by default in Dramatiq 1.15.0, it binds to ports 9191/9200
# To disable in production: set DRAMATIQ_PROMETHEUS_PORT env var to a different value or -1
