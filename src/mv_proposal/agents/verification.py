"""
校验审核 Agent：检查图文一致性、锚点解析、设备覆盖与图片完整性。

问题分 error（阻断）/ warning（提示）。passed = 无 error。
"""
from __future__ import annotations

import re

from ..constraints import check_case_constraints
from ..models import Chapter, DiagramArtifact, Issue, TaskPlan, VerifyReport
from .base import BaseAgent


class VerificationAgent(BaseAgent):
    name = "校验审核Agent"

    def run(self, plan: TaskPlan, chapters: list[Chapter], artifacts: list[DiagramArtifact]) -> VerifyReport:
        self.log("校验图文一致性…")
        issues: list[Issue] = []
        art_by_id = {a.spec_id: a for a in artifacts}          # 图 id -> 产物
        all_text = "\n".join(c.content for c in chapters)       # 全部正文拼起来
        node_map: dict[str, dict] = {}                          # "fig:node" -> 节点信息

        for a in artifacts:
            for n in a.nodes:
                key = f"{a.spec_id}:{n.id}"
                node_map[key] = {"label": n.label, "device_type": n.device_type,
                                 "image_rel": n.image_rel, "name": (n.image_meta or {}).get("name", "")}

        # 1) 正文里的图引用必须对应已生成的图
        for ch in chapters:
            for fig in ch.fig_refs:
                if fig not in art_by_id:
                    issues.append(Issue(code="FIG_MISSING", severity="error",
                                        message=f"章节「{ch.title}」引用了未生成的图纸 [[FIG:{fig}]]", anchor_id=fig))
        # 2) 正文里的设备引用必须对应图中节点
        for ch in chapters:
            for ref in ch.dev_refs:
                if ref not in node_map:
                    issues.append(Issue(code="DEV_UNRESOLVED", severity="error",
                                        message=f"章节「{ch.title}」引用了不存在的节点 [[DEV:{ref}]]", anchor_id=ref))
        # 3) 每张图都应被正文引用
        for aid, a in art_by_id.items():
            if not any(aid in c.fig_refs for c in chapters):
                issues.append(Issue(code="FIG_UNREFERENCED", severity="warning",
                                    message=f"图纸「{a.title}」未被正文引用", anchor_id=aid))
        # 4) 图中设备应在正文有说明
        for key, info in node_map.items():
            label_parts = [p for p in info["label"].replace("/", " ").split() if p]
            hit = any(p in all_text for p in label_parts) or info["name"] in all_text
            if not hit:
                issues.append(Issue(code="DEV_UNDESCRIBED", severity="warning",
                                    message=f"图中设备「{info['label']}」在正文中缺少说明", anchor_id=key))
        # 5) 图片完整性
        for key, info in node_map.items():
            if not info["image_rel"]:
                issues.append(Issue(code="IMAGE_MISSING", severity="warning",
                                    message=f"节点「{info['label']}」未检索到图片（使用占位框）", anchor_id=key))
        # 6) 核心设备覆盖（仅设备框架图）
        for a in artifacts:
            if a.kind != "framework":
                continue
            types = {n.device_type for n in a.nodes}
            for core in ("light_source", "lens", "camera"):
                if core not in types:
                    issues.append(Issue(code="CORE_DEVICE_MISSING", severity="error",
                                        message=f"框架图「{a.title}」缺少核心设备 {self.cfg.device_label(core)}",
                                        anchor_id=a.spec_id))

        # 7) 光路图参数与正文一致性（图文联动核心校验：49mm/20mm/角度必须出现在正文）
        for spec in plan.diagrams:
            if spec.kind == "optic" and getattr(spec, "optic_spec", None) is not None:
                ospec = spec.optic_spec
                for label, val in (("镜头-检测物距离", ospec.lens_to_object),
                                   ("光源底部高度", ospec.light_height)):
                    num = re.sub(r"[^0-9.]", "", val)
                    if num and num not in all_text:
                        issues.append(Issue(code="OPTIC_PARAM_MISSING", severity="warning",
                                            message=f"光路参数「{label}={val}」未在正文中说明", anchor_id=spec.id))
                if f"{int(ospec.tilt_min)}°" not in all_text:
                    issues.append(Issue(code="OPTIC_ANGLE_MISSING", severity="warning",
                                        message=f"光路参数「光源角度 {int(ospec.tilt_min)}°~{int(ospec.tilt_max)}°」未在正文中说明",
                                        anchor_id=spec.id))

        # 8) 动态章节完整度
        titles = [c.title for c in chapters]
        for required in ("项目概述", "需求分析", "总体方案设计", "设备选型说明",
                         "系统软件与算法", "安装调试与验收", "服务与售后",
                         "风险与注意事项", "验证数据与验收指标"):
            if not any(required in t for t in titles):
                issues.append(Issue(code="SECTION_MISSING", severity="warning",
                                    message=f"方案书缺少建议章节「{required}」"))

        # 9) 命中案例参数/设备/光路覆盖率
        issues.extend(check_case_constraints(plan, chapters))

        # 10) 光源朝向检查：侧光源不能朝工件外侧
        for spec in plan.diagrams:
            ss = getattr(spec, "station_spec", None)
            if ss is None:
                continue
            for unit in getattr(ss, "stations", []) or []:
                for lt in getattr(unit, "lights", []) or []:
                    d = str(getattr(lt, "direction", "") or "").lower()
                    x = float(getattr(lt, "x", 0.0))
                    if x < 0 and "left" in d:
                        issues.append(Issue(code="LIGHT_DIRECTION", severity="warning",
                                            message=f"光源「{lt.label}」位于工件左侧，但朝向左侧（应朝右/朝工件）"))
                    elif x > 0 and "right" in d:
                        issues.append(Issue(code="LIGHT_DIRECTION", severity="warning",
                                            message=f"光源「{lt.label}」位于工件右侧，但朝向右侧（应朝左/朝工件）"))

        errors = [i for i in issues if i.severity == "error"]
        return VerifyReport(passed=not errors, issues=issues)