#!/usr/bin/env python3
"""
Entry point for the installed `dam` command.
Runs the orchestrator (dam.py) from the project root so script paths resolve.
When built with PyInstaller (frozen), scripts are in sys._MEIPASS.
"""

import runpy
import sys
from pathlib import Path


def main():
    if getattr(sys, "frozen", False):
        root = Path(sys._MEIPASS)
    else:
        root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))

    # If no arguments are provided, default to starting the desktop app window
    if len(sys.argv) == 1:
        sys.argv.extend(["serve", "--window"])

    runpy.run_path(str(root / "dam.py"), run_name="__main__")


if __name__ == "__main__":
    main()
