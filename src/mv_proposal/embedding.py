"""
向量化：把文本转成向量，供知识库/图片库检索。

支持：
  - bge（默认）：本地 BGE 中文模型（fastembed + ONNX，离线可用）
  - dashscope/openai：API embedding
  - hash：离线哈希兜底（无模型可用时）
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Iterable

# 国内网络访问 HuggingFace 的镜像（fastembed 内部用 huggingface_hub 下载模型）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


class HashEmbedder:
    """离线哈希向量兜底：字符 n-gram 哈希 + 符号，归一化。"""

    def __init__(self, dim: int = 512):
        self.dim = dim

    @staticmethod
    def _tokens(text: str) -> Iterable[str]:
        t = text.lower()
        cjk = re.findall(r"[\u4e00-\u9fff]", t)
        for ch in cjk:
            yield ch
        for a, b in zip(cjk, cjk[1:]):
            yield a + b
        for w in re.findall(r"[a-z0-9]+", t):
            yield w

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        n = 0
        for tok in self._tokens(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0 if (h >> 8) & 1 else -1.0
            n += 1
        if n == 0:
            return vec
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class BgeEmbedder:
    """本地中文 embedding 模型（fastembed + ONNX runtime）。"""

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5", cache_dir: str | None = None):
        from fastembed import TextEmbedding  # type: ignore
        kwargs: dict = {}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        self._model = TextEmbedding(model_name, **kwargs)

    def embed(self, text: str) -> list[float]:
        return [float(x) for x in list(self._model.embed([text]))[0]]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in self._model.embed(list(texts))]


class ApiEmbedder:
    """OpenAI 兼容接口的 embedding。"""

    def __init__(self, base_url: str, api_key: str, model: str, dimensions: int | None = None):
        self.model = model
        self.dimensions = dimensions
        try:
            from openai import OpenAI  # type: ignore
            self._client = OpenAI(api_key=api_key, base_url=base_url)
        except Exception as e:  # pragma: no cover
            self._client = None
            self._err = e

    def embed(self, text: str) -> list[float]:
        if self._client is None:
            raise RuntimeError(f"embedding client unavailable: {self._err}")
        kw: dict = {"model": self.model, "input": text}
        if self.dimensions:
            kw["dimensions"] = self.dimensions
        return list(self._client.embeddings.create(**kw).data[0].embedding)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self._client is None:
            raise RuntimeError(f"embedding client unavailable: {self._err}")
        kw: dict = {"model": self.model, "input": list(texts)}
        if self.dimensions:
            kw["dimensions"] = self.dimensions
        return [list(d.embedding) for d in self._client.embeddings.create(**kw).data]


class EmbeddingClient:
    """统一入口：bge（默认）| dashscope/openai | hash 兜底。"""

    def __init__(self, provider: str = "bge", dim: int = 512, cache_dir: str | None = None,
                 base_url: str = "", api_key: str | None = None, model: str = "BAAI/bge-small-zh-v1.5"):
        self.provider = provider
        self.fallback_reason: str | None = None
        if provider == "bge":
            try:
                self._impl = BgeEmbedder(model, cache_dir)
                self.provider = "bge"
            except Exception as e:
                # 模型加载失败时回退哈希
                self._impl = HashEmbedder(dim)
                self.provider = "hash"
                self.fallback_reason = str(e)
        elif provider in ("dashscope", "openai") and api_key:
            self._impl = ApiEmbedder(base_url, api_key, model)
        else:
            self._impl = HashEmbedder(dim)
            self.provider = "hash"

    def embed(self, text: str) -> list[float]:
        return self._impl.embed(text)

    def embed_batch(self, texts: Iterable[str]) -> list[list[float]]:
        texts = list(texts)
        if not texts:
            return []
        if hasattr(self._impl, "embed_batch"):
            return self._impl.embed_batch(texts)
        return [self.embed(t) for t in texts]


def cosine(a: list[float], b: list[float]) -> float:
    """两个向量的余弦相似度。"""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)