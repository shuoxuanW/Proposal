"""
图文联动注册表：记录正文锚点 <-> 图 <-> 节点 <-> 图片素材 的双向映射。

存成 linkage.json，前端画布编辑/人工修改回流都依赖它。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LinkageRegistry:
    def __init__(self):
        self.entries: list[dict[str, Any]] = []

    def add(self, anchor_id: str, kind: str, chapter_id: str, chapter_title: str, **extra) -> None:
        """记一条联动：kind = fig | dev。"""
        entry = {"anchor_id": anchor_id, "kind": kind,
                 "chapter_id": chapter_id, "chapter_title": chapter_title, **extra}
        if entry not in self.entries:
            self.entries.append(entry)

    def to_dict(self) -> dict[str, Any]:
        return {"version": 1, "entries": self.entries}

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "LinkageRegistry":
        reg = cls()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            reg.entries = data.get("entries", [])
        return reg

    def find(self, anchor_id: str) -> list[dict[str, Any]]:
        return [e for e in self.entries if e["anchor_id"] == anchor_id]