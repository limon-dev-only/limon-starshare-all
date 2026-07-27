"""
logger.py

Single place to configure logging for the whole project so every module
gets consistent, readable formatting without repeating basicConfig calls
or fighting duplicate handler registration.
"""

from __future__ import annotations

import logging

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger configured with the project's standard format.

    Safe to call from every module at import time — logging.basicConfig
    is applied exactly once no matter how many modules call this.
    """
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        _CONFIGURED = True
    return logging.getLogger(name)
