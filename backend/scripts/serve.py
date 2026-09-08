from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import uvicorn


if __name__ == "__main__":
    uvicorn.run("bid_writer_v2.app:app", host="127.0.0.1", port=8876, reload=False)
