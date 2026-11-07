"""GUI entry point for Dsm2Empirum.exe."""

import sys


def main() -> None:
    if len(sys.argv) > 1:
        from dsm2emp.cli import app

        app()
    else:
        from dsm2emp.gui.app import run_gui

        sys.exit(run_gui())


if __name__ == "__main__":
    main()
