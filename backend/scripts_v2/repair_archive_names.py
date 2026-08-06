"""Repair already extracted legacy Chinese ZIP member names."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bid_writer_v2.database import Database
from bid_writer_v2.knowledge.service import decode_archive_member_name
from bid_writer_v2.settings import Settings
from bid_writer_v2.utils import family_key, infer_industry, write_text_atomic


def safe_destination(root: Path, member_name: str) -> Path | None:
    destination = (root / member_name).resolve()
    if not str(destination).startswith(str(root.resolve()) + str(Path("/"))):
        return None
    return destination


def extract_repaired(archive_path: Path, target: Path) -> tuple[dict[str, str], int]:
    temporary = target.with_name(f"{target.name}.filename-repair")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    changed = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                repaired_name = decode_archive_member_name(member.filename, member.flag_bits)
                old_path = safe_destination(target, member.filename)
                new_path = safe_destination(temporary, repaired_name)
                final_path = safe_destination(target, repaired_name)
                if new_path is None or final_path is None:
                    continue
                if old_path is not None and old_path != final_path:
                    mapping[str(old_path)] = str(final_path)
                    changed += 1
                if member.is_dir():
                    new_path.mkdir(parents=True, exist_ok=True)
                else:
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, new_path.open("wb") as output:
                        shutil.copyfileobj(source, output)
        (temporary / ".complete").write_text("ok", encoding="ascii")
        if target.exists():
            shutil.rmtree(target)
        temporary.replace(target)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return mapping, changed


def repair(settings: Settings, database: Database, archive_id: int | None = None) -> dict[str, int]:
    counters = {"archives_checked": 0, "archives_repaired": 0, "members_repaired": 0, "rows_updated": 0, "failed": 0}
    with database.connect() as conn:
        if archive_id:
            archives = conn.execute(
                "SELECT * FROM source_files WHERE id=? AND extension='.zip'", (archive_id,)
            ).fetchall()
        else:
            archives = conn.execute(
                "SELECT * FROM source_files WHERE extension='.zip' AND source_kind='raw' ORDER BY id"
            ).fetchall()
    for archive in archives:
        counters["archives_checked"] += 1
        archive = dict(archive)
        archive_path = Path(archive["absolute_path"])
        target = settings.cache_root / "archives" / f"{archive['id']}_{archive['sha256'][:12]}"
        try:
            with zipfile.ZipFile(archive_path) as handle:
                affected = any(
                    decode_archive_member_name(item.filename, item.flag_bits) != item.filename
                    for item in handle.infolist()
                )
            if not affected:
                continue
            mapping, changed = extract_repaired(archive_path, target)
            with database.connect() as conn:
                children = conn.execute(
                    "SELECT id,absolute_path FROM source_files WHERE parent_source_id=?", (archive["id"],)
                ).fetchall()
                for child in children:
                    old_path = str(Path(child["absolute_path"]).resolve())
                    new_path_value = mapping.get(old_path)
                    if not new_path_value:
                        continue
                    new_path = Path(new_path_value)
                    relative_path = str(new_path.relative_to(settings.workspace_root))
                    conn.execute(
                        """
                        UPDATE source_files
                        SET absolute_path=?,relative_path=?,file_name=?,family_key=?,industry=?,updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                        """,
                        (
                            str(new_path),
                            relative_path,
                            new_path.name,
                            family_key(new_path),
                            infer_industry(new_path),
                            child["id"],
                        ),
                    )
                    counters["rows_updated"] += 1
            counters["archives_repaired"] += 1
            counters["members_repaired"] += changed
        except Exception:
            counters["failed"] += 1
    with database.connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM source_files ORDER BY id")]
    inventory_path = settings.knowledge_directories["metadata"] / "source_inventory.jsonl"
    write_text_atomic(inventory_path, "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n")
    return counters


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-id", type=int)
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.ensure_directories()
    database = Database(settings.db_path)
    database.migrate()
    print(json.dumps(repair(settings, database, args.archive_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
