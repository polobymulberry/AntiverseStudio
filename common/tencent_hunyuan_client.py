"""Tencent Hunyuan 3D texture API wrapper."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from tencentcloud.ai3d.v20250513 import ai3d_client, models
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile

from common.settings import SETTINGS


def build_client() -> ai3d_client.Ai3dClient:
    secret_id = os.getenv("TENCENTCLOUD_SECRET_ID", "")
    secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY", "")
    if not secret_id or not secret_key:
        raise RuntimeError("缺少 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY。")
    cred = credential.Credential(secret_id, secret_key)
    http_profile = HttpProfile()
    http_profile.endpoint = "ai3d.tencentcloudapi.com"
    client_profile = ClientProfile()
    client_profile.httpProfile = http_profile
    return ai3d_client.Ai3dClient(cred, SETTINGS.tencent_region, client_profile)


def submit_texture_job(file3d_url: str, image_base64: str) -> dict[str, Any]:
    client = build_client()
    req = models.SubmitTextureTo3DJobRequest()
    params = {
        "File3D": {"Type": "OBJ", "Url": file3d_url},
        "Model": SETTINGS.tencent_hunyuan_model,
        "Image": {"Base64": image_base64},
        "EnablePBR": True,
    }
    req.from_json_string(json.dumps(params))
    delay = 5.0
    for attempt in range(1, 6):
        try:
            resp = client.SubmitTextureTo3DJob(req)
            return json.loads(resp.to_json_string())
        except TencentCloudSDKException as exc:
            code = (exc.code or "").strip()
            msg = exc.message or ""
            transient = (
                "RequestTimeout" in code
                or "RequestTimeout" in msg
                or "超时" in msg
                or "timeout" in msg.lower()
            )
            if not transient or attempt >= 5:
                raise
            time.sleep(delay)
            delay = min(delay * 1.5, 45.0)


def texture_job_json_body(data: dict[str, Any]) -> dict[str, Any]:
    """DescribeTextureTo3DJob 的 JSON：SDK 多为扁平字段；若带 Response 则取其内层。"""
    inner = data.get("Response")
    if isinstance(inner, dict):
        return inner
    return data


def texture_job_status(data: dict[str, Any]) -> str:
    return (texture_job_json_body(data).get("Status") or "").strip().upper()


def texture_job_error(data: dict[str, Any]) -> tuple[str, str]:
    b = texture_job_json_body(data)
    return (b.get("ErrorCode") or "").strip(), (b.get("ErrorMessage") or "").strip()


def _result_file3ds_as_dicts(body: dict[str, Any]) -> list[dict[str, Any]]:
    raw = body.get("ResultFile3Ds")
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def extract_texture_glb_and_image_urls(data: dict[str, Any]) -> tuple[str, str]:
    """从 DescribeTextureTo3DJob 返回中取出 GLB 与主图 URL。

    依据 ``ResultFile3Ds`` 中 ``Type`` 为 ``GLB`` / ``IMAGE`` / ``TEXTURE_IMAGE`` 等项的 ``Url``；
    ``File3D`` 项上若有 ``PreviewImageUrl`` 也会作为备选图 URL。
    """
    body = texture_job_json_body(data)
    items = _result_file3ds_as_dicts(body)
    glb_url = ""
    image_url = ""
    texture_image_url = ""
    for it in items:
        typ = (it.get("Type") or "").strip().upper()
        url = (it.get("Url") or "").strip()
        preview = (it.get("PreviewImageUrl") or "").strip()
        if typ == "GLB" and url:
            glb_url = url
            if preview:
                image_url = image_url or preview
        elif typ == "IMAGE" and url:
            image_url = image_url or url
        elif typ == "TEXTURE_IMAGE" and url:
            texture_image_url = texture_image_url or url
        elif typ == "OBJ" and url and preview:
            image_url = image_url or preview
    img = image_url or texture_image_url
    if not glb_url:
        glb_url = _legacy_scan_glb_url(body)
    return glb_url, img


def _legacy_scan_glb_url(node: Any) -> str:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "Url" and isinstance(v, str) and v.startswith("http") and v.lower().endswith(".glb"):
                return v
            found = _legacy_scan_glb_url(v)
            if found:
                return found
    elif isinstance(node, list):
        for x in node:
            found = _legacy_scan_glb_url(x)
            if found:
                return found
    elif isinstance(node, str) and node.startswith("http") and node.lower().endswith(".glb"):
        return node
    return ""


def describe_texture_job(job_id: str) -> dict[str, Any]:
    client = build_client()
    req = models.DescribeTextureTo3DJobRequest()
    req.from_json_string(json.dumps({"JobId": job_id}))
    resp = client.DescribeTextureTo3DJob(req)
    return json.loads(resp.to_json_string())

