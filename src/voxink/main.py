"""Entry point for PyInstaller builds.

When packaged as a standalone executable, this is the script that runs.
It launches the tray application directly (no CLI parsing needed for
end users — they just double-click the app).
"""

from __future__ import annotations

import sys


def main() -> None:
    """Launch the tray app directly for standalone builds."""
    # If run with CLI arguments, use the full CLI
    if len(sys.argv) > 1:
        from voxink.cli import main as cli_main
        cli_main()
    else:
        # Default: launch tray directly
        from voxink.tray import run_tray
        run_tray()


if __name__ == "__main__":
    main()
