from __future__ import annotations

import os
import tempfile
from pathlib import Path

from bid_writer_v2.database import Database


def main() -> None:
    url = os.environ["BID_WRITER_DATABASE_URL"]
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "unused.sqlite3", database_url=url)
        database.migrate()
        with database.connect() as connection:
            cursor = connection.execute("INSERT INTO projects(name,profile_json) VALUES (?,?)", ("PostgreSQL CI", "{}"))
            project_id = int(cursor.lastrowid)
            row = connection.execute("SELECT id,name FROM projects WHERE id=?", (project_id,)).fetchone()
            assert row and row["name"] == "PostgreSQL CI"
            connection.execute("DELETE FROM projects WHERE id=?", (project_id,))
        assert database.backend == "postgresql"
    print("PostgreSQL migration and compatibility smoke test passed")


if __name__ == "__main__":
    main()
