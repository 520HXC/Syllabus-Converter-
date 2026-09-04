from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.storage import StorageError, StorageService


def build_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "auth_mode": "dev",
        "storage_mode": "local",
        "local_storage_path": tmp_path / "uploads",
        "supabase_url": "https://example.supabase.co",
        "supabase_service_role_key": "service-role",
        "supabase_storage_bucket": "syllabi",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_supabase_object_reads_url_encode_the_storage_key(monkeypatch, tmp_path: Path):
    settings = build_settings(tmp_path, storage_mode="supabase")
    storage = StorageService(settings)
    requested_urls: list[str] = []

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        requested_urls.append(url)
        return httpx.Response(200, content=b"%PDF-1.4 test")

    monkeypatch.setattr("app.storage.httpx.get", fake_get)

    storage.read("user-a/semester-a/course #1?.pdf")

    assert requested_urls == [
        "https://example.supabase.co/storage/v1/object/authenticated/"
        "syllabi/user-a/semester-a/course%20%231%3F.pdf"
    ]


def test_delete_many_removes_local_files_inside_upload_root(tmp_path: Path):
    settings = build_settings(tmp_path)
    storage = StorageService(settings)
    first = settings.local_storage_path / "user-a" / "semester-a" / "one.pdf"
    second = settings.local_storage_path / "user-a" / "semester-a" / "two.pdf"
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    backups = storage.delete_many(
        ["user-a/semester-a/one.pdf", "user-a/semester-a/two.pdf"]
    )

    assert not first.exists()
    assert not second.exists()
    assert backups
    assert all(backup.path.exists() for backup in backups)
    assert not hasattr(backups[0], "content")

    storage.cleanup_backups(backups)

    assert all(not backup.path.exists() for backup in backups)


def test_delete_many_rejects_local_path_escape(tmp_path: Path):
    settings = build_settings(tmp_path)
    storage = StorageService(settings)

    with pytest.raises(StorageError, match="outside the upload root"):
        storage.delete_many(["../secrets.txt"])


def test_discard_new_uploads_ignores_missing_keys_while_deleting_existing_local_files(
    tmp_path: Path,
):
    settings = build_settings(tmp_path)
    storage = StorageService(settings)
    existing = settings.local_storage_path / "user-a" / "semester-a" / "one.pdf"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"one")

    storage.discard_new_uploads(
        ["user-a/semester-a/one.pdf", "user-a/semester-a/missing.pdf"]
    )

    assert not existing.exists()


def test_discard_new_uploads_raises_when_local_cleanup_hits_os_error(
    monkeypatch,
    tmp_path: Path,
):
    settings = build_settings(tmp_path)
    storage = StorageService(settings)
    existing = settings.local_storage_path / "user-a" / "semester-a" / "one.pdf"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"one")

    def fail_unlink(self, missing_ok: bool = False):
        raise OSError("disk offline")

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with pytest.raises(StorageError, match="could not be deleted"):
        storage.discard_new_uploads(["user-a/semester-a/one.pdf"])


def test_delete_many_batches_supabase_exact_keys(monkeypatch, tmp_path: Path):
    settings = build_settings(tmp_path, storage_mode="supabase")
    storage = StorageService(settings)
    requests: list[tuple[str, dict[str, object], dict[str, str]]] = []

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        return httpx.Response(200, content=b"%PDF-1.4 test")

    def fake_delete(
        method: str, url: str, headers: dict[str, str], json: dict[str, object], timeout: int,
    ):
        assert method == "DELETE"
        requests.append((url, json, headers))
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr("app.storage.httpx.get", fake_get)
    monkeypatch.setattr("app.storage.httpx.request", fake_delete)
    keys = [f"user-a/semester-a/file-{index}.pdf" for index in range(1005)]

    storage.delete_many(keys)

    assert [request[0] for request in requests] == [
        "https://example.supabase.co/storage/v1/object/syllabi",
        "https://example.supabase.co/storage/v1/object/syllabi",
    ]
    assert requests[0][1] == {"prefixes": keys[:1000]}
    assert requests[1][1] == {"prefixes": keys[1000:]}
    assert all(request[2]["Authorization"] == "Bearer service-role" for request in requests)


def test_delete_many_raises_on_supabase_error(monkeypatch, tmp_path: Path):
    settings = build_settings(tmp_path, storage_mode="supabase")
    storage = StorageService(settings)

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        return httpx.Response(200, content=b"%PDF-1.4 test")

    def fake_delete(
        method: str, url: str, headers: dict[str, str], json: dict[str, object], timeout: int,
    ):
        assert method == "DELETE"
        return httpx.Response(500, json={"error": "boom"})

    monkeypatch.setattr("app.storage.httpx.get", fake_get)
    monkeypatch.setattr("app.storage.httpx.request", fake_delete)

    with pytest.raises(StorageError, match="Supabase Storage rejected the delete"):
        storage.delete_many(["user-a/semester-a/file.pdf"])


