"""宠物定制网站 API 客户端：按订单号拉取 3D 浮雕模型。

职责：
    封装订单查询、模型下载与本地落盘；API 契约随外部仓库演进，此处以 env 配置 endpoint。
业务作用：
    用户在宠物定制网站手工生成浮雕后，本仓库根据 ``order_id`` 拉取 GLB/OBJ 等到本地 ``model/``。
系统定位：
    Pet Stage3 拉模脚本与后续 Blender 渲染之间的数据接入层。

模型加载 / 超时 / 降级：
    - 优先调用远程 API；未配置 ``PET_CUSTOMIZATION_API_BASE_URL`` 时仅支持 ``--local-model-dir`` 手工拷贝。
    - HTTP 请求带指数退避重试；单文件下载超时见 ``PET_CUSTOMIZATION_DOWNLOAD_TIMEOUT``。
    - 响应须含可下载 URL 或 base64；校验扩展名与文件非空后写入目标目录。
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

from common.settings import SETTINGS


@dataclass(frozen=True)
class PetReliefModelFile:
    """单模型文件描述。

    Attributes:
        filename: 落盘文件名（含扩展名）。
        source_url: 远程下载 URL（与 ``content_bytes`` 二选一）。
        content_bytes: 内联二进制（API 直接返回 base64 时使用）。
    """

    filename: str
    source_url: str = ""
    content_bytes: bytes | None = None


@dataclass(frozen=True)
class PetReliefOrderPayload:
    """订单拉模 API 解析结果。

    Attributes:
        order_id: 订单号。
        status: 远程状态字符串。
        model_files: 待下载模型文件列表。
        raw: 原始 JSON（调试/审计）。
    """

    order_id: str
    status: str
    model_files: tuple[PetReliefModelFile, ...]
    raw: dict[str, Any]


class PetCustomizationClient:
    """宠物定制网站订单与模型 API 客户端。

    核心职责：
        按订单号查询浮雕任务状态并下载 3D 资产到本地目录。
    系统定位：
        外部宠物定制服务与本仓库 Pet Stage3 之间的 HTTP 适配层。
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
        download_timeout: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        self._base_url = (base_url if base_url is not None else SETTINGS.pet_customization_api_base_url).rstrip(
            "/"
        )
        self._api_key = api_key if api_key is not None else SETTINGS.pet_customization_api_key
        self._timeout = timeout if timeout is not None else SETTINGS.pet_customization_api_timeout
        self._download_timeout = (
            download_timeout
            if download_timeout is not None
            else SETTINGS.pet_customization_download_timeout
        )
        self._max_retries = max_retries if max_retries is not None else SETTINGS.pet_customization_max_retries

    def is_configured(self) -> bool:
        """是否已配置远程 API 根 URL。"""
        return bool(self._base_url)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """带重试的 JSON HTTP 请求。"""
        if not self._base_url:
            raise RuntimeError(
                "未配置 PET_CUSTOMIZATION_API_BASE_URL。"
                "请在 .env 中设置宠物定制 API 根地址，或使用 --local-model-dir 手工指定模型目录。"
            )
        url = urljoin(self._base_url + "/", path.lstrip("/"))
        last_err = ""
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = requests.request(
                    method,
                    url,
                    headers=self._headers(),
                    timeout=self._timeout,
                    **kwargs,
                )
                if resp.status_code >= 400:
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
                data = resp.json()
                if not isinstance(data, dict):
                    raise RuntimeError(f"API 响应不是 JSON 对象: {type(data)}")
                return data
            except (requests.RequestException, RuntimeError, json.JSONDecodeError) as exc:
                last_err = str(exc)
                if attempt >= self._max_retries:
                    break
                #  transient 错误退避，避免瞬时网络抖动打满配额
                time.sleep(min(2.0 ** (attempt - 1), 8.0))
        raise RuntimeError(f"宠物定制 API 请求失败（{method} {path}，重试 {self._max_retries} 次）: {last_err}")

    @staticmethod
    def _parse_model_files(node: dict[str, Any]) -> tuple[PetReliefModelFile, ...]:
        """从 API JSON 解析模型文件列表（兼容多种字段命名）。"""
        candidates: list[Any] = []
        for key in ("model_files", "files", "assets", "models"):
            val = node.get(key)
            if isinstance(val, list):
                candidates = val
                break
        if not candidates:
            # 单文件 shortcut：{"model_url": "...", "filename": "relief.glb"}
            url = (node.get("model_url") or node.get("glb_url") or node.get("download_url") or "").strip()
            if url:
                fname = (node.get("filename") or Path(url.split("?", 1)[0]).name or "relief.glb").strip()
                return (PetReliefModelFile(filename=fname, source_url=url),)
            return ()

        files: list[PetReliefModelFile] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            fname = (
                item.get("filename")
                or item.get("name")
                or item.get("file_name")
                or "relief.glb"
            )
            fname = str(fname).strip()
            url = (item.get("url") or item.get("download_url") or item.get("model_url") or "").strip()
            b64 = item.get("content_base64") or item.get("b64")
            content: bytes | None = None
            if b64:
                content = base64.b64decode(str(b64))
            if url or content:
                files.append(PetReliefModelFile(filename=fname, source_url=url, content_bytes=content))
        return tuple(files)

    def fetch_order(self, order_id: str) -> PetReliefOrderPayload:
        """查询订单并解析模型文件列表。

        Args:
            order_id: 宠物定制网站订单号。

        Returns:
            解析后的订单载荷；``model_files`` 可能为空（任务未完成）。
        """
        oid = (order_id or "").strip()
        if not oid:
            raise ValueError("order_id 不能为空。")
        # endpoint 路径可通过 env 覆盖，默认 REST 风格
        path = SETTINGS.pet_customization_order_path.format(order_id=oid)
        data = self._request_json("GET", path)
        status = str(data.get("status") or data.get("state") or "unknown").strip()
        files = self._parse_model_files(data)
        return PetReliefOrderPayload(order_id=oid, status=status, model_files=files, raw=data)

    def download_model_files(
        self,
        payload: PetReliefOrderPayload,
        dest_dir: Path,
        *,
        overwrite: bool = False,
    ) -> list[Path]:
        """将订单模型文件下载到 ``dest_dir``。

        Args:
            payload: :meth:`fetch_order` 的返回。
            dest_dir: 本地 ``model/`` 目录。
            overwrite: 是否覆盖已存在非空文件。

        Returns:
            成功落盘的文件路径列表。
        """
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        if not payload.model_files:
            raise RuntimeError(
                f"订单 {payload.order_id} 无可用模型文件（status={payload.status!r}）。"
                "请确认网站侧浮雕已生成完成。"
            )
        saved: list[Path] = []
        for mf in payload.model_files:
            out = dest_dir / mf.filename
            if out.is_file() and out.stat().st_size > 0 and not overwrite:
                saved.append(out.resolve())
                continue
            if mf.content_bytes is not None:
                out.write_bytes(mf.content_bytes)
            elif mf.source_url:
                self._download_url(mf.source_url, out)
            else:
                raise RuntimeError(f"模型条目缺少 url 与 content: {mf.filename}")
            if not out.is_file() or out.stat().st_size == 0:
                raise RuntimeError(f"下载后文件无效: {out}")
            saved.append(out.resolve())
        return saved

    def _download_url(self, url: str, dest: Path) -> None:
        """下载单个 URL 到本地文件（带重试）。"""
        last_err = ""
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = requests.get(url, timeout=self._download_timeout)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                return
            except requests.RequestException as exc:
                last_err = str(exc)
                if attempt >= self._max_retries:
                    break
                time.sleep(min(2.0 ** (attempt - 1), 8.0))
        raise RuntimeError(f"下载模型失败: {url} -> {dest} ({last_err})")


def copy_local_model_dir(src_dir: Path, dest_dir: Path, *, overwrite: bool = False) -> list[Path]:
    """将本地模型目录中的 3D 文件拷贝到订单 ``model/``（API 未就绪时的降级路径）。

    Args:
        src_dir: 用户手工放置 GLB/OBJ/FBX 的目录。
        dest_dir: 订单 model 目录。
        overwrite: 是否覆盖。

    Returns:
        拷贝后的路径列表。
    """
    src_dir = Path(src_dir).resolve()
    if not src_dir.is_dir():
        raise FileNotFoundError(f"本地模型目录不存在: {src_dir}")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    exts = {".glb", ".gltf", ".obj", ".fbx", ".stl", ".usdz"}
    copied: list[Path] = []
    for p in sorted(src_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        out = dest_dir / p.name
        if out.is_file() and out.stat().st_size > 0 and not overwrite:
            copied.append(out.resolve())
            continue
        out.write_bytes(p.read_bytes())
        copied.append(out.resolve())
    if not copied:
        raise RuntimeError(f"目录内无支持的 3D 文件: {src_dir}（扩展名 {sorted(exts)}）")
    return copied
