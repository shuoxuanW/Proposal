"""
图片库知识库：递归扫描设备照片 → 向量索引 → 按设备类型检索。

约定：图片名 = 简介；设备类型优先同名 .json 的 device_type，否则按文件名关键词判定。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .device_classify import classify_text, device_label

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class ImageEntry:
    """一张设备照片的索引条目。"""
    def __init__(self, rel_path: str, device_type: str, name: str, description: str,
                 params: dict, tags: list[str], view: str = "", angle: str = "", color: str = ""):
        self.rel_path = rel_path
        self.device_type = device_type
        self.name = name
        self.description = description
        self.params = params or {}
        self.tags = tags or []
        self.view = view or ""
        self.angle = angle or ""
        self.color = color or ""
        self.text = self._text()

    def _text(self) -> str:
        """用于向量化的文本：类型+名称+描述+参数+标签+视角+角度+颜色。"""
        p = " ".join(f"{k}:{v}" for k, v in self.params.items())
        return f"{self.device_type} {self.name} {self.description} {self.view} {self.angle} {self.color} {p} {' '.join(self.tags)}"

    def to_dict(self) -> dict[str, Any]:
        return {"rel_path": self.rel_path, "device_type": self.device_type, "name": self.name,
                "description": self.description, "params": self.params, "tags": self.tags,
                "view": self.view, "angle": self.angle, "color": self.color}


class ImageLibrary:
    def __init__(self, root: Path, embedder, vectorstore, collection: str = "images"):
        self.root = Path(root)
        self.embedder = embedder
        self.store = vectorstore
        self.collection = collection
        self.entries: list[ImageEntry] = []
        self.rebuild()

    def _discover(self) -> list[ImageEntry]:
        """递归扫描图片；有同名 .json 用其 device_type，否则按文件名判定。"""
        entries: list[ImageEntry] = []
        if not self.root.exists():
            return entries
        for f in sorted(self.root.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in IMAGE_EXTS:
                continue
            if f.name.startswith(("_", "~$")):
                continue
            meta: dict[str, Any] = {}
            sidecar = f.with_suffix(".json")
            if sidecar.exists():
                try:
                    meta = json.loads(sidecar.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            stem = f.stem          # 图片名即简介
            dtype = meta.get("device_type") or classify_text(stem)
            entries.append(ImageEntry(
                rel_path=str(f.relative_to(self.root)).replace("\\", "/"),
                device_type=dtype, name=stem, description=stem,
                params=meta.get("params") or {}, tags=meta.get("tags") or [device_label(dtype)],
                view=meta.get("view", ""), angle=meta.get("angle", ""), color=meta.get("color", ""),
            ))
        return entries

    def rebuild(self) -> None:
        """重建索引：扫描 → 向量化 → 写入向量库集合 images。"""
        self.entries = self._discover()
        self.store.delete_collection(self.collection)
        items = []
        for e in self.entries:
            items.append({
                "id": e.rel_path, "text": e.text, "embedding": self.embedder.embed(e.text),
                "metadata": {"device_type": e.device_type, "rel_path": e.rel_path,
                             "name": e.name, "description": e.description,
                             "params": e.params, "tags": e.tags,
                             "view": e.view, "angle": e.angle, "color": e.color},
            })
        if items:
            self.store.upsert_many(self.collection, items)

    def search(self, device_type: str, query: str = "", top_k: int = 3) -> list[dict[str, Any]]:
        """混合检索：向量模糊匹配(BGE) + 精准匹配(型号/视角/角度/参数) 加权融合。"""
        qv = self.embedder.embed(query or device_type)
        # 先取更多候选（向量模糊），再做精准匹配融合
        results = self.store.search(self.collection, qv, top_k=max(top_k * 3, 9),
                                    metadata_filter={"device_type": device_type}, query_text=query)
        from .hybrid_search import fuse, precise_score
        p = {r["id"]: precise_score(r["metadata"], query) for r in results}
        results = fuse(results, p, vector_weight=0.5, precise_weight=0.5)
        out = []
        for r in results[:top_k]:
            m = r["metadata"]
            out.append({"rel_path": m["rel_path"], "device_type": m["device_type"],
                        "name": m["name"], "description": m["description"],
                        "params": m["params"], "tags": m["tags"],
                        "view": m.get("view", ""), "angle": m.get("angle", ""), "color": m.get("color", ""),
                        "score": r["score"], "precise": r.get("precise", 0.0),
                        "fused": r.get("fused", 0.0), "abs_path": str(self.root / m["rel_path"])})
        return out

    def best(self, device_type: str, query: str = "") -> dict[str, Any] | None:
        """取最匹配的一张。"""
        hits = self.search(device_type, query, top_k=1)
        return hits[0] if hits else None

    def list_types(self) -> list[str]:
        return sorted({e.device_type for e in self.entries})

    def count(self) -> int:
        return len(self.entries)

    def register(self, image_path: Path, meta: dict[str, Any]) -> ImageEntry:
        """人工修改/新增图片入库：复制 + 写元数据 + 重建索引。"""
        image_path = Path(image_path)
        dst = self.root / image_path.name
        if image_path.resolve() != dst.resolve():
            dst.write_bytes(image_path.read_bytes())
        (dst.with_suffix(".json")).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        self.rebuild()
        return ImageEntry(
            rel_path=str(dst.relative_to(self.root)).replace("\\", "/"),
            device_type=meta.get("device_type") or classify_text(dst.stem),
            name=dst.stem, description=dst.stem,
            params=meta.get("params") or {}, tags=meta.get("tags") or [],
        )