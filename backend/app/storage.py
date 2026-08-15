from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx

from .config import Settings


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StorageBackup:
    storage_key: str
    path: Path
    content_type: str = "application/pdf"


class StorageService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def save(self, storage_key: str, content: bytes, content_type: str) -> None:
        try:
            if self.settings.storage_mode == "supabase":
                self._save_supabase(storage_key, content, content_type)
                return
            path = self._resolve_local_path(storage_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        except httpx.HTTPError as error:
            raise StorageError("Storage request failed.") from error

    def read(self, storage_key: str) -> bytes:
        try:
            if self.settings.storage_mode == "supabase":
                return self._read_supabase(storage_key)
            path = self._resolve_local_path(storage_key)
            if not path.exists():
                raise StorageError("The uploaded PDF could not be found.")
            return path.read_bytes()
        except httpx.HTTPError as error:
            raise StorageError("Storage request failed.") from error

    def backup_many(self, storage_keys: list[str]) -> list[StorageBackup]:
        if not storage_keys:
            return []
        backup_root = Path(tempfile.mkdtemp(prefix="syllabus-delete-"))
        backups: list[StorageBackup] = []
        try:
            for index, storage_key in enumerate(storage_keys):
                backup_path = backup_root / f"{index:08d}.pdf"
                backup_path.write_bytes(self.read(storage_key))
                backups.append(StorageBackup(storage_key=storage_key, path=backup_path))
        except Exception:
            shutil.rmtree(backup_root, ignore_errors=True)
            raise
        return backups

    def restore_many(self, backups: list[StorageBackup]) -> None:
        restored: list[StorageBackup] = []
        try:
            for backup in backups:
                self.save(backup.storage_key, backup.path.read_bytes(), backup.content_type)
                restored.append(backup)
        except (StorageError, httpx.HTTPError) as error:
            raise StorageError(
                f"Could not restore {backups[len(restored)].storage_key}."
            ) from error

    def cleanup_backups(self, backups: list[StorageBackup]) -> None:
        backup_roots = {backup.path.parent for backup in backups}
        for backup_root in backup_roots:
            shutil.rmtree(backup_root, ignore_errors=True)

    def delete_many(self, storage_keys: list[str]) -> list[StorageBackup]:
        if not storage_keys:
            return []
        backups = self.backup_many(storage_keys)
        try:
            if self.settings.storage_mode == "supabase":
                self._delete_many_supabase(backups)
                return backups
            self._delete_many_local(backups)
            return backups
        except Exception:
            self.cleanup_backups(backups)
            raise

    def _resolve_local_path(self, storage_key: str) -> Path:
        upload_root = self.settings.local_storage_path.resolve()
        path = (upload_root / storage_key).resolve()
        try:
            path.relative_to(upload_root)
        except ValueError as error:
            raise StorageError("Resolved storage path fell outside the upload root.") from error
        return path

    def _headers(self) -> dict[str, str]:
        key = self.settings.supabase_service_role_key
        if not key:
            raise StorageError("Supabase service role is not configured on the backend.")
        return {"Authorization": f"Bearer {key}", "apikey": key}

    def _supabase_object_url(self, storage_key: str, *, authenticated: bool = False) -> str:
        if not self.settings.supabase_url:
            raise StorageError("Supabase URL is not configured.")
        access_scope = "authenticated/" if authenticated else ""
        bucket = quote(self.settings.supabase_storage_bucket, safe="")
        encoded_key = quote(storage_key, safe="/")
        return (
            f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/"
            f"{access_scope}{bucket}/{encoded_key}"
        )

    def _save_supabase(self, storage_key: str, content: bytes, content_type: str) -> None:
        url = self._supabase_object_url(storage_key)
        headers = {**self._headers(), "Content-Type": content_type, "x-upsert": "false"}
        response = httpx.post(url, headers=headers, content=content, timeout=60)
        if response.is_error:
            raise StorageError(
                f"Supabase Storage rejected the upload with status {response.status_code}."
            )

    def _read_supabase(self, storage_key: str) -> bytes:
        url = self._supabase_object_url(storage_key, authenticated=True)
        response = httpx.get(url, headers=self._headers(), timeout=60)
        if response.is_error:
            raise StorageError(f"Supabase Storage returned status {response.status_code}.")
        return response.content

    def _delete_many_local(self, backups: list[StorageBackup]) -> None:
        deleted: list[StorageBackup] = []
        try:
            for backup in backups:
                path = self._resolve_local_path(backup.storage_key)
                if not path.exists():
                    raise StorageError("The uploaded PDF could not be found.")
                path.unlink()
                deleted.append(backup)
        except Exception as error:
            self.restore_many(deleted)
            if isinstance(error, StorageError):
                raise
            raise StorageError("The uploaded PDF could not be deleted.") from error

    def _delete_many_supabase(self, backups: list[StorageBackup]) -> None:
        if not self.settings.supabase_url:
            raise StorageError("Supabase URL is not configured.")
        url = (
            f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/"
            f"{self.settings.supabase_storage_bucket}"
        )
        deleted: list[StorageBackup] = []
        for index in range(0, len(backups), 1000):
            batch = backups[index : index + 1000]
            response = httpx.delete(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"prefixes": [backup.storage_key for backup in batch]},
                timeout=60,
            )
            if response.is_error:
                self.restore_many(deleted)
                raise StorageError(
                    f"Supabase Storage rejected the delete with status {response.status_code}."
                )
            deleted.extend(batch)
