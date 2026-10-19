"""
共享组件装配：把 LLM、Embedding、向量库、文本知识库、图片库拼成一个 context 对象。

Web 服务常驻时只 build 一次，避免每次请求都重新加载 BGE 模型 / 重建索引。
"""
from __future__ import annotations

from types import SimpleNamespace

from .config import Config
from .embedding import EmbeddingClient
from .image_library import ImageLibrary
from .knowledge import KnowledgeBase
from .llm import LLMClient
from .vectorstore import VectorStore


def build_context(cfg: Config, llm_provider: str | None = None):
    """按配置构建所有共享组件，返回一个带属性的命名空间对象 ctx。"""
    provider = (llm_provider or cfg.llm_provider).lower()

    # 1) LLM 客户端（对话生成）
    llm = LLMClient(
        provider=provider,
        base_url=cfg.llm_base_url,
        api_key=cfg.api_key,
        model=cfg.llm_model,
        temperature=cfg.llm_temperature,
    )
    # 2) 向量化（默认本地 BGE 中文模型）
    embedder = EmbeddingClient(
        provider=cfg.embedding_provider,
        dim=cfg.embedding_dim,
        cache_dir=str(cfg.model_cache_dir),
        base_url=cfg.embedding_base_url,
        api_key=cfg.embedding_api_key,
        model=cfg.embedding_model,
    )
    # 3) SQLite 向量库（持久化，多集合）
    vectorstore = VectorStore(cfg.vectorstore_path)
    # 4) 文本知识库（方案范文/图例规范/设备参数 3 集合）
    kb = KnowledgeBase(cfg.knowledge_dir, embedder, vectorstore)
    # 5) 图片库（设备照片）
    image_lib = ImageLibrary(cfg.image_library_dir, embedder, vectorstore)
    # 6) 模板库（透明底可拼模板，用于建图）
    from .station_library import StationLibrary
    from .template_library import TemplateLibrary
    template_lib = TemplateLibrary(cfg.template_dir, embedder, vectorstore, collection="templates")
    station_lib = StationLibrary(cfg.project_root / "data" / "station_diagrams", embedder, vectorstore)

    return SimpleNamespace(llm=llm, embedder=embedder, vectorstore=vectorstore,
                           kb=kb, image_lib=image_lib, template_lib=template_lib,
                           station_lib=station_lib)