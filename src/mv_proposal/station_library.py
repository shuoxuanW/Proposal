"""
工位示意图库（历史工位/光路示意图的检索集合）。

入库预处理：图片入库时先跑一次 VLM，把读图结果（component_list/connection_list）
存为 sidecar JSON；检索时对「摘要文本」做向量检索，命中后直接用 sidecar JSON 渲染，
无需二次读图。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class StationLibrary:
    COLLECTION = "stations"

    def __init__(self, root: Path, embedder, store):
        self.root = Path(root)
        self.embedder = embedder
        self.store = store
        self.entries: list[dict[str, Any]] = []
        self.rebuild()

    @staticmethod
    def _project_from_stem(stem: str) -> str:
        """从文件名里取项目名：去掉 _slideN 后缀，并把 -/_ 转成空格方便检索。"""
        name = re.sub(r"_slide\d+$", "", stem)
        return re.sub(r"[\-_]+", " ", name).strip()

    def _scan(self):
        out = []
        if not self.root.exists():
            return out
        for png in sorted(self.root.glob("*.png")):
            side = png.with_suffix(".json")
            if not side.exists():
                continue
            data = json.loads(side.read_text(encoding="utf-8"))
            meta = data.get("meta") or {}
            project = meta.get("project") or self._project_from_stem(png.stem)
            comps = [" ".join(filter(None, [c.get("name", ""), c.get("position", "")]))
                     for c in data.get("component_list", [])]
            keywords = " ".join(meta.get("keywords") or [])
            light_txt = "；".join(" ".join(filter(None, [
                str(s.get("name", "")), str(s.get("type", "")),
                str(s.get("angle", "")), str(s.get("distance_to_object", "")),
            ])) for s in (data.get("light_spec_list") or []))
            # 检索文本：文件名/项目名 + 图类型 + 视角 + 部件名与位置 + 光源规格 + 结构化关键词 + 完整备注
            text = "，".join(filter(None, [
                png.stem, project, data.get("drawing_type", ""), data.get("view_type", ""),
                "，".join(comps), light_txt, keywords, data.get("note", ""),
            ]))
            out.append({"id": png.stem, "text": text, "png": str(png), "data": data,
                        "project": project, "meta": meta,
                        "embedding": self.embedder.embed(text)})
        return out

    def rebuild(self):
        self.entries = self._scan()
        self.store.delete_collection(self.COLLECTION)
        items = [{"id": e["id"], "text": e["text"], "embedding": e["embedding"],
                  "metadata": {"id": e["id"], "png": e["png"], "project": e["project"],
                               "drawing_type": e["data"].get("drawing_type", "")}}
                 for e in self.entries]
        if items:
            self.store.upsert_many(self.COLLECTION, items)

    def count(self):
        return len(self.entries)

    def search(self, query, top_k=3):
        qv = self.embedder.embed(query)
        hits = self.store.search(self.COLLECTION, qv, top_k=max(top_k, 3), query_text=query)
        out = []
        for h in hits:
            e = next((x for x in self.entries if x["id"] == h["metadata"]["id"]), None)
            if e:
                out.append({"id": e["id"], "png": e["png"], "data": e["data"],
                            "project": e["project"], "score": h["score"]})
        return out[:top_k]
