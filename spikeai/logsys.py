import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

log = logging.getLogger("spikeai")


def setup(home, debug=False):
    Path(home).mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    handler = RotatingFileHandler(
        Path(home) / "SpikeAI.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    if debug:
        log.addHandler(logging.StreamHandler())
