"""PyInstaller entry point.

When run as a script (or frozen by PyInstaller), this delegates to the
package's main() so all relative imports inside `densitas/` continue to
work. Targets:

    pyinstaller --onefile --windowed --name Densitas entry.py

For ordinary development you should still use:

    python -m densitas.main
"""
from __future__ import annotations
import sys
from densitas.main import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
