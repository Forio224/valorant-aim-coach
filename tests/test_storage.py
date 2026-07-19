# -*- coding: utf-8 -*-
"""Этап 1 запуска: файлы в S3-совместимом хранилище (R2), dev — на диске.

Живой R2 в тестах не нужен: boto3-клиент инжектируется фейком — проверяем
контракт (ключи, presigned URL, очистку локальных файлов, легаси-рефы).
"""
import os
from pathlib import Path

import pytest

from backend.services.storage import (LocalStorage, R2Storage, create_storage)


# ---------------------------------------------------------------- фабрика

def test_default_backend_is_local(monkeypatch, tmp_path):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    storage = create_storage(evidence_dir=str(tmp_path))
    assert isinstance(storage, LocalStorage)


def test_r2_backend_requires_credentials(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "r2")
    for var in ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID",
                "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValueError, match="R2_"):
        create_storage(evidence_dir="evidence")


def test_unknown_backend_fails_fast(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "gcs")
    with pytest.raises(ValueError, match="STORAGE_BACKEND"):
        create_storage(evidence_dir="evidence")


# ------------------------------------------------------------------ local

def test_local_presign_is_direct(tmp_path):
    assert LocalStorage(str(tmp_path)).presign_upload("clip.mp4") is None


def test_local_fetch_video_yields_path_unchanged(tmp_path):
    storage = LocalStorage(str(tmp_path))
    with storage.fetch_video("uploads/x.mp4") as path:
        assert path == "uploads/x.mp4"


def test_local_publish_and_resolve_keep_current_urls(tmp_path):
    storage = LocalStorage(str(tmp_path))
    frame = tmp_path / "sid" / "frame_000177.jpg"
    frame.parent.mkdir()
    frame.write_bytes(b"jpg")

    refs = storage.publish_evidence("sid", [str(frame)])
    assert refs == ["/evidence/sid/frame_000177.jpg"]
    assert storage.resolve_evidence_urls(refs) == refs
    assert frame.exists()                     # локальные файлы не трогаем


# --------------------------------------------------------------------- r2

class FakeS3Client:
    def __init__(self):
        self.uploaded = []      # (path, bucket, key)
        self.deleted = []
        self.head_sizes = {}
        self.downloads = {}     # key -> bytes

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://r2.example/{op}/{Params['Key']}?exp={ExpiresIn}"

    def upload_file(self, path, bucket, key):
        self.uploaded.append((path, bucket, key))

    def download_file(self, bucket, key, path):
        Path(path).write_bytes(self.downloads[key])

    def head_object(self, Bucket, Key):
        if Key not in self.head_sizes:
            raise ClientError()
        return {"ContentLength": self.head_sizes[Key]}

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)


class ClientError(Exception):
    pass


@pytest.fixture
def r2():
    client = FakeS3Client()
    return R2Storage(client=client, bucket="aim", not_found=ClientError), client


def test_r2_presign_upload_returns_key_and_put_url(r2):
    storage, client = r2
    got = storage.presign_upload("моя игра.mp4")
    assert got["key"].startswith("uploads/")
    assert got["key"].endswith(".mp4")        # расширение сохранено
    assert "моя" not in got["key"]            # имя файла не утекает в ключ
    assert got["upload_url"].startswith("https://r2.example/put_object/")


def test_r2_fetch_video_downloads_and_cleans_up(r2, tmp_path):
    storage, client = r2
    client.downloads["uploads/k.mp4"] = b"video-bytes"
    with storage.fetch_video("uploads/k.mp4") as path:
        assert Path(path).read_bytes() == b"video-bytes"
        kept = path
    assert not os.path.exists(kept)           # temp-файл удалён после разбора


def test_r2_publish_evidence_uploads_and_removes_local(r2, tmp_path):
    storage, client = r2
    frame = tmp_path / "frame_000001.jpg"
    frame.write_bytes(b"jpg")

    refs = storage.publish_evidence("sid-1", [str(frame)])

    assert refs == ["evidence/sid-1/frame_000001.jpg"]
    assert client.uploaded == [(str(frame), "aim",
                                "evidence/sid-1/frame_000001.jpg")]
    assert not frame.exists()                 # диск API-хоста не копит улики


def test_r2_resolve_presigns_keys_but_passes_legacy_urls(r2):
    storage, client = r2
    urls = storage.resolve_evidence_urls(
        ["evidence/sid/frame_000001.jpg", "/evidence/old/frame_000002.jpg"])
    assert urls[0].startswith(
        "https://r2.example/get_object/evidence/sid/frame_000001.jpg")
    assert urls[1] == "/evidence/old/frame_000002.jpg"    # старые сессии


def test_r2_video_size_and_missing(r2):
    storage, client = r2
    client.head_sizes["uploads/k.mp4"] = 1234
    assert storage.video_size("uploads/k.mp4") == 1234
    assert storage.video_size("uploads/nope.mp4") is None


def test_r2_delete_video(r2):
    storage, client = r2
    storage.delete_video("uploads/k.mp4")
    assert client.deleted == ["uploads/k.mp4"]
