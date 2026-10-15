"""Shared browser selection for reports, setup and browser verification."""

import os
from pathlib import Path
import sys


def installed_windows_browser():
    if sys.platform != "win32":
        return None
    for product in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
        for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                executable = Path(root) / product
                if executable.is_file():
                    return executable
    return None


def browser_launch_options(*, channel=None, executable_path=None):
    if executable_path:
        executable = Path(executable_path)
        if not executable.is_file():
            raise RuntimeError(f"Configured browser does not exist: {executable}")
        return {"executable_path": str(executable)}
    if channel:
        return {"channel": channel}
    executable = installed_windows_browser()
    return {"executable_path": str(executable)} if executable else {}
