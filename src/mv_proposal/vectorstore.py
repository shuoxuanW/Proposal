"""
SQLite 持久化向量库：多集合、元数据过滤、向量 + BM25 混合检索（RRF 融合）。

用 SQLite 存向量（BLOB），简单可靠、零重依赖，重启不丢；
检索时向量相似度 + BM25 关键词打分做 RRF 融合，兼顾语义和关键词。
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def _tokenize(text: str) -> list[str]:
    """分词：英文单词 + 单个汉字 + 汉字二元组。"""
    t = text.lower()
    tokens = _TOKEN_RE.findall(t)
    tokens += [a + b for a, b in zip(re.findall(r"[\u4e00-\u9fff]", t), re.findall(r"[\u4e00-\u9fff]", t)[1:])]
    return tokens


class VectorStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # 表结构：collection + id 联合主键
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS vectors(
                collection TEXT NOT NULL,
                id TEXT NOT NULL,
                text TEXT,
                metadata TEXT,
                embedding BLOB,
                PRIMARY KEY(collection, id)
            )
        """)
        self._conn.commit()

    # ---------- 写 ----------
    def upsert_many(self, collection: str, items: Iterable[dict[str, Any]]) -> None:
        """批量写入/更新向量。items: [{id, text, embedding, metadata}]"""
        rows = []
        for it in items:
            blob = np.asarray(it["embedding"], dtype=np.float32).tobytes()
            rows.append((collection, it["id"], it.get("text", ""),
                         json.dumps(it.get("metadata") or {}, ensure_ascii=False), blob))
        self._conn.executemany("INSERT OR REPLACE INTO vectors VALUES(?,?,?,?,?)", rows)
        self._conn.commit()

    def delete_collection(self, collection: str) -> None:
        """清空某集合。"""
        self._conn.execute("DELETE FROM vectors WHERE collection=?", (collection,))
        self._conn.commit()

    # ---------- 读 ----------
    def count(self, collection: str) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM vectors WHERE collection=?", (collection,))
        return int(cur.fetchone()[0])

    def _rows(self, collection: str) -> list[tuple[str, str, dict, np.ndarray]]:
        """读取集合全部行：id, text, metadata, embedding。"""
        cur = self._conn.execute(
            "SELECT id,text,metadata,embedding FROM vectors WHERE collection=?", (collection,))
        out = []
        for id_, text, meta, blob in cur.fetchall():
            out.append((id_, text or "", json.loads(meta or "{}"), np.frombuffer(blob, dtype=np.float32)))
        return out

    # ---------- 检索 ----------
    def search(self, collection: str, query_vec: list[float], top_k: int = 3,
               metadata_filter: dict[str, Any] | None = None,
               keyword_weight: float = 0.3, query_text: str = "") -> list[dict[str, Any]]:
        """向量 + BM25 混合检索（RRF 融合），支持元数据过滤。"""
        q = np.asarray(query_vec, dtype=np.float32)
        qn = np.linalg.norm(q) or 1.0
        vec_scores: dict[str, float] = {}
        docs: dict[str, tuple[str, dict]] = {}
        for id_, text, meta, vec in self._rows(collection):
            # 元数据过滤（如 device_type=light_source）
            if metadata_filter and any(meta.get(k) != v for k, v in metadata_filter.items()):
                continue
            sim = float(np.dot(q, vec) / (np.linalg.norm(vec) * qn + 1e-9))
            vec_scores[id_] = sim
            docs[id_] = (text, meta)

        # BM25 关键词打分
        kw_scores: dict[str, float] = {}
        if query_text and keyword_weight > 0:
            from rank_bm25 import BM25Okapi
            ids = list(docs)
            corpus = [_tokenize(docs[i][0]) for i in ids]
            if corpus:
                bm25 = BM25Okapi(corpus)
                for i, s in zip(ids, bm25.get_scores(_tokenize(query_text))):
                    kw_scores[i] = float(s)

        # RRF 融合：排名倒数求和
        def rank_list(d: dict[str, float]) -> list[str]:
            return sorted(d, key=lambda x: d[x], reverse=True)

        vec_rank = {i: r for r, i in enumerate(rank_list(vec_scores))}
        kw_rank = {i: r for r, i in enumerate(rank_list(kw_scores))} if kw_scores else {}
        K = 60
        fused: dict[str, float] = {}
        for i in docs:
            fused[i] = (1.0 / (K + vec_rank.get(i, 1e9))) + (keyword_weight * 3.0) * (1.0 / (K + kw_rank.get(i, 1e9)))

        ordered = sorted(fused, key=lambda x: fused[x], reverse=True)[:top_k]
        out = []
        for i in ordered:
            text, meta = docs[i]
            out.append({"id": i, "text": text, "metadata": meta,
                        "score": round(vec_scores[i], 4), "fused": round(fused[i], 6)})
        return out

    def close(self) -> None:
        self._conn.close()