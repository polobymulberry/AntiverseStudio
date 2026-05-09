"""Aliyun OSS client wrapper."""

from __future__ import annotations

from pathlib import Path

import oss2

from common.settings import SETTINGS


def build_bucket() -> oss2.Bucket:
    if not SETTINGS.oss_access_key_id or not SETTINGS.oss_secret_access_key:
        raise RuntimeError("缺少 OSS_ACCESS_KEY_ID / OSS_SECRET_ACCESS_KEY。")
    auth = oss2.Auth(SETTINGS.oss_access_key_id, SETTINGS.oss_secret_access_key)
    endpoint = SETTINGS.oss_endpoint_url.replace("https://", "").replace("http://", "")
    return oss2.Bucket(auth, endpoint, SETTINGS.oss_bucket_name)


def upload_file(local_path: Path, object_key: str) -> str:
    bucket = build_bucket()
    bucket.put_object_from_file(object_key, str(local_path))
    return f"{SETTINGS.oss_public_url.rstrip('/')}/{object_key.lstrip('/')}"

