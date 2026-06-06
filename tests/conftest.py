from __future__ import annotations

import sys
from pathlib import Path

# Make `src/` importable for tests without requiring an editable install.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
