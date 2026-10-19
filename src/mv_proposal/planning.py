"""
项目持续规划文档生成：每次生成方案时，额外输出一份可持续更新的规划文档。

结构固定两大模块：
  - 一、已完成事项（硬件 / 软件 / 智能体能力 / 知识库建设）
  - 二、后续待实施规划（迭代目标 / 待开发 / 待补知识库 / 待验证 / 风险与时间）
"""
from __future__ import annotations

from datetime import datetime


def generate_planning_doc(plan, report, image_count: int = 0) -> str:
    """生成 Markdown 格式的规划文档文本。"""
    ck = plan.checklist
    date = datetime.now().strftime("%Y.%m.%d")
    parts: list[str] = []

    # 标题
    parts.append("# 项目持续规划文档")
    parts.append("")
    parts.append(f"- 项目：{plan.project_name}")
    parts.append(f"- 更新时间：{date}")
    parts.append(f"- 需求完整度：{'完整' if not ck.missing else '缺失 ' + '、'.join(ck.missing)}")
    parts.append("")

    # ===== 一、已完成事项 =====
    parts.append("## 一、已完成事项")
    parts.append("")
    parts.append("### 1. 方案与图纸成果")
    parts.append(f"- 已完成《{plan.project_name}》成套方案文档与 PPT（9 页）")
    parts.append("- 已生成：光路布局示意图、产品示意图、检测俯视图、设备选型建议")
    parts.append("- 图文联动注册表 linkage.json（锚点 ↔ 图纸 ↔ 设备照片）")
    parts.append("")
    parts.append("### 2. 硬件与选型")
    parts.append(f"- 设备清单：{'、'.join(d.label for d in plan.devices) or '待定'}")
    parts.append(f"- 检测指标：{'；'.join(f'{k}:{v}' for k, v in plan.key_metrics.items()) or '待定'}")
    if ck.optic_requirements:
        parts.append(f"- 光路要求：{ck.optic_requirements[:120]}")
    parts.append("")
    parts.append("### 3. 软件与智能体能力")
    parts.append("- 5 个 Agent 已落地：需求解析 / 方案撰写 / 绘图 / 校验 / 汇总")
    parts.append("- 本地 BGE 中文向量 + SQLite 向量库 + BM25 混合检索")
    parts.append("- 光路图支持机位可变（相机上/右上/左上，光源左/右/两侧/同轴）+ 嵌入知识库真实设备照片")
    parts.append("")
    parts.append("### 4. 知识库建设")
    parts.append("- 文本知识库：方案范文库 / 图例规范库 / 设备参数库 3 集合")
    parts.append(f"- 图片库：{image_count} 张设备照片（光源/相机/镜头/工控机…）")
    parts.append("")

    # ===== 二、后续待实施规划 =====
    parts.append("## 二、后续待实施规划")
    parts.append("")
    parts.append("### 1. 下一阶段迭代目标")
    parts.append("- 多轮对话式需求收集（自动追问缺失字段）")
    parts.append("- 方案正文严格定制化，杜绝模板原文与旧案例残留")
    parts.append("- 绘图按硬件型号/工位结构/光路参数更精准匹配知识库图片")
    parts.append("")
    parts.append("### 2. 待开发功能")
    parts.append("- Web 前端：画布编辑、图文联动、人工修改回流")
    parts.append("- 可选：VLM 图文一致性校验、rerank 重排序")
    parts.append("")
    parts.append("### 3. 待补充知识库内容")
    parts.append(f"- 方案范文库：补充「{ck.scene or '本场景'}」相关完整范文")
    if ck.missing:
        parts.append(f"- 本项目的缺失需求字段：{'、'.join(ck.missing)}")
    parts.append("")
    parts.append("### 4. 待验证项目")
    parts.append("- 用真实客户项目跑通全流程，对比人工方案书质量")
    parts.append("- 验证光路图机位 / 产品形状 / 选型建议与实际情况的一致性")
    parts.append("")
    parts.append("### 5. 风险点与时间规划建议")
    parts.append("- 风险：知识库图片匹配不准、模板文字残留、光路机位覆盖不全")
    parts.append("- 建议：先补齐范文与设备参数，再逐类扩展机位；按 2 周一个迭代推进")
    parts.append("")

    return "\n".join(parts)