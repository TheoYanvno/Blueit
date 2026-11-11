"""Entry point for the packaged Windows app. PyInstaller builds Blueit.exe from this file; double-click
it to open the page, or run `Blueit.exe doctor`, `Blueit.exe run --fetch` and the other commands in a
terminal, the same as `python -m blueit`."""
import sys

from blueit.cli import main

if __name__ == "__main__":
    sys.exit(main())
