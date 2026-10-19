"""
设备选型建议生成：根据需求指标 + 光路参数，产出相机/镜头/光源/工控机/控制器的选型建议。

规则：
  - 相机：按“3 像素覆盖最小缺陷”反推分辨率（精度 + 视场）
  - 镜头：焦距 = 工作距 × 传感器宽 / 视场（2/3 英寸 ≈ 8.8mm）
  - 光源：优先用光路描述里的光源；否则按检测要求推断（划痕→环形光、反光→同轴光）
"""
from __future__ import annotations

import re


def _num(s: str) -> float | None:
    """从字符串里取第一个数字。"""
    r = re.search(r"\d+(?:\.\d+)?", s or "")
    return float(r.group(0)) if r else None


def _optic(plan):
    """取 TaskPlan 里的光路参数对象（若有）。"""
    for d in plan.diagrams:
        if d.kind == "optic" and getattr(d, "optic_spec", None):
            return d.optic_spec
    return None


def recommend_devices(plan) -> list[str]:
    """返回逐条选型建议。模型生成的优先，确定性规则仅作兜底。"""
    if getattr(plan, "selection_advice", None):
        return plan.selection_advice   # 大模型生成的选型建议（去硬编码）
    m = plan.key_metrics
    acc = _num(m.get("精度"))
    fov = _num(m.get("视场"))
    wd = _num(m.get("工作距"))
    reqs = " ".join(plan.requirements)
    recs: list[str] = []

    # 相机
    if acc and fov:
        px = fov / (acc / 3.0)
        recs.append(f"工业相机：检测精度 {acc:g}mm、视场 {fov:g}mm → 单方向约 {int(px)} 像素，"
                    f"建议 {px / 1000:.0f} 百万像素以上全局快门相机（GigE/USB3）")
    else:
        recs.append("工业相机：建议全局快门面阵相机，分辨率按 3 像素覆盖最小缺陷反推")

    # 镜头
    if wd and fov:
        f = wd * 8.8 / fov
        recs.append(f"镜头：工作距 {wd:g}mm、视场 {fov:g}mm → 焦距约 {f:.0f}mm；高精度测量建议双远心镜头")
    else:
        recs.append("镜头：建议低畸变定焦镜头；高精度测量选用双侧远心镜头（C 口）")

    # 光源
    ospec = _optic(plan)
    if ospec:
        recs.append(f"光源：建议 {ospec.light_color}{ospec.light_label}，安装角度 {int(ospec.tilt_min)}°~{int(ospec.tilt_max)}° 可调，"
                    f"底部距平台 {ospec.light_height}")
    elif re.search(r"划痕|凹坑|锈斑|针孔", reqs):
        recs.append("光源：建议低角度环形光（突出划痕/凹坑），颜色与被测物形成对比")
    elif re.search(r"反光|高亮|镜面|光面", reqs):
        recs.append("光源：建议同轴光或偏振光（抑制镜面反光）")
    else:
        recs.append("光源：根据目标选择环形/条形/同轴光，保证缺陷对比度")

    recs.append("工控机：算力满足图像处理/深度学习推理，预留 PCIe 扩展槽位")
    recs.append("控制器/采集卡：多相机带宽扩展，IO 输出用于剔除/报警联动")

    return recs