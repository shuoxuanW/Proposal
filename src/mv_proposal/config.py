"""配置加载：默认值 + .env + config.yaml 覆盖。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# src/mv_proposal/config.py -> parents[0]=mv_proposal, [1]=src, [2]=项目根
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(root: Path) -> None:
    """轻量 .env 加载（不覆盖已有环境变量）。"""
    p = root / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ[k] = v          # .env 优先：覆盖系统环境里的旧值（否则新 key 会被旧 DASHSCOPE_API_KEY 压住）


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Config:
    project_root: Path = PROJECT_ROOT
    name: str = "机器视觉解决方案书自动生成系统"
    language: str = "zh-CN"

    image_library_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "image_library")
    knowledge_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "knowledge")
    samples_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "samples")
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "output")

    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    llm_temperature: float = 0.3

    vlm_provider: str = "dashscope"
    vlm_model: str = "qwen3-vl-plus"
    vlm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    vlm_api_key_env: str = "DASHSCOPE_API_KEY"

    embedding_provider: str = "bge"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_api_key_env: str = "DASHSCOPE_API_KEY"
    embedding_dim: int = 512

    top_k: int = 3
    score_threshold: float = 0.0

    framework_groups: list[dict] = field(default_factory=list)
    device_types: dict[str, dict] = field(default_factory=dict)
    chain: list[list[str]] = field(default_factory=list)

    export_formats: list[str] = field(default_factory=lambda: ["markdown", "html", "docx", "pdf"])
    image_dpi: int = 150

    search_backend: str = "sqlite"            # sqlite | es（精准匹配后端）
    es_url: str = "http://127.0.0.1:9200"
    es_index: str = "vision_templates"
    vector_weight: float = 0.5                # 向量模糊权重
    precise_weight: float = 0.5               # 精准匹配权重

    template_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "image_templates")
    vectorstore_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "vector.db")
    model_cache_dir: Path = field(default_factory=lambda: PROJECT_ROOT / ".model_cache")
    ppt_template: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "templates" / "视觉方案书格式.pptx")
    ppt_profile: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "templates" / "visual_proposal_profile.yaml")

    def ensure_dirs(self) -> None:
        for d in (self.image_library_dir, self.knowledge_dir, self.samples_dir, self.output_dir, self.model_cache_dir):
            d.mkdir(parents=True, exist_ok=True)

    def device_label(self, dtype: str) -> str:
        return self.device_types.get(dtype, {}).get("label", dtype)

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env)

    @property
    def vlm_api_key(self) -> str | None:
        return os.environ.get(self.vlm_api_key_env)

    @property
    def embedding_api_key(self) -> str | None:
        return os.environ.get(self.embedding_api_key_env)

    @classmethod
    def load(cls, root: Path | None = None) -> "Config":
        root = root or PROJECT_ROOT
        _load_dotenv(root)
        cfg = cls(project_root=root)
        yaml_path = root / "config.yaml"
        if yaml_path.exists():
            cfg._apply(_read_yaml(yaml_path))
        # 环境变量覆盖（Docker/部署时用，覆盖 config.yaml 中的绝对路径）
        for env, attr in (("MV_IMAGE_LIBRARY", "image_library_dir"),
                          ("MV_KNOWLEDGE", "knowledge_dir"),
                          ("MV_OUTPUT", "output_dir"),
                          ("MV_VECTORSTORE", "vectorstore_path"),
                          ("MV_MODEL_CACHE", "model_cache_dir")):
            v = os.environ.get(env)
            if v:
                setattr(cfg, attr, Path(v))
        cfg.ensure_dirs()
        return cfg

    def _apply(self, raw: dict[str, Any]) -> None:
        p = raw.get("project", {})
        if p.get("name"):
            self.name = p["name"]
        if p.get("language"):
            self.language = p["language"]

        paths = raw.get("paths", {})
        base = self.project_root

        def _p(v):
            _path = Path(v)
            return _path if _path.is_absolute() else base / _path

        if paths.get("image_library"):
            self.image_library_dir = _p(paths["image_library"])
        if paths.get("knowledge"):
            self.knowledge_dir = _p(paths["knowledge"])
        if paths.get("samples"):
            self.samples_dir = _p(paths["samples"])
        if paths.get("output"):
            self.output_dir = _p(paths["output"])
        if paths.get("ppt_template"):
            self.ppt_template = _p(paths["ppt_template"])
        if paths.get("ppt_profile"):
            self.ppt_profile = _p(paths["ppt_profile"])

        llm = raw.get("llm", {})
        if llm.get("provider"):
            self.llm_provider = llm["provider"]
        if llm.get("model"):
            self.llm_model = llm["model"]
        if llm.get("base_url"):
            self.llm_base_url = llm["base_url"]
        elif llm.get("dashscope_base_url"):
            self.llm_base_url = llm["dashscope_base_url"]
        if llm.get("api_key_env"):
            self.api_key_env = llm["api_key_env"]
        if "temperature" in llm:
            self.llm_temperature = float(llm["temperature"])

        vlm = raw.get("vlm", {})
        if vlm.get("provider"):
            self.vlm_provider = vlm["provider"]
        if vlm.get("model"):
            self.vlm_model = vlm["model"]
        if vlm.get("base_url"):
            self.vlm_base_url = vlm["base_url"]
        if vlm.get("api_key_env"):
            self.vlm_api_key_env = vlm["api_key_env"]

        emb = raw.get("embedding", {})
        if emb.get("provider"):
            self.embedding_provider = emb["provider"]
        if emb.get("model"):
            self.embedding_model = emb["model"]
        if emb.get("base_url"):
            self.embedding_base_url = emb["base_url"]
        if emb.get("api_key_env"):
            self.embedding_api_key_env = emb["api_key_env"]
        if emb.get("dim"):
            self.embedding_dim = int(emb["dim"])

        ret = raw.get("retrieval", {})
        if ret.get("top_k") is not None:
            self.top_k = int(ret["top_k"])
        if ret.get("score_threshold") is not None:
            self.score_threshold = float(ret["score_threshold"])

        fw = raw.get("framework", {})
        if fw.get("groups"):
            self.framework_groups = list(fw["groups"])
        if fw.get("device_types"):
            self.device_types = dict(fw["device_types"])
        if fw.get("chain"):
            self.chain = [list(c) for c in fw["chain"]]

        exp = raw.get("export", {})
        if exp.get("formats"):
            self.export_formats = list(exp["formats"])
        if exp.get("image_dpi") is not None:
            self.image_dpi = int(exp["image_dpi"])

        sr = raw.get("search", {})
        if sr.get("backend"):
            self.search_backend = sr["backend"]
        if sr.get("es_url"):
            self.es_url = sr["es_url"]
        if sr.get("es_index"):
            self.es_index = sr["es_index"]
        if sr.get("vector_weight") is not None:
            self.vector_weight = float(sr["vector_weight"])
        if sr.get("precise_weight") is not None:
            self.precise_weight = float(sr["precise_weight"])

        st = raw.get("storage", {})
        if st.get("vectorstore"):
            self.vectorstore_path = _p(st["vectorstore"])
        if st.get("model_cache"):
            self.model_cache_dir = _p(st["model_cache"])