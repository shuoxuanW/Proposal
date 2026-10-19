"""
模板库：索引「可拼模板」（透明底 + 标准尺寸 + 视角/角度/颜色元数据），供建图拼装。

与图片库的区别：图片库是原始示意图，模板库是预处理后的透明模板。
检索采用「向量模糊 + 精准匹配」混合策略（型号/视角/角度/颜色精确命中优先）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class TemplateEntry:
    def __init__(self, rel_path, device_type, name, view, angle, color, description):
        self.rel_path = rel_path
        self.device_type = device_type
        self.name = name
        self.view = view or ""
        self.angle = angle or ""
        self.color = color or ""
        self.description = description or name
        self.text = f"{device_type} {name} {view} {angle} {color} {description}"


class TemplateLibrary:
    def __init__(self, root: Path, embedder, vectorstore, collection: str = "templates"):
        self.root = Path(root)
        self.embedder = embedder
        self.store = vectorstore
        self.collection = collection
        self.entries: list[TemplateEntry] = []
        self.rebuild()

    def _discover(self) -> list[TemplateEntry]:
        entries = []
        if not self.root.exists():
            return entries
        for f in sorted(self.root.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in IMAGE_EXTS or f.name.startswith("_"):
                continue
            meta = {}
            sidecar = f.with_suffix(".json")
            if sidecar.exists():
                try:
                    meta = json.loads(sidecar.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            entries.append(TemplateEntry(
                rel_path=str(f.relative_to(self.root)).replace("\\", "/"),
                device_type=meta.get("device_type", "accessory"),
                name=f.stem,
                view=meta.get("view", ""),
                angle=meta.get("angle", ""),
                color=meta.get("color", ""),
                description=meta.get("description", ""),
            ))
        return entries

    def rebuild(self) -> None:
        self.entries = self._discover()
        self.store.delete_collection(self.collection)
        items = []
        for e in self.entries:
            items.append({
                "id": e.rel_path, "text": e.text, "embedding": self.embedder.embed(e.text),
                "metadata": {"device_type": e.device_type, "name": e.name,
                             "view": e.view, "angle": e.angle, "color": e.color,
                             "rel_path": e.rel_path, "description": e.description},
            })
        if items:
            self.store.upsert_many(self.collection, items)

    def search(self, device_type: str, query: str = "", top_k: int = 3) -> list[dict[str, Any]]:
        """混合检索：向量模糊 + 精准匹配（型号/视角/角度/颜色）。"""
        qv = self.embedder.embed(query or device_type)
        results = self.store.search(self.collection, qv, top_k=max(top_k * 3, 9),
                                    metadata_filter={"device_type": device_type}, query_text=query)
        from .hybrid_search import fuse, precise_score
        p = {r["id"]: precise_score(r["metadata"], query) for r in results}
        results = fuse(results, p, 0.4, 0.6)   # 拼图更看重精准匹配
        out = []
        for r in results[:top_k]:
            m = r["metadata"]
            out.append({"rel_path": m["rel_path"], "device_type": m["device_type"],
                        "name": m["name"], "view": m["view"], "angle": m["angle"], "color": m["color"],
                        "score": r["score"], "precise": r.get("precise", 0.0),
                        "fused": r.get("fused", 0.0), "abs_path": str(self.root / m["rel_path"])})
        return out

    def best(self, device_type: str, query: str = "") -> dict[str, Any] | None:
        hits = self.search(device_type, query, top_k=1)
        return hits[0] if hits else None

    def count(self) -> int:
        return len(self.entries)