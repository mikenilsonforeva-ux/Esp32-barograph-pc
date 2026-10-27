#!/usr/bin/env python3
"""ESP32 Barograph PC. Без аргументов - графический интерфейс; `python barograph_app.py --help` - команды."""
import sys

from barograph.cli import main

if __name__ == "__main__":
    sys.exit(main())
