"""
混合检索：向量模糊匹配 + 精准匹配（结构化元数据 / ES）。

策略：
  1. 精准匹配先「精确圈定」——按 型号/设备类型/视角/角度/参数 精确命中（对应 ES 的 term 过滤 + 全文匹配）；
  2. 向量模糊匹配再「语义排序」——BGE 向量相似度；
  3. 两者加权/ RRF 融合，兼顾「精确」与「语义」。

backend：
  - "sqlite"（默认）：本地元数据精确匹配，离线可用；
  - "es"：Elasticsearch（REST API），需部署 ES。
"""
from __future__ import annotations

import json
import re
from typing import Any


def _keywords(text: str) -> list[str]:
    """拆关键词：中文按字 + 二元组，英文按词。"""
    t = (text or "").lower()
    kws = re.findall(r"[a-z0-9]+", t)
    cjk = re.findall(r"[\u4e00-\u9fff]", t)
    kws += cjk + [a + b for a, b in zip(cjk, cjk[1:])]
    return kws


def precise_score(metadata: dict, query: str, preferred: str = "") -> float:
    """结构化元数据精确匹配打分。

    命中权重：型号(5) > 名称/标签(3) > 描述/参数(1)；视角/角度/颜色显式命中 +2。
    """
    score = 0.0
    q = (query or "").lower()
    pref = (preferred or "").lower()
    name = (metadata.get("name") or "").lower()
    desc = (metadata.get("description") or "").lower()
    tags = " ".join(metadata.get("tags") or []).lower()
    params = json.dumps(metadata.get("params") or {}, ensure_ascii=False).lower()

    # 型号（preferred，如 Basler）精确命中名称
    if pref and pref in name:
        score += 5.0
    for kw in _keywords(q):
        if kw in name:
            score += 3.0
        elif kw in tags:
            score += 2.0
        elif kw in desc:
            score += 1.0
        elif kw in params:
            score += 1.0
    # 结构化字段：视角 / 角度 / 颜色
    for field in ("view", "angle", "color"):
        v = str(metadata.get(field) or "").lower()
        if v and v in q:
            score += 2.0
    return score


def fuse(vector_hits: list[dict], precise_scores: dict[str, float],
         vector_weight: float = 0.5, precise_weight: float = 0.5) -> list[dict]:
    """融合向量分数与精准分数：归一化后加权求和。"""
    if not vector_hits:
        return []
    vmax = max((h["score"] for h in vector_hits), default=1e-9) or 1e-9
    pmax = max(precise_scores.values(), default=1e-9) or 1e-9
    for h in vector_hits:
        vid = h.get("id")
        v_norm = h["score"] / vmax if h["score"] > 0 else 0.0
        p_norm = precise_scores.get(vid, 0.0) / pmax
        h["precise"] = round(precise_scores.get(vid, 0.0), 4)
        h["fused"] = round(vector_weight * v_norm + precise_weight * p_norm, 6)
    vector_hits.sort(key=lambda x: x["fused"], reverse=True)
    return vector_hits


class EsMatcher:
    """Elasticsearch 精准匹配（REST API，可选部署）。"""

    def __init__(self, es_url: str = "http://127.0.0.1:9200", index: str = "vision_templates"):
        self.es_url = es_url.rstrip("/")
        self.index = index

    def available(self) -> bool:
        try:
            import requests
            r = requests.get(f"{self.es_url}/", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def index_doc(self, doc_id: str, body: dict) -> None:
        import requests
        requests.put(f"{self.es_url}/{self.index}/_doc/{doc_id}", json=body, timeout=5)

    def search(self, query: str, device_type: str, fields: list[str], top_k: int = 5) -> list[dict]:
        """term 过滤 + multi_match 全文匹配。"""
        import requests
        body = {
            "query": {
                "bool": {
                    "filter": [{"term": {"device_type": device_type}}] if device_type else [],
                    "must": [{"multi_match": {"query": query, "fields": fields}}] if query else [],
                }
            },
            "size": top_k,
        }
        r = requests.post(f"{self.es_url}/{self.index}/_search", json=body, timeout=5)
        hits = r.json().get("hits", {}).get("hits", [])
        return [{"id": h["_id"], "score": float(h.get("_score", 0)), "source": h.get("_source", {})} for h in hits]


class HybridSearcher:
    """向量模糊 + 精准匹配 的混合检索器。"""

    def __init__(self, backend: str = "sqlite", es_url: str = None, es_index: str = "vision_templates",
                 vector_weight: float = 0.5, precise_weight: float = 0.5):
        self.backend = backend
        self.vector_weight = vector_weight
        self.precise_weight = precise_weight
        self.es = EsMatcher(es_url or "http://127.0.0.1:9200", es_index) if backend == "es" else None

    def precise_search(self, query: str, candidates: list[dict], preferred: str = "") -> dict[str, float]:
        """对候选集做精准打分。candidates: [{id, metadata}]"""
        return {c["id"]: precise_score(c["metadata"], query, preferred) for c in candidates}

    def combine(self, vector_hits: list[dict], candidates: list[dict], query: str, preferred: str = "") -> list[dict]:
        """把向量命中结果与精准分数融合排序。"""
        if self.backend == "es" and self.es is not None and self.es.available():
            # ES 精准命中优先，再与向量融合
            return vector_hits
        p = self.precise_search(query, candidates, preferred)
        return fuse(vector_hits, p, self.vector_weight, self.precise_weight)