"""
文本知识库 RAG：3 个集合（方案范文库 / 图例规范库 / 设备参数库）。

每个集合对应一个目录，启动时自动：扫描文件 → 按 ## 标题切块 → BGE 向量化 → 存入 SQLite。
检索走 vectorstore（向量 + BM25 混合）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

TEXT_EXTS = {".md", ".txt", ".json"}

# 单块最小长度：低于此长度的碎块并入「同一章节」的上一块
# 典型场景：结构化 JSON（如光路图例规范）被按长度硬切后，尾部只剩 "}" 这类无信息碎块
MIN_CHUNK = 12

# 集合名 -> 中文名
COLLECTIONS = {
    "proposals": "方案范文库",
    "legends": "图例规范库",
    "devices": "设备参数库",
}


class TextChunk:
    """知识库里的一个文本块。"""
    def __init__(self, id: str, text: str, source: str, collection: str):
        self.id = id
        self.text = text
        self.source = source          # 来源文件相对路径
        self.collection = collection  # 所属集合


class KnowledgeBase:
    def __init__(self, root: Path, embedder, vectorstore):
        self.root = Path(root)
        self.embedder = embedder
        self.store = vectorstore
        self.chunks: dict[str, list[TextChunk]] = {c: [] for c in COLLECTIONS}
        self.rebuild()

    @staticmethod
    def _chunk_text(text: str, max_len: int = 480) -> list[str]:
        """按 ##/### 切块；孤立的标题行（如文档 H1）并入下一节，避免无内容空块虚高占位。"""
        text = re.sub(r"\r\n?", "\n", text)
        parts = re.split(r"\n(?=#{2,3}\s)", text)

        # 先把「只有一行标题、无正文」的块并入下一节
        merged: list[str] = []
        i = 0
        while i < len(parts):
            p = parts[i].strip()
            lines = [l for l in p.split("\n") if l.strip()]
            if len(lines) == 1 and lines[0].startswith("#") and i + 1 < len(parts):
                merged.append(p + "\n\n" + parts[i + 1].strip())
                i += 2
            else:
                merged.append(p)
                i += 1

        chunks: list[str] = []
        for p in merged:
            if not p:
                continue
            sec: list[str] = []          # 本节切出的块（只在节内合并，不跨章节）
            while len(p) > max_len:
                cut = p[:max_len].rsplit("\n", 1)
                head = cut[0] if len(cut) > 1 else p[:max_len]
                sec.append(head.strip())
                p = p[len(head):].strip()
            if p:
                sec.append(p)
            # 节内碎块归并：过短块先并入其后一块，末尾过短块再并入前一块
            # 覆盖两种碎块：超长章节切出的「## 标题」小块、结构化 JSON 尾部 "}"
            norm: list[str] = []
            for c in sec:
                if norm and len(norm[-1]) < MIN_CHUNK:
                    norm[-1] = (norm[-1] + "\n" + c).strip()
                else:
                    norm.append(c)
            if len(norm) > 1 and len(norm[-1]) < MIN_CHUNK:
                norm[-2] = (norm[-2] + "\n" + norm[-1]).strip()
                norm.pop()
            chunks.extend(norm)
        return chunks or [text]

    def _discover(self, collection: str) -> list[TextChunk]:
        """扫描某集合目录，读文件并切块。"""
        base = self.root / collection
        chunks: list[TextChunk] = []
        if not base.exists():
            return chunks
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in TEXT_EXTS or f.name.startswith("_"):
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            rel = str(f.relative_to(self.root)).replace("\\", "/")
            for i, c in enumerate(self._chunk_text(text)):
                if c.strip():
                    chunks.append(TextChunk(f"{rel}#{i}", c, rel, collection))
        return chunks

    def rebuild(self) -> None:
        """全量重建：清空集合 → 扫描 → 向量化 → 写入向量库。"""
        for coll in COLLECTIONS:
            self.chunks[coll] = self._discover(coll)
            self.store.delete_collection(coll)
            items = [{"id": c.id, "text": c.text, "embedding": self.embedder.embed(c.text),
                      "metadata": {"source": c.source, "collection": coll}} for c in self.chunks[coll]]
            if items:
                self.store.upsert_many(coll, items)

    # ---------- 检索 ----------
    def retrieve(self, collection: str, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """单集合检索。"""
        qv = self.embedder.embed(query)
        res = self.store.search(collection, qv, top_k=top_k, query_text=query)
        return [{"text": r["text"], "source": r["metadata"].get("source", ""),
                 "collection": collection, "score": r["score"]} for r in res]

    def retrieve_multi(self, collections: list[str], query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """跨集合检索并合并排序。"""
        out: list[dict[str, Any]] = []
        for c in collections:
            out += self.retrieve(c, query, top_k)
        out.sort(key=lambda x: -x["score"])
        return out[:top_k]

    # ---------- 回流 ----------
    def add(self, collection: str, text: str, source: str = "人工修改") -> TextChunk:
        """人工修改素材回流：加一块并重新向量化入库。"""
        cid = f"{source}#{self.store.count(collection) + 1}"
        chunk = TextChunk(cid, text.strip(), source, collection)
        self.store.upsert_many(collection, [{
            "id": cid, "text": chunk.text, "embedding": self.embedder.embed(chunk.text),
            "metadata": {"source": source, "collection": collection},
        }])
        self.chunks.setdefault(collection, []).append(chunk)
        return chunk

    # ---------- 统计 ----------
    def count(self, collection: str | None = None) -> int:
        """总块数或某集合块数。"""
        if collection:
            return self.store.count(collection)
        return sum(self.store.count(c) for c in COLLECTIONS)

    def collection_counts(self) -> dict[str, int]:
        return {c: self.store.count(c) for c in COLLECTIONS}