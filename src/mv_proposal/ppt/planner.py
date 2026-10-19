"""页面规划：根据内容决定附录页、标题、正文、表格和图片。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..models import Chapter, DiagramArtifact, TaskPlan, VerifyReport


@dataclass
class SlideSpec:
    role: str
    title: str
    body: str = ""
    bullets: list[str] = field(default_factory=list)
    table: list[list[str]] = field(default_factory=list)
    images: list[str] = field(default_factory=list)


def _clean_md(text: str) -> str:
    text = re.sub(r"\[\[FIG:[^\]]+\]\]", "", text or "")
    text = re.sub(r"\[\[DEV:[^\]]+\]\]", "", text)
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        s = s.lstrip("> ").strip()
        s = re.sub(r"^\d+[.、]\s*", "", s)
        s = re.sub(r"^[-*•]\s*", "", s)
        s = s.replace("**", "")
        if s.startswith("|") or re.fullmatch(r"[-:|\s]+", s):
            continue
        if s.startswith("参考素材"):
            continue
        if s:
            lines.append(s)
    return "\n".join(lines)


def _chapter(chapters: list[Chapter] | None, cid: str, title: str) -> Chapter | None:
    for ch in chapters or []:
        if ch.id == cid or ch.title == title or title in ch.title:
            return ch
    return None


def _chapter_body(chapters: list[Chapter] | None, cid: str, title: str, limit: int = 900) -> str:
    ch = _chapter(chapters, cid, title)
    body = _clean_md(ch.content) if ch else ""
    return body[:limit]


def _metrics_table(plan: TaskPlan) -> list[list[str]]:
    rows = [["指标", "要求", "验证方法"]]
    metrics = plan.key_metrics or {}
    cc = getattr(plan, "case_constraints", None) or {}
    mapping = [
        ("检测精度", cc.get("accuracy") or metrics.get("精度")),
        ("生产节拍", metrics.get("速度") or cc.get("cycle_time")),
        ("视场", cc.get("fov") or metrics.get("视场")),
        ("相机工作距离", cc.get("working_distance") or metrics.get("工作距")),
        ("产品尺寸", cc.get("product_size") or plan.product_size),
        ("相机数量", str(cc.get("camera_count") or "")),
    ]
    for label, val in mapping:
        if val:
            rows.append([label, str(val), "标准样件重复检测 / 技术协议验收"])
    for spec in cc.get("light_specs", []) or []:
        if spec.get("distance_to_object"):
            rows.append(["光源到工件距离", str(spec["distance_to_object"]), "标准样件重复检测 / 技术协议验收"])
        if spec.get("angle"):
            rows.append(["光源角度", str(spec["angle"]), "标准样件重复检测 / 技术协议验收"])
    return rows


def _device_table(plan: TaskPlan) -> list[list[str]]:
    rows = [["设备", "型号/建议", "数量"]]
    cc = getattr(plan, "case_constraints", None) or {}
    model_map = {
        "camera": cc.get("camera_model", ""),
        "lens": cc.get("lens", ""),
        "light_source": cc.get("light_type", ""),
        "controller": cc.get("controller", ""),
        "ipc": cc.get("ipc", ""),
    }
    for d in plan.devices:
        hint = model_map.get(d.device_type, "") or d.spec_hint or "建议选型/待确认"
        rows.append([d.label or d.device_type, hint, str(d.quantity)])
    if len(rows) == 1:
        rows.append(["待选型", "以最终 BOM 为准", "-"])
    return rows


def _risk_bullets(plan: TaskPlan, report: VerifyReport | None) -> list[str]:
    cc = getattr(plan, "case_constraints", None) or {}
    items: list[str] = []
    if cc.get("light_type"):
        items.append(f"光源需按 {cc['light_type']} 方案验证，避免反光或阴影影响缺陷对比度。")
    if cc.get("working_distance"):
        items.append(f"安装时需保证工作距离 {cc['working_distance']}，并预留调焦与维护空间。")
    if cc.get("cycle_time"):
        items.append(f"节拍要求 {cc['cycle_time']}，需通过曝光、传输和算法耗时联调确认。")
    items += [
        "来料表面状态、油污或粉尘可能影响成像稳定性，建议增加遮光罩与定期清洁。",
        "正式验收前需使用客户真实样件进行算法阈值标定。",
    ]
    if report:
        friendly = {
            "PARAM_MISSING": "历史案例中的部分关键参数未在正文中完整体现，建议人工复核。",
            "DEVICE_MISMATCH": "设备清单与历史案例存在差异，建议确认替代型号及理由。",
            "OPTICAL_MISMATCH": "光路/光源类型与历史案例存在差异，建议确认打光方案。",
            "SECTION_MISSING": "方案书部分建议章节缺失，建议补充。",
        }
        for it in report.issues:
            if it.severity in ("warning", "error") and it.code in friendly:
                msg = friendly[it.code]
                if msg not in items:
                    items.append(msg)
    return items[:8]


def _artifact_images(artifacts: list[DiagramArtifact] | None, out_dir: Path, kinds: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for a in artifacts or []:
        if a.kind in kinds:
            p = Path(out_dir) / a.png_rel
            if p.exists():
                out.append(str(p))
    return out


def plan_appendix_slides(plan: TaskPlan, chapters: list[Chapter] | None,
                         artifacts: list[DiagramArtifact] | None, report: VerifyReport | None,
                         out_dir: Path) -> list[SlideSpec]:
    slides: list[SlideSpec] = []

    # 1) 检测效果与缺陷样张
    imgs = _artifact_images(artifacts, out_dir, ("detection", "workpiece", "station", "optic"))
    slides.append(SlideSpec(
        role="ch9",
        title="检测效果与缺陷样张",
        body=_chapter_body(chapters, "ch9", "检测效果与缺陷样张", limit=480 if imgs else 800) or (
            f"检测对象：{plan.detection_target}\n"
            f"检测项：{'、'.join(plan.requirements) or '以技术协议为准'}\n"
            "成像方式：工业相机配合专用光源采集缺陷图像。\n"
            "判定方式：算法输出 OK/NG，并保存缺陷图像与检测记录。"
        ),
        images=imgs,
    ))

    # 2) 验证数据与验收指标
    slides.append(SlideSpec(
        role="ch10",
        title="验证数据与验收指标",
        body="",
        table=_metrics_table(plan),
    ))

    # 3) 风险与注意事项
    slides.append(SlideSpec(
        role="ch11",
        title="风险与注意事项",
        body="",
        bullets=_risk_bullets(plan, report),
    ))

    # 4) 设备参数汇总
    if plan.devices:
        slides.append(SlideSpec(
            role="ch12",
            title="设备参数汇总",
            body="",
            table=_device_table(plan),
        ))
    return slides
