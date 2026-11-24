"""OpenAI 兼容的 LLM 客户端（仅标准库）。

密钥只从环境变量读，不入库、不写进配置文件。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def extract_text(payload: dict) -> str:
    """从 OpenAI 兼容响应中取出文本。"""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return message.get("content") or ""


class LlmClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, prompt: str, system: str = "") -> str:
        body = {
            "model": self.model,
            "messages": (
                ([{"role": "system", "content": system}] if system else [])
                + [{"role": "user", "content": prompt}]
            ),
            "temperature": 0.3,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return extract_text(payload)


def from_env(base_url: str | None = None, api_key: str | None = None,
             model: str | None = None) -> LlmClient | None:
    """从环境变量构造客户端；任一缺失返回 None（调用方走降级）。"""
    base_url = base_url if base_url is not None else os.environ.get("AGAISTOCK_LLM_BASE_URL", "")
    api_key = api_key if api_key is not None else os.environ.get("AGAISTOCK_LLM_API_KEY", "")
    model = model if model is not None else os.environ.get("AGAISTOCK_LLM_MODEL", "")
    if not (base_url and api_key and model):
        return None
    return LlmClient(base_url=base_url, api_key=api_key, model=model)
