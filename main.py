"""Batch AI Image Generator — entry point.

Run this to open the GUI. The command-line interface in `cli.py` is a fully
supported alternative front end onto the same engine.
"""

from __future__ import annotations

import logging
import sys


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from gui.app import BatchGenApp

    BatchGenApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
