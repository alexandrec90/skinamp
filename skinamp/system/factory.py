"""Choosing the `System` for this machine."""

import sys
from pathlib import Path

from skinamp.paths import AppPaths
from skinamp.system.api import System


class UnsupportedPlatformError(RuntimeError):
    """Skinamp themes Windows; there is nothing to do anywhere else."""


def get_system(paths: AppPaths) -> System:
    if sys.platform != "win32":
        raise UnsupportedPlatformError(f"Skinamp needs Windows, not {sys.platform}")
    from skinamp.system.win32 import Win32System

    return Win32System(paths)


def run_request(request: Path) -> None:
    """Carry out an elevated request, in the elevated helper process."""
    if sys.platform != "win32":
        raise UnsupportedPlatformError(f"Skinamp needs Windows, not {sys.platform}")
    from skinamp.system.win32 import execute_request

    execute_request(request)
