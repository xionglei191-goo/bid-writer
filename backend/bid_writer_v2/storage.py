from __future__ import annotations

import io
import hashlib
import mimetypes
from pathlib import Path
from typing import BinaryIO

from .database import Database
from .settings import Settings
from .utils import content_hash


class ObjectStorage:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.local_root = settings.data_root / "objects"
        self.local_root.mkdir(parents=True, exist_ok=True)
        self._client = None

    @property
    def mode(self) -> str:
        return "minio" if self.settings.minio_endpoint else "filesystem"

    def _minio(self):
        if self._client is None:
            from minio import Minio

            self._client = Minio(
                self.settings.minio_endpoint,
                access_key=self.settings.minio_access_key,
                secret_key=self.settings.minio_secret_key,
                secure=self.settings.minio_secure,
            )
            if not self._client.bucket_exists(self.settings.minio_bucket):
                self._client.make_bucket(self.settings.minio_bucket)
        return self._client

    def put_bytes(self, object_key: str, data: bytes, media_type: str = "application/octet-stream", mirror: Path | None = None) -> dict:
        object_key = object_key.replace("\\", "/").lstrip("/")
        digest = hashlib.sha256(data).hexdigest()
        if self.mode == "minio":
            self._minio().put_object(self.settings.minio_bucket, object_key, io.BytesIO(data), len(data), content_type=media_type)
        else:
            path = self.local_root / Path(object_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if mirror:
            mirror.parent.mkdir(parents=True, exist_ok=True)
            mirror.write_bytes(data)
        with self.db.connect() as conn:
            existing = conn.execute("SELECT id FROM object_records WHERE object_key=?", (object_key,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE object_records SET bucket=?,media_type=?,size_bytes=?,sha256=?,local_mirror_path=? WHERE id=?",
                    (self.settings.minio_bucket, media_type, len(data), digest, str(mirror or ""), existing[0]),
                )
                record_id = int(existing[0])
            else:
                cursor = conn.execute(
                    "INSERT INTO object_records(object_key,bucket,media_type,size_bytes,sha256,local_mirror_path) VALUES (?,?,?,?,?,?)",
                    (object_key, self.settings.minio_bucket, media_type, len(data), digest, str(mirror or "")),
                )
                record_id = int(cursor.lastrowid)
        return {"id": record_id, "object_key": object_key, "sha256": digest, "size_bytes": len(data), "storage": self.mode}

    def put_file(self, object_key: str, path: Path, mirror: Path | None = None) -> dict:
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return self.put_bytes(object_key, path.read_bytes(), media_type, mirror)

    def open(self, object_key: str) -> BinaryIO:
        if self.mode == "minio":
            response = self._minio().get_object(self.settings.minio_bucket, object_key)
            return io.BytesIO(response.read())
        return (self.local_root / Path(object_key)).open("rb")

    def health(self) -> dict:
        try:
            if self.mode == "minio":
                self._minio().bucket_exists(self.settings.minio_bucket)
            else:
                self.local_root.mkdir(parents=True, exist_ok=True)
            return {"status": "ok", "mode": self.mode, "bucket": self.settings.minio_bucket}
        except Exception:
            return {"status": "unavailable", "mode": self.mode, "bucket": self.settings.minio_bucket}
