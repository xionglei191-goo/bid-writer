from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from bid_writer.server_stdlib import main


if __name__ == "__main__":
    raise SystemExit(main())
