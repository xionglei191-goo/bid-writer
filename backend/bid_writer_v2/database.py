from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable


class ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Database:
    def __init__(self, path: Path, migrations_root: Path | None = None) -> None:
        self.path = path
        self.migrations_root = migrations_root or Path(__file__).with_name("migrations")

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30, factory=ManagedConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def migrate(self) -> list[str]:
        applied: list[str] = []
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            existing = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            for migration in sorted(self.migrations_root.glob("*.sql")):
                if migration.name in existing:
                    continue
                conn.executescript(migration.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (migration.name,))
                applied.append(migration.name)
        return applied

    def rows(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]

    def row(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self.connect() as conn:
            value = conn.execute(sql, tuple(params)).fetchone()
            return dict(value) if value else None
