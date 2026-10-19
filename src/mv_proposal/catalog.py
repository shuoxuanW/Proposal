"""
产品目录知识库（独立于 MD 文本知识库）。

数据源：data/catalog/products.json（由海康标准产品手册解析而来，属「设备层官方资料」）。
集合名：catalog —— 与 MD 知识库的 proposals/devices/legends 分开，后续可跨库串联。

本知识库只做「设备层权威产品参数」的检索与参考，不参与方案书正文生成。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TYPE_LABEL = {"camera": "工业相机(面阵/板级)", "linescan": "工业线阵相机", "infrared": "红外相机",
              "lens": "镜头", "framegrabber": "采集卡", "cable": "线缆",
              "sensor3d": "3D轮廓/结构光", "stereo": "立体相机", "perception": "感知相机",
              "logistics": "物流视觉", "industry": "行业产品(2.5D系统)", "context": "应用案例", "series": "系列"}


def _product_text(t: str, e: dict) -> str:
    """把一条产品拼成可向量化的自然语言（供语义检索）。"""
    model = e.get("model", "")
    if t == "camera":
        return ("海康机器人 %s 工业面阵相机，分辨率%s，%s万像素，靶面%s，像元%gμm，%s快门，%s接口，%s，最大帧率%gfps"
                % (model, e.get("分辨率", ""), e.get("像素万", ""), e.get("靶面", ""),
                   e.get("像元μm", 0) or 0, e.get("快门", ""), e.get("接口", ""), e.get("颜色", ""),
                   e.get("帧率fps", 0) or 0))
    if t == "linescan":
        return ("海康机器人 %s 工业线阵相机，分辨率%s，像元%gμm，行频%gkHz，%s接口，%s"
                % (model, e.get("分辨率", ""), e.get("像元μm", 0) or 0,
                   e.get("行频kHz", 0) or 0, e.get("接口", ""), e.get("颜色", "")))
    if t == "infrared":
        return ("海康机器人 %s 红外相机，%s波段，%s，分辨率%s，帧率%g"
                % (model, e.get("波段", ""), e.get("类型2", ""), e.get("分辨率", ""), e.get("帧率", 0) or 0))
    if t == "framegrabber":
        return ("海康机器人 %s 采集卡，总线%s，%s个网口，带宽%s，功耗%gW"
                % (model, e.get("总线接口", ""), e.get("网口数", ""), e.get("带宽", ""), e.get("功耗W", 0) or 0))
    if t == "cable":
        return ("海康机器人 %s 线缆，%s接口，%s，长度%s"
                % (model, e.get("接口", ""), e.get("类别", ""), e.get("长度", "")))
    if t == "industry":
        parts = ["海康机器人 %s %s" % (model, e.get("类型", ""))]
        for k, v in e.items():
            if k in ("model", "类型") or v is None or str(v).strip() == "":
                continue
            parts.append("%s%s" % (k, v))
        return "，".join(parts)
    if t == "context":
        return ("应用案例：%s。识别难点：%s。检测效果：%s"
                % (e.get("应用场景", ""), e.get("识别难点", ""), e.get("检测效果", "")))
    if t in ("sensor3d", "stereo", "perception", "logistics"):
        if e.get("类型") in ("3D激光轮廓传感器", "双目单线3D轮廓传感器"):
            if e.get("近视场mm") is not None:      # MV-DL 双目单线（体积测量）
                parts = ["海康机器人 %s 双目单线3D轮廓传感器" % model]
                if e.get("近视场mm") is not None: parts.append("近视场%gmm" % e["近视场mm"])
                if e.get("远视场mm") is not None: parts.append("远视场%gmm" % e["远视场mm"])
                if e.get("净距离CDmm") is not None: parts.append("净距离%gmm" % e["净距离CDmm"])
                if e.get("测量范围MRmm") is not None: parts.append("测量范围%gmm" % e["测量范围MRmm"])
                if e.get("检测精度"): parts.append("检测精度" + e["检测精度"])
                if e.get("检测速度m/s"): parts.append("检测速度%sm/s" % e["检测速度m/s"])
                if e.get("扫描帧率fps"): parts.append("扫描帧率%sfps" % e["扫描帧率fps"])
                return "，".join(parts)
            parts = ["海康机器人 %s 3D激光轮廓传感器" % model]
            if e.get("单轮廓点数"): parts.append("单轮廓点数%d" % e["单轮廓点数"])
            if e.get("参考距离mm") is not None: parts.append("参考距离%gmm" % e["参考距离mm"])
            if e.get("Z轴测量范围mm") is not None: parts.append("Z轴测量范围%gmm" % e["Z轴测量范围mm"])
            if e.get("X轴测量范围"): parts.append("X轴测量范围" + e["X轴测量范围"])
            if e.get("Z轴分辨率µm"): parts.append("Z轴分辨率%sµm" % e["Z轴分辨率µm"])
            if e.get("Z轴重复精度µm"): parts.append("Z轴重复精度%sµm" % e["Z轴重复精度µm"])
            if e.get("扫描帧率"): parts.append("扫描帧率" + e["扫描帧率"])
            if e.get("激光波长nm"): parts.append("激光波长%dnm" % e["激光波长nm"])
            return "，".join(parts)
        parts = ["海康机器人 %s %s" % (model, e.get("类型", ""))]
        for k, v in e.items():
            if k in ("model", "类型", "原文参数", "版本"):
                continue
            if v is not None and str(v).strip() != "":
                parts.append("%s：%s" % (k, v))
        return "，".join(parts)
    if t == "lens":
        parts = ["海康机器人 %s 镜头" % model]
        if e.get("焦距mm") is not None:
            parts.append("焦距%gmm" % e["焦距mm"])
        if e.get("光圈范围"):
            parts.append("光圈%s" % e["光圈范围"])
        if e.get("畸变"):
            parts.append("畸变%s" % e["畸变"])
        if e.get("视场角D°") is not None:
            parts.append("视场角D%g°H%g°V%g°" % (e["视场角D°"], e.get("视场角H°", 0) or 0, e.get("视场角V°", 0) or 0))
        if e.get("最近摄距m") is not None:
            parts.append("最近摄距%gm" % e["最近摄距m"])
        if e.get("滤镜螺纹"):
            parts.append("滤镜螺纹%s" % e["滤镜螺纹"])
        if e.get("卡口"):
            parts.append("卡口%s" % e["卡口"])
        if e.get("标称MP") is not None:
            parts.append("标称%sMP" % e["标称MP"])
        return "，".join(parts)
    return model


class CatalogKB:
    """产品目录知识库：向量化到独立集合 catalog。"""

    COLLECTION = "catalog"

    def __init__(self, products_path: Path, embedder, store):
        self.path = Path(products_path)
        self.embedder = embedder
        self.store = store
        self.entries: list[dict[str, Any]] = []
        self.rebuild()

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        out = []
        for t in ("camera", "linescan", "infrared", "lens", "framegrabber", "cable",
                  "sensor3d", "stereo", "perception", "logistics", "industry"):
            for e in raw.get(t, []):
                if not e.get("model"):
                    continue
                meta = dict(e)
                meta["device_type"] = t
                meta["type_label"] = TYPE_LABEL.get(t, t)
                out.append({"text": _product_text(t, e), "meta": meta})
        # 应用案例层：场景 → 所属 2.5D 系列型号（双向关联，防只匹配到场景而找不到型号）
        industry_by_type = {}
        for e in raw.get("industry", []):
            industry_by_type.setdefault(e.get("类型", ""), []).append(e)
        for e in raw.get("context", []):
            series = e.get("系列", "")
            linked = [x for t, lst in industry_by_type.items() if t.startswith(series[:4]) for x in lst]
            models_txt = "、".join(x["model"] for x in linked[:8])
            text = _product_text("context", e) + ("。关联方案：" + models_txt if models_txt else "")
            meta = {"device_type": "context", "type_label": "应用案例", "系列": series,
                    "应用场景": e.get("应用场景", ""), "识别难点": e.get("识别难点", ""),
                    "检测效果": e.get("检测效果", ""), "关联型号": [x["model"] for x in linked]}
            out.append({"text": text, "meta": meta})

        # 系列层：定位/适用场景 + 关联型号清单（场景 ↔ 型号 ↔ 参数 的桥梁）
        for e in raw.get("series", []):
            models = e.get("关联型号", [])
            text = "%s：%s。适用场景：%s。关联型号：%s" % (
                e.get("系列", ""), e.get("定位", ""), e.get("适用场景", ""),
                "；".join(models[:30]))
            meta = {"device_type": "series", "type_label": "系列",
                    "系列": e.get("系列", ""), "设备类型": e.get("设备类型", ""),
                    "定位": e.get("定位", ""), "适用场景": e.get("适用场景", ""),
                    "关联型号数": e.get("关联型号数", 0), "关联型号": models}
            out.append({"text": text, "meta": meta})
        return out

    def rebuild(self) -> None:
        self.entries = self._load()
        self.store.delete_collection(self.COLLECTION)
        items = [{"id": e["meta"].get("model") or ("series:" + e["meta"].get("系列", "")),
                  "text": e["text"], "embedding": self.embedder.embed(e["text"]),
                  "metadata": e["meta"]} for e in self.entries]
        if items:
            self.store.upsert_many(self.COLLECTION, items)

    def count(self) -> int:
        return len(self.entries)

    def by_type(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entries:
            t = e["meta"]["device_type"]
            out[t] = out.get(t, 0) + 1
        return out

    def search(self, query: str, top_k: int = 5, device_type: str | None = None) -> list[dict[str, Any]]:
        qv = self.embedder.embed(query)
        filt = {"device_type": device_type} if device_type else None
        hits = self.store.search(self.COLLECTION, qv, top_k=max(top_k, 3), metadata_filter=filt, query_text=query)
        out = []
        for h in hits:
            m = h["metadata"]
            out.append({"model": m.get("model") or m.get("系列", ""), "device_type": m["device_type"],
                        "type_label": m.get("type_label", ""), "score": h["score"], "fields": m})
        return out[:top_k]