def test_discard_new_uploads_uses_verified_supabase_delete_contract(
    monkeypatch,
    tmp_path: Path,
):
    settings = build_settings(tmp_path, storage_mode="supabase")
    storage = StorageService(settings)
    requests: list[tuple[str, dict[str, object], dict[str, str], int]] = []

    def fake_delete(
        method: str, url: str, headers: dict[str, str], json: dict[str, object], timeout: int,
    ):
        assert method == "DELETE"
        requests.append((url, json, headers, timeout))
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr("app.storage.httpx.request", fake_delete)

    storage.discard_new_uploads(["user-a/semester-a/file.pdf"])

    assert requests == [
        (
            "https://example.supabase.co/storage/v1/object/syllabi",
            {"prefixes": ["user-a/semester-a/file.pdf"]},
            {
                "Authorization": "Bearer service-role",
                "apikey": "service-role",
                "Content-Type": "application/json",
            },
            60,
        )
    ]


def test_discard_new_uploads_raises_on_supabase_error(monkeypatch, tmp_path: Path):
    settings = build_settings(tmp_path, storage_mode="supabase")
    storage = StorageService(settings)

    def fake_delete(
        method: str, url: str, headers: dict[str, str], json: dict[str, object], timeout: int,
    ):
        assert method == "DELETE"
        return httpx.Response(500, json={"error": "boom"})

    monkeypatch.setattr("app.storage.httpx.request", fake_delete)

    with pytest.raises(StorageError, match="Supabase Storage rejected the delete"):
        storage.discard_new_uploads(["user-a/semester-a/file.pdf"])


def test_discard_new_uploads_does_not_hide_supabase_not_found(monkeypatch, tmp_path: Path):
    settings = build_settings(tmp_path, storage_mode="supabase")
    storage = StorageService(settings)

    def fake_delete(
        method: str, url: str, headers: dict[str, str], json: dict[str, object], timeout: int,
    ):
        assert method == "DELETE"
        return httpx.Response(404, json={"error": "not found"})

    monkeypatch.setattr("app.storage.httpx.request", fake_delete)

    with pytest.raises(StorageError, match="Supabase Storage rejected the delete with status 404"):
        storage.discard_new_uploads(["user-a/semester-a/file.pdf"])


def test_discard_new_uploads_surfaces_supabase_transport_failure(monkeypatch, tmp_path: Path):
    settings = build_settings(tmp_path, storage_mode="supabase")
    storage = StorageService(settings)

    def fake_delete(
        method: str, url: str, headers: dict[str, str], json: dict[str, object], timeout: int,
    ):
        assert method == "DELETE"
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr("app.storage.httpx.request", fake_delete)

    with pytest.raises(StorageError, match="Storage request failed"):
        storage.discard_new_uploads(["user-a/semester-a/file.pdf"])


def test_delete_many_restores_files_after_partial_supabase_batch_failure(
    monkeypatch,
    tmp_path: Path,
):
    settings = build_settings(tmp_path, storage_mode="supabase")
    storage = StorageService(settings)
    deleted_batches: list[list[str]] = []
    restored: list[tuple[str, bytes, str]] = []

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        storage_key = url.split("/authenticated/syllabi/", 1)[1]
        return httpx.Response(200, content=f"backup:{storage_key}".encode())

    def fake_delete(
        method: str, url: str, headers: dict[str, str], json: dict[str, object], timeout: int,
    ):
        assert method == "DELETE"
        deleted_batches.append(list(json["prefixes"]))
        if len(deleted_batches) == 2:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json={"data": []})

    def fake_save(self, storage_key: str, content: bytes, content_type: str):
        restored.append((storage_key, content, content_type))

    monkeypatch.setattr("app.storage.httpx.get", fake_get)
    monkeypatch.setattr("app.storage.httpx.request", fake_delete)
    monkeypatch.setattr(StorageService, "save", fake_save)
    keys = [f"user-a/semester-a/file-{index}.pdf" for index in range(1001)]

    with pytest.raises(StorageError, match="Supabase Storage rejected the delete"):
        storage.delete_many(keys)

    assert deleted_batches == [keys[:1000], keys[1000:]]
    assert restored == [
        (storage_key, f"backup:{storage_key}".encode(), "application/pdf")
        for storage_key in keys[:1000]
    ]


@pytest.mark.parametrize("operation", ["delete_many", "discard_new_uploads"])
def test_supabase_deletion_uses_real_httpx_request_serialization(
    monkeypatch, tmp_path: Path, operation: str,
):
    storage = StorageService(build_settings(tmp_path, storage_mode="supabase"))
    requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, content=b"%PDF-1.4 test", request=request)
        return httpx.Response(200, json=[], request=request)

    # Keep HTTPX's public call signatures and JSON serialization real.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle_request)
    keys = ["user-a/semester-a/course #1.pdf"]
    backups = getattr(storage, operation)(keys)
    if backups:
        storage.cleanup_backups(backups)

    deletes = [request for request in requests if request.method == "DELETE"]
    assert len(deletes) == 1
    assert str(deletes[0].url) == "https://example.supabase.co/storage/v1/object/syllabi"
    assert json.loads(deletes[0].content) == {"prefixes": keys}
    assert deletes[0].headers["Content-Type"] == "application/json"
    assert deletes[0].headers["Authorization"] == "Bearer service-role"
