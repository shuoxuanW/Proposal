"""
LLM 客户端：统一封装不同大模型后端。

支持：
  - deepseek / dashscope / openai（OpenAI 兼容接口）
  - mock（离线兜底，结构化任务由各 Agent 内置逻辑兜底）
"""
from __future__ import annotations

import json
import re
from typing import Any

SUPPORTED = {"deepseek", "dashscope", "openai"}


class MockLLM:
    """离线占位实现：不调用 API，关键结构化任务由各 Agent 内置逻辑兜底。"""

    def complete(self, system: str, user: str) -> str:
        return ""

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        return {}


class ApiLLM:
    """真实 LLM（OpenAI 兼容接口）。"""

    def __init__(self, base_url: str, api_key: str, model: str, temperature: float = 0.3):
        self.model = model
        self.temperature = temperature
        try:
            from openai import OpenAI  # type: ignore
            self._client = OpenAI(api_key=api_key, base_url=base_url)
        except Exception as e:  # pragma: no cover
            self._client = None
            self._err = e

    def complete(self, system: str, user: str) -> str:
        """普通文本生成。"""
        if self._client is None:
            raise RuntimeError(f"LLM client unavailable: {self._err}")
        r = self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return r.choices[0].message.content or ""

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        """要求返回 JSON（开启 json_object 模式），并稳健解析。"""
        if self._client is None:
            raise RuntimeError(f"LLM client unavailable: {self._err}")
        kwargs: dict[str, Any] = dict(
            model=self.model,
            temperature=self.temperature,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        try:
            kwargs["response_format"] = {"type": "json_object"}
        except Exception:
            pass
        r = self._client.chat.completions.create(**kwargs)
        return extract_json(r.choices[0].message.content or "")


def extract_json(text: str) -> dict[str, Any]:
    """从 LLM 输出中稳健提取 JSON（容忍代码块包裹、前后杂字）。"""
    if not text:
        return {}
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                pass
    return {}


class LLMClient:
    """统一入口：provider 在支持列表且有 key 时用真实 API，否则 mock。"""

    def __init__(self, provider: str, base_url: str, api_key: str | None, model: str, temperature: float = 0.3):
        self.provider = (provider or "mock").lower()
        if self.provider in SUPPORTED and api_key:
            self._impl = ApiLLM(base_url, api_key, model, temperature)
        else:
            self._impl = MockLLM()
            self.provider = "mock"

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock"

    def complete(self, system: str, user: str) -> str:
        return self._impl.complete(system, user)

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        return self._impl.complete_json(system, user)