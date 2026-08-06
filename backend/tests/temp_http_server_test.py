from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    port = free_port()
    env = os.environ.copy()
    env["BID_WRITER_TEST_BASE_URL"] = f"http://127.0.0.1:{port}"
    env["BID_WRITER_DISABLE_USER_ENV"] = "1"
    env["OPENAI_API_KEY"] = ""
    env["BID_WRITER_DB"] = str(ROOT_DIR / "data" / "test_temp_http.sqlite")
    env["BID_WRITER_TEST_BYPASS_FORMAL_GATE"] = "1"
    os.environ["BID_WRITER_TEST_BASE_URL"] = env["BID_WRITER_TEST_BASE_URL"]
    os.environ["BID_WRITER_DISABLE_USER_ENV"] = "1"
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["BID_WRITER_DB"] = env["BID_WRITER_DB"]
    os.environ["BID_WRITER_TEST_BYPASS_FORMAL_GATE"] = "1"
    for suffix in ("", "-wal", "-shm"):
        Path(env["BID_WRITER_DB"] + suffix).unlink(missing_ok=True)
    from bid_writer.kb_importer import import_knowledge_base

    import_knowledge_base(reset=True, limit_documents=20)
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(BACKEND_DIR)!r}); "
        "from bid_writer.server_stdlib import serve; "
        f"serve(port={port})"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=str(ROOT_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(1)
        from http_delivery_review_test import main as run_http_test

        return run_http_test()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
