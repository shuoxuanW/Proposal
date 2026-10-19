"""
选型流程（会议纪要定版）。

执行顺序（固定，不可颠倒）：
  第一步 案例优先：检索案例层 proposals，命中（分数≥阈值）→ 直接返回历史方案参考；
  第二步 兜底：案例召回不足时，动态设备组合（设备层 devices + 硬件强制配套校验）。

输出格式见 format_selection。基础版本不建场景层；不编造知识库内不存在的参数。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .compat import CompatReport, DeviceItem, check_compat, format_compat

CASE_THRESHOLD = 0.72    # 案例召回分数阈值（BGE 中文相似度：自匹配约0.8、跨案例约0.6~0.67，取中间值；可按实测校准）


@dataclass
class SelectionResult:
    source: str                       # 案例库召回 / AI动态选型
    matched_cases: list = field(default_factory=list)   # 命中的历史方案
    device_list: list = field(default_factory=list)     # DeviceItem 结构化硬件
    advice: list = field(default_factory=list)          # 选型建议文本（兜底规则）
    compat: CompatReport | None = None
    note: str = ""


def recall_cases(ctx, text: str, top_k: int = 3, threshold: float = CASE_THRESHOLD):
    """案例层召回：按方案文件去重，返回分数≥阈值的历史方案命中。"""
    # 同一份方案会被切成多个块，先多取一些再按 source 去重，避免前端重复显示同一案例
    hits = ctx.kb.retrieve("proposals", text, top_k=max(top_k * 4, 8))
    out: list[dict] = []
    seen: set[str] = set()
    for h in sorted(hits, key=lambda x: x["score"], reverse=True):
        src = h["source"]
        if h["score"] < threshold or src in seen:
            continue
        seen.add(src)
        out.append(h)
        if len(out) >= top_k:
            break
    return out


def _metric(text: str, patterns: tuple[str, ...]) -> float | None:
    for p in patterns:
        m = re.search(p, text)
        if m:
            return float(m.group(1))
    return None


def _dynamic_selection(ctx, text: str):
    """案例召回不足时的动态设备组合。模型结构化输出优先，确定性规则兜底。"""
    items = _llm_items(ctx, text)
    if items:
        return items, []
    return _rule_items(text), _rule_advice(text)


def _llm_items(ctx, text: str) -> list[DeviceItem] | None:
    """让模型基于设备层知识库输出结构化硬件清单（去硬编码）。离线/失败返回 None。"""
    llm = getattr(ctx, "llm", None)
    if llm is None or llm.is_mock:
        return None
    snippets = "\n".join(h["text"] for h in ctx.kb.retrieve("devices", text, top_k=5))
    from .compat import load_catalog
    catalog = load_catalog()
    cat_txt = json.dumps(catalog, ensure_ascii=False) if catalog else ""
    prompt = (
        "你是工业视觉设备选型工程师。基于设备层知识库，为下面需求输出硬件选型清单，只输出 JSON。\n"
        'JSON 结构：{"items":[{"device_type":"camera|lens|light_source|controller|ipc|cable","model":"","desc":"","qty":1}]}\n'
        "要求：\n"
        "1) model 必须是知识库或海康官方真实型号，没把握就留空；\n"
        "2) desc 必须逐类写出关键工程参数：\n"
        "   camera：像素(如2000万)+卡口(如C口)+接口(如GigE网口)；\n"
        "   lens：焦距+卡口(如C口/M42)+标称分辨率(如25MP)；\n"
        "   light_source：类型+颜色；\n"
        "   controller：通道数(如双通道/四通道)；\n"
        "   ipc：网口数(如双网口)+CPU；\n"
        '示例：{"device_type":"camera","model":"MV-CS200-10GM","desc":"2000万，C口，GigE网口","qty":1}\n'
        "设备目录（型号→参数，优先从目录选型号；线缆也按相机接口配套）：\n" + cat_txt[:3000] + "\n" +
        "历史项目设备参考：\n" + snippets[:2000]
    )
    try:
        data = llm.complete_json(prompt, "需求：\n" + text)
        raw = data.get("items") or []
        items = [DeviceItem(device_type=str(i.get("device_type", "")).strip(),
                            model=str(i.get("model", "")).strip(),
                            desc=str(i.get("desc", "")).strip(),
                            qty=int(i.get("qty", 1) or 1)) for i in raw if isinstance(i, dict)]
        return items or None
    except Exception:
        return None


def _rule_items(text: str) -> list[DeviceItem]:
    """确定性兜底：按指标反推硬件清单（型号留空，待人工/模型补全）。"""
    acc = _metric(text, (r"精度[^\d]{0,6}([\d.]+)", r"([\d.]+)\s*mm\s*/\s*pix"))
    fov = _metric(text, (r"视野\D{0,8}([\d.]+)",))
    wd = _metric(text, (r"工作距离\s*([\d.]+)",))
    mp = (fov / (acc / 3.0) / 1000) if (acc and fov) else None
    flen = (wd * 8.8 / fov) if (wd and fov) else None
    items = [
        DeviceItem("camera", "",
                   "全局快门 GigE 面阵相机" + ("，约 %d 百万像素以上" % mp if mp else ""), 1),
        DeviceItem("lens", "",
                   "C口 低畸变定焦镜头" + ("，焦距约 %dmm" % flen if flen else ""), 1),
    ]
    if re.search(r"划痕|凹坑|锈斑|针孔|麻点", text):
        items.append(DeviceItem("light_source", "", "低角度环形光，颜色与被测物形成对比", 1))
    elif re.search(r"反光|高亮|镜面|光面|焊锡|焊点", text):
        items.append(DeviceItem("light_source", "", "同轴光或偏振光，抑制镜面反光", 1))
    else:
        items.append(DeviceItem("light_source", "", "环形/条形光，保证缺陷对比度", 1))
    items.append(DeviceItem("controller", "", "数字光源控制器", 1))
    items.append(DeviceItem("ipc", "", "工控机，双网口，预留 PCIe 扩展", 1))
    return items


def _rule_advice(text: str) -> list[str]:
    """兜底的选型建议文本。"""
    acc = _metric(text, (r"精度[^\d]{0,6}([\d.]+)", r"([\d.]+)\s*mm\s*/\s*pix"))
    fov = _metric(text, (r"视野\D{0,8}([\d.]+)",))
    out = []
    if acc and fov:
        out.append("检测精度 %gmm、视场 %gmm → 单方向约 %d 像素，建议 %d 百万像素以上"
                   % (acc, fov, int(fov / (acc / 3.0)), int(fov / (acc / 3.0) / 1000)))
    else:
        out.append("分辨率按 3 像素覆盖最小缺陷反推")
    return out


def run_selection(ctx, text: str, threshold: float = CASE_THRESHOLD) -> SelectionResult:
    """主入口：案例优先 → 动态选型兜底。"""
    cases = recall_cases(ctx, text, threshold=threshold)
    if cases:
        return SelectionResult(
            source="案例库召回",
            matched_cases=cases,
            note="命中 %d 个历史方案，可直接复用框架与设备参数" % len(cases),
        )
    items, advice = _dynamic_selection(ctx, text)
    compat = check_compat(items)
    return SelectionResult(
        source="AI动态选型",
        device_list=items,
        advice=advice,
        compat=compat,
        note="案例库无足够匹配，进入动态设备组合，需人工复核校准",
    )


def format_selection(res: SelectionResult) -> str:
    """按会议纪要要求的输出格式渲染。"""
    lines: list[str] = []
    lines.append("> 【选型来源】：" + ("案例库召回" if res.source == "案例库召回" else "AI动态选型"))
    lines.append("> 【匹配说明】：" + res.note)
    lines.append("")
    lines.append("> 【硬件方案清单】")
    if res.source == "案例库召回":
        for c in res.matched_cases:
            lines.append("> - 参考方案：%s（相似度 %.2f）" % (c["source"], c["score"]))
            for line in c["text"].split("\n")[:4]:
                lines.append(">   " + line.strip()[:90])
    else:
        for it in res.device_list:
            label = {"camera": "工业相机", "lens": "镜头", "light_source": "光源",
                     "controller": "光源控制器", "ipc": "工控机"}.get(it.device_type, it.device_type)
            qty = "" if it.qty == 1 else "（共 %d 台/套）" % it.qty
            if it.model and it.desc:
                lines.append("> - %s：%s（%s）%s" % (label, it.model, it.desc, qty))
            else:
                lines.append("> - %s：%s%s" % (label, it.model or it.desc, qty))
        for a in res.advice:
            lines.append("> - 说明：" + a)
    lines.append("")
    lines.append("> 【配套校验结果】")
    if res.compat:
        lines += ["> " + x for x in format_compat(res.compat)]
    else:
        lines.append("> - 历史方案直接复用，未做动态配套校验（如需可对方案内硬件补校验）")
    lines.append("")
    lines.append("> 【风险提示】：AI生成方案需人工复核；知识库迭代目标 90%~98% 准确率")
    return "\n".join(lines)
