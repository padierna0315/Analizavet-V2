# NOTE: Do NOT import app.tasks.broker or any actor modules here.
# broker.py calls dramatiq.set_broker(RedisBroker) at import time,
# which must happen BEFORE any @dramatiq.actor decorator runs.
# Actors are auto-registered when broker.py imports them explicitly.
