"""Logging configuration for DevOps AI application.

This module configures the root logger with a standard format and level so
all components share the same logging setup. Importing this module once is
sufficient to configure logging for the entire application.
"""

from __future__ import annotations

import logging
import sys


def configure() -> None:
    """Configure the root logger with a stream handler if not already done."""
    root = logging.getLogger()
    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(logging.INFO)


configure()
