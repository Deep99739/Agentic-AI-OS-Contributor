"""
Simple colored logging utility.
Provides timestamped log output to stderr so it doesn't interfere with stdout artifacts.
"""

import sys
from datetime import datetime


class Logger:
    """Minimal logger with level-based output and timestamps."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def info(self, msg: str):
        self._print(msg, "INFO")

    def warning(self, msg: str):
        self._print(msg, "WARN")

    def error(self, msg: str):
        self._print(msg, "ERROR")

    def debug(self, msg: str):
        if self.verbose:
            self._print(msg, "DEBUG")

    def _print(self, msg: str, level: str):
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "INFO": "ℹ️ ",
            "WARN": "⚠️ ",
            "ERROR": "❌",
            "DEBUG": "🔍",
        }.get(level, "")
        print(f"[{ts}] [{level}] {prefix} {msg}", file=sys.stderr)


# Module-level singleton — reconfigured by setup_logger()
log = Logger()


def setup_logger(verbose: bool = False):
    """Reconfigure the global logger instance."""
    global log
    log = Logger(verbose=verbose)
