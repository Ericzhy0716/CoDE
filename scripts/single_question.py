#!/usr/bin/env python3
"""Single-question teaching diagnostic; --help and plan need only Python 3.10+."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from diagnostic_core import main

if __name__ == "__main__":
    raise SystemExit(main())
