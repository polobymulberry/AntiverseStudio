"""Clients for Qwen and Seedream services."""

from __future__ import annotations

import json
from typing import Any

import requests
from openai import OpenAI

from common.settings import SETTINGS


def create_qwen_client() -> OpenAI:
    if not SETTINGS.dashscope_api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY。")
    return OpenAI(api_key=SETTINGS.dashscope_api_key, base_url=SETTINGS.dashscope_base_url)


def qwen_chat(messages: list[dict[str, Any]], temperature: float = 0.7, top_p: float = 0.8) -> str:
    client = create_qwen_client()
    # DashScope 扩展字段须放在 extra_body；OpenAI SDK 不接受顶层 result_format。
    completion = client.chat.completions.create(
        model=SETTINGS.dashscope_model,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        extra_body={
            "result_format": "message",
            "enable_thinking": SETTINGS.enable_thinking,
            "thinking_budget": SETTINGS.thinking_budget,
        },
    )
    return completion.choices[0].message.content or ""


def seedream_generate(
    *,
    prompt: str,
    image_url: str,
    n: int = 4,
    size: str = "2048x2048",
    response_format: str = "url",
) -> dict[str, Any]:
    if not SETTINGS.seedream_api_key:
        raise RuntimeError("缺少 SEEDREAM_API_KEY。")
    url = f"{SETTINGS.seedream_base_url.rstrip('/')}{SETTINGS.seedream_endpoint}"
    headers = {
        "Authorization": f"Bearer {SETTINGS.seedream_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": SETTINGS.seedream_model,
        "prompt": prompt,
        "image": image_url,
        "n": n,
        "size": size,
        "response_format": response_format,
    }
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=180)
    if resp.status_code >= 400:
        raise RuntimeError(f"Seedream 请求失败: {resp.status_code} {resp.text}")
    return resp.json()

