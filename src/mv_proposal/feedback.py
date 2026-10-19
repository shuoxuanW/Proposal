"""
素材回流：人工修改后的图片/文本重新入库，形成“用→改→回→再用”闭环。
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import Config
from .context import build_context
from .linkage import LinkageRegistry


class FeedbackManager:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config.load()
        self.ctx = build_context(self.cfg)

    def ingest_image(self, image_path: str | Path, meta: dict) -> dict:
        """人工修改/新增的设备图片入库（复制进图片库 + 写元数据 + 重建索引）。"""
        entry = self.ctx.image_lib.register(Path(image_path), meta)
        return entry.to_dict()

    def ingest_text(self, text: str, source: str = "人工修改", collection: str = "proposals") -> dict:
        """人工修改的正文/参数文本回流到指定知识库集合。"""
        chunk = self.ctx.kb.add(collection, text, source)
        return {"source": chunk.source, "collection": chunk.collection, "text": chunk.text[:80]}

    def relink(self, anchor_id: str, new_label: str, run_dir: str | Path) -> dict:
        """人工改图后同步更新联动注册表，并回流知识库。"""
        linkage_path = Path(run_dir) / "linkage.json"
        reg = LinkageRegistry.load(linkage_path)
        matched = reg.find(anchor_id)
        for e in matched:
            if e.get("kind") == "dev":
                e["node_label"] = new_label
        reg.save(linkage_path)
        self.ctx.kb.add("proposals", f"[人工修订] 锚点 {anchor_id} 的设备标注更新为：{new_label}",
                        source="人工修改")
        return {"updated": len(matched), "entries": matched}