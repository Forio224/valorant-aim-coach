# -*- coding: utf-8 -*-
"""Хранилище клипов и улик (Этап 1 запуска): local (dev) | r2 (прод).

local — диск API-хоста, как раньше: улики раздаёт StaticFiles /evidence.
r2 — S3-совместимый бакет (Cloudflare R2): клип загружается фронтом по
presigned PUT мимо API, воркер скачивает его во временный файл, улики
уезжают в бакет и отдаются presigned GET. Ретеншн клипов (7 дней) —
lifecycle-правило бакета на префикс uploads/, не код.

boto3-клиент инжектируется — тесты живут без сети и без R2.
"""
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterator, List, Optional, Protocol

UPLOAD_PREFIX = "uploads/"
EVIDENCE_PREFIX = "evidence/"
PUT_EXPIRY_S = 15 * 60          # окно на загрузку клипа фронтом
GET_EXPIRY_S = 60 * 60          # улики в отчёте; поллинг обновляет URL


class Storage(Protocol):
    def presign_upload(self, filename: str) -> Optional[dict]:
        """None — грузить напрямую в API (local); dict {upload_url, key}."""

    def fetch_video(self, video_ref: str):
        """Контекст с локальным путём к клипу (r2 — временный файл)."""

    def publish_evidence(self, session_id: str,
                         frame_paths: List[str]) -> List[str]:
        """Кадры-улики -> рефы для БД (local: URL, r2: ключи бакета)."""

    def resolve_evidence_urls(self, refs: List[str]) -> List[str]:
        """Рефы из БД -> URL для фронта (r2: presigned GET)."""

    def video_size(self, key: str) -> Optional[int]:
        """Размер загруженного клипа; None — объекта нет."""

    def delete_video(self, key: str) -> None:
        """Удалить клип (превышение лимита; ретеншн — lifecycle бакета)."""


class LocalStorage:
    """Диск API-хоста; поведение до Этапа 1 — без изменений."""

    def __init__(self, evidence_dir: str):
        self.evidence_dir = evidence_dir

    def presign_upload(self, filename: str) -> Optional[dict]:
        return None

    @contextmanager
    def fetch_video(self, video_ref: str) -> Iterator[str]:
        yield video_ref

    def publish_evidence(self, session_id: str,
                         frame_paths: List[str]) -> List[str]:
        return [f"/evidence/{session_id}/{Path(p).name}" for p in frame_paths]

    def resolve_evidence_urls(self, refs: List[str]) -> List[str]:
        return list(refs)

    def video_size(self, key: str) -> Optional[int]:
        return os.path.getsize(key) if os.path.exists(key) else None

    def delete_video(self, key: str) -> None:
        if os.path.exists(key):
            os.remove(key)


class R2Storage:
    """S3-совместимый бакет; not_found — класс ошибки head_object."""

    def __init__(self, client, bucket: str, not_found=Exception):
        self._client = client
        self._bucket = bucket
        self._not_found = not_found

    def presign_upload(self, filename: str) -> dict:
        # Ключ — UUID: имя файла не утекает в бакет (там бывают ники и даты).
        ext = os.path.splitext(filename)[1].lower()
        key = f"{UPLOAD_PREFIX}{uuid.uuid4()}{ext}"
        url = self._client.generate_presigned_url(
            "put_object", Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=PUT_EXPIRY_S)
        return {"upload_url": url, "key": key}

    @contextmanager
    def fetch_video(self, video_ref: str) -> Iterator[str]:
        ext = os.path.splitext(video_ref)[1] or ".mp4"
        tmp = NamedTemporaryFile(suffix=ext, delete=False)
        tmp.close()
        try:
            self._client.download_file(self._bucket, video_ref, tmp.name)
            yield tmp.name
        finally:
            if os.path.exists(tmp.name):
                os.remove(tmp.name)

    def publish_evidence(self, session_id: str,
                         frame_paths: List[str]) -> List[str]:
        refs = []
        for path in frame_paths:
            key = f"{EVIDENCE_PREFIX}{session_id}/{Path(path).name}"
            self._client.upload_file(path, self._bucket, key)
            os.remove(path)                   # диск API/воркера не копим
            refs.append(key)
        return refs

    def resolve_evidence_urls(self, refs: List[str]) -> List[str]:
        urls = []
        for ref in refs:
            if ref.startswith("/"):           # легаси-сессии local-режима
                urls.append(ref)
                continue
            urls.append(self._client.generate_presigned_url(
                "get_object", Params={"Bucket": self._bucket, "Key": ref},
                ExpiresIn=GET_EXPIRY_S))
        return urls

    def video_size(self, key: str) -> Optional[int]:
        try:
            head = self._client.head_object(Bucket=self._bucket, Key=key)
        except self._not_found:
            return None
        return head["ContentLength"]

    def delete_video(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)


def create_storage(*, evidence_dir: str) -> Storage:
    """Собрать хранилище по STORAGE_BACKEND (local — дефолт | r2)."""
    backend = os.getenv("STORAGE_BACKEND", "local").strip().lower()
    if backend == "local":
        return LocalStorage(evidence_dir)
    if backend == "r2":
        missing = [var for var in ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID",
                                   "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
                   if not os.getenv(var)]
        if missing:
            raise ValueError(f"STORAGE_BACKEND=r2: не заданы {missing} "
                             f"(см. .env.example, секция R2_)")
        import boto3
        from botocore.exceptions import ClientError

        client = boto3.client(
            "s3",
            endpoint_url=os.environ["R2_ENDPOINT_URL"],
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto")
        return R2Storage(client=client, bucket=os.environ["R2_BUCKET"],
                         not_found=ClientError)
    raise ValueError(
        f"STORAGE_BACKEND={backend!r}: ожидается 'local' или 'r2'")
