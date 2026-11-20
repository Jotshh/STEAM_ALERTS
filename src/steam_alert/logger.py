"""Configuração de logging."""
from __future__ import annotations

import logging
import os
import sys


def setup_logging() -> None:
    root = logging.getLogger("steam_alert")
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
