from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator


class ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class CompatRow(dict[str, Any]):
    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class CompatResult:
    def __init__(self, rows: list[CompatRow], rowcount: int = 0, lastrowid: int | None = None) -> None:
        self._rows = rows
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self) -> CompatRow | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[CompatRow]:
        return list(self._rows)

    def __iter__(self) -> Iterator[CompatRow]:
        return iter(self._rows)


_ID_TABLES = {
    "source_files", "processing_jobs", "standard_documents", "document_sections", "knowledge_clusters",
    "knowledge_units", "knowledge_unit_sources", "knowledge_versions", "knowledge_reviews",
    "knowledge_publications", "knowledge_assets", "projects", "project_requirements", "project_sections",
    "project_drafts", "requirement_responses", "deliveries", "draft_review_decisions",
    "confirmation_resolutions", "ai_prompt_versions", "ai_runs", "retrieval_eval_cases", "retrieval_eval_runs",
    "knowledge_ai_pipeline_runs", "knowledge_ai_candidates", "knowledge_exception_tasks", "source_relations",
    "organizations", "app_users", "roles", "auth_sessions", "login_attempts", "audit_events", "app_jobs",
    "job_events", "object_records", "document_chunks", "candidate_relations", "knowledge_auto_publish_batches",
    "retrieval_indexes", "retrieval_runs_v2", "retrieval_feedback", "generation_runs", "claims", "evidence_links",
    "quality_issues", "delivery_manifests",
    "corpus_runs", "corpus_run_items", "knowledge_review_decisions", "governance_tasks",
    "corpus_section_clusters",
}


def _qmark_sql(sql: str, params: Iterable[Any]) -> tuple[str, dict[str, Any]]:
    values = list(params)
    output: list[str] = []
    bindings: dict[str, Any] = {}
    index = 0
    in_string = False
    position = 0
    while position < len(sql):
        char = sql[position]
        if char == "'":
            output.append(char)
            if in_string and position + 1 < len(sql) and sql[position + 1] == "'":
                output.append("'")
                position += 2
                continue
            in_string = not in_string
        elif char == "?" and not in_string:
            name = f"p{index}"
            output.append(f":{name}")
            bindings[name] = values[index]
            index += 1
        else:
            output.append(char)
        position += 1
    if index != len(values):
        raise ValueError(f"SQL参数数量不匹配: placeholders={index}, values={len(values)}")
    return "".join(output), bindings


def _postgres_sql(sql: str, params: Iterable[Any]) -> tuple[str, dict[str, Any], bool]:
    normalized = sql.strip()
    if "published_units_fts" in normalized:
        raise RuntimeError("PostgreSQL运行时不使用SQLite FTS索引")
    ignore_conflict = bool(re.match(r"INSERT\s+OR\s+IGNORE\s+INTO", normalized, re.IGNORECASE))
    normalized = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bCURRENT_TIMESTAMP\b", "(CURRENT_TIMESTAMP)::text", normalized, flags=re.IGNORECASE)
    translated, bindings = _qmark_sql(normalized, params)
    insert_match = re.match(r"INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", translated, re.IGNORECASE)
    table = insert_match.group(1).lower() if insert_match else ""
    if ignore_conflict:
        translated = f"{translated.rstrip().rstrip(';')} ON CONFLICT DO NOTHING"
    expects_id = table in _ID_TABLES and " RETURNING " not in translated.upper()
    if expects_id:
        translated = f"{translated.rstrip().rstrip(';')} RETURNING id"
    return translated, bindings, expects_id


class PostgresConnection:
    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._connection: Any = None
        self._transaction: Any = None

    def __enter__(self) -> "PostgresConnection":
        self._connection = self._engine.connect()
        self._transaction = self._connection.begin()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            if exc_type is None:
                self._transaction.commit()
            else:
                self._transaction.rollback()
        finally:
            self._connection.close()
        return False

    def execute(self, sql: str, params: Iterable[Any] = ()) -> CompatResult:
        from sqlalchemy import text

        translated, bindings, expects_id = _postgres_sql(sql, params)
        result = self._connection.execute(text(translated), bindings)
        lastrowid: int | None = None
        rows: list[CompatRow] = []
        if expects_id:
            returned = result.fetchone()
            if returned is not None:
                lastrowid = int(returned[0])
        elif result.returns_rows:
            rows = [CompatRow(dict(item._mapping)) for item in result.fetchall()]
        return CompatResult(rows, result.rowcount, lastrowid)


def postgres_migration_statements(migrations_root: Path, through: str = "") -> list[str]:
    statements: list[str] = []
    for migration in sorted(migrations_root.glob("*.sql")):
        if through and migration.name > through:
            continue
        source = migration.read_text(encoding="utf-8")
        source = re.sub(
            r"CREATE\s+VIRTUAL\s+TABLE\s+published_units_fts\s+USING\s+fts5\s*\(.*?\);",
            "",
            source,
            flags=re.IGNORECASE | re.DOTALL,
        )
        source = source.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
        source = re.sub(r"\bINTEGER\b", "BIGINT", source)
        source = re.sub(r"\bREAL\b", "DOUBLE PRECISION", source)
        source = source.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        for statement in source.split(";"):
            cleaned = statement.strip()
            if not cleaned or "published_units_fts" in cleaned:
                continue
            statements.append(cleaned)
    return statements


class Database:
    def __init__(self, path: Path, migrations_root: Path | None = None, database_url: str = "") -> None:
        self.path = path
        self.database_url = database_url.strip()
        self.migrations_root = migrations_root or Path(__file__).with_name("migrations")
        self._engine: Any = None

    @property
    def backend(self) -> str:
        return "postgresql" if self.database_url.startswith(("postgresql://", "postgresql+")) else "sqlite"

    def connect(self) -> sqlite3.Connection | PostgresConnection:
        if self.backend == "postgresql":
            if self._engine is None:
                from sqlalchemy import create_engine

                self._engine = create_engine(self.database_url, pool_pre_ping=True, future=True)
            return PostgresConnection(self._engine)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30, factory=ManagedConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def migrate(self) -> list[str]:
        if self.backend == "postgresql":
            from alembic import command
            from alembic.config import Config

            config = Config()
            config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
            config.set_main_option("sqlalchemy.url", self.database_url.replace("%", "%%"))
            command.upgrade(config, "head")
            return ["alembic:head"]
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
