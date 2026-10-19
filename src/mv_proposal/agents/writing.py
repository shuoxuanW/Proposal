"""
方案撰写 Agent：基于需求拆解 + 知识库素材，撰写方案正文并标记图纸点位。

正文里用 [[FIG:图id]] 标记要插入的图；写完后再做两件事：
  1. 剥掉大模型可能幻觉出来的 [[DEV:...]] 设备节点引用；
  2. 兜底补上未被引用的图（产品图→项目概述、检测/光路图→光路布局章）。
"""
from __future__ import annotations

import re

from ..anchors import extract_dev_refs, extract_fig_refs
from ..models import Chapter, TaskPlan
from .base import BaseAgent


class WritingAgent(BaseAgent):
    name = "方案撰写Agent"

    def run(self, plan: TaskPlan) -> list[Chapter]:
        """逐章撰写正文，提取锚点引用，最后做引用兜底。"""
        self.log(f"撰写方案正文（{len(plan.chapters)} 个章节）…")
        out: list[Chapter] = []
        for ch in plan.chapters:
            content = self._compose(plan, ch)
            # 剥掉大模型可能幻觉出来的设备节点引用（当前图没有设备节点）
            content = re.sub(r"\[\[DEV:[^\]]*\]\]", "", content)
            out.append(Chapter(
                id=ch.id, title=ch.title, content=content,
                fig_refs=extract_fig_refs(content),
                dev_refs=extract_dev_refs(content),
            ))
        out = self._ensure_device_summary(plan, out)
        return self._ensure_fig_refs(plan, out)

    def _ensure_fig_refs(self, plan: TaskPlan, chapters: list[Chapter]) -> list[Chapter]:
        """兜底：保证每张图都在正文被引用，避免校验报 FIG_UNREFERENCED。"""
        refs: set[str] = set()
        for ch in chapters:
            refs.update(ch.fig_refs)
        for spec in plan.diagrams:
            if spec.id in refs:
                continue
            # 产品图放项目概述，检测/光路图放光路布局章
            target = next((c for c in chapters if c.id == ("ch1" if spec.kind == "workpiece" else "ch4")), None)
            if target is None and chapters:
                target = chapters[0]
            if target is not None:
                target.content = target.content.rstrip() + f"\n\n[[FIG:{spec.id}]]\n"
                target.fig_refs.append(spec.id)
                refs.add(spec.id)
        return chapters

    # ---------------- 内容编排 ----------------
    def _compose(self, plan: TaskPlan, ch: Chapter) -> str:
        """单章正文：mock 用模板，真实模型用 LLM + 知识库素材。"""
        if self.llm.is_mock:
            return self._compose_mock(plan, ch)
        # 真实模型：带素材检索的正文生成
        sys = (
            "你是机器视觉方案工程师，撰写方案书章节正文（Markdown）。\n"
            "规则：1) 按章节内容在合适位置插入图纸占位符 [[FIG:图id]]，图id以用户提供的为准；\n"
            "2) 不要使用 [[DEV:...]] 之类的设备节点引用；\n"
            "3) 只输出正文本身，不要输出任何解释。"
        )
        kb_txt = self._kb_snippets(plan, ch)
        optic_hint = self._optic_hint(plan)
        case_txt = self._case_ref_text()
        constraints_txt = ""
        cc = getattr(plan, "case_constraints", None) or {}
        if cc:
            try:
                from ..constraints import CaseConstraints
                constraints_txt = ("命中案例关键参数（必须覆盖；确需替换时说明理由）：\n"
                                   + CaseConstraints(**cc).prompt_text())
            except Exception:
                constraints_txt = ""
        user = (
            f"项目：{plan.project_name}\n需求：{plan.requirement_summary}\n"
            f"设备：{[d.label for d in plan.devices]}\n"
            f"可用图 id（按章节内容插入 [[FIG:图id]]）：{[d.id for d in plan.diagrams]}\n"
            f"{optic_hint}\n"
            f"{constraints_txt}\n"
            f"{case_txt}\n"
            f"章节标题：{ch.title}\n知识库素材：\n{kb_txt}"
        )
        text = self.llm.complete(sys, user)
        return text.strip() if text.strip() else self._compose_mock(plan, ch)

    def _compose_mock(self, plan: TaskPlan, ch: Chapter) -> str:
        """离线模板正文（8 章固定骨架 + 需求字段填充）。"""
        # 设备清单（正文选型章节用）
        dev_lines = "\n".join(
            f"- **{d.label}**：{d.spec_hint or '选型依据见第5章'}" for d in plan.devices
        ) or "- 待选型"
        fig_id = plan.diagrams[0].id if plan.diagrams else "framework-1"
        node_refs = ""
        if plan.diagrams:
            node_refs = " ".join(f"[[DEV:{fig_id}:{n.id}]]" for n in plan.diagrams[0].nodes)

        # 8 章固定模板
        templates = {
            "ch1": (
                "## 项目概述\n\n"
                f"本项目为 **{plan.project_name}**，旨在通过机器视觉系统实现对"
                f"「{plan.detection_target}」的自动检测与判定。\n\n"
                f"需求要点：{plan.requirement_summary}\n\n"
                "系统采用工业相机采集图像，配合专用光源照明与高分辨率镜头成像，"
                "由视觉软件完成图像处理、特征提取与结果判定，并通过执行机构输出控制信号。"
            ),
            "ch2": (
                "## 需求分析\n\n"
                f"- 检测对象：{plan.detection_target}\n"
                f"- 关键指标：{self._metrics_str(plan.key_metrics)}\n"
                "- 运行方式：在线连续检测，自动判定 OK/NG\n\n"
                "根据需求，系统需满足成像稳定性、检测精度与节拍要求，并预留数据追溯接口。"
            ),
            "ch3": (
                "## 总体方案设计\n\n"
                "本方案采用「图像采集 → 图像处理 → 结果输出」三层架构：\n\n"
                f"{dev_lines}\n\n"
                "光源为工件提供稳定照明，镜头将目标成像到相机靶面，相机输出图像至控制器，"
                "由工控机运行视觉算法完成检测，最终将判定结果发送给执行输出单元。"
            ),
            "ch4": (
                "## 视觉系统框架与组成\n\n"
                "系统框架如下图所示，各设备按照光路与数据链路连接：\n\n"
                f"[[FIG:{fig_id}]]\n\n"
                f"图中设备：{node_refs}\n\n"
                "图像采集单元由光源、镜头、工业相机组成；图像处理单元由控制器与工控机构成；"
                "执行输出单元负责将检测结果下发至 PLC/机器人或显示器。"
            ),
            "ch5": (
                "## 设备选型说明\n\n"
                f"{dev_lines}\n\n"
                "选型原则：光源需保证缺陷对比度；镜头分辨率与靶面尺寸匹配；"
                "相机分辨率满足检测精度要求（按 3 倍以上像素覆盖计算）；"
                "控制器与工控机满足图像处理算力与接口需求。"
            ),
            "ch6": (
                "## 系统软件与算法\n\n"
                "- 图像采集与标定\n"
                "- 图像预处理（滤波、增强）\n"
                "- 特征提取与缺陷检测算法\n"
                "- 结果判定与统计分析\n\n"
                "软件支持配方管理、图像存储、MES/上位机通讯与数据追溯。"
            ),
            "ch7": (
                "## 安装调试与验收\n\n"
                "1. 机械安装与光路调整\n"
                "2. 相机标定与曝光参数优化\n"
                "3. 软件调试与算法验证\n"
                "4. 整线联调与验收测试\n\n"
                "验收标准以双方确认的技术协议为准。"
            ),
            "ch8": (
                "## 服务与售后\n\n"
                "- 质保期内免费维修\n"
                "- 7×24 小时技术支持\n"
                "- 备件供应与培训服务\n"
                "- 定期回访与系统升级"
            ),
            "ch9": (
                "## 检测效果与缺陷样张\n\n"
                f"- 检测对象：{plan.detection_target}\n"
                f"- 检测项：{'、'.join(plan.requirements) or '以技术协议为准'}\n"
                "- 成像方式：工业相机配合专用光源采集缺陷图像\n"
                "- 判定方式：算法输出 OK/NG，并保存缺陷图像与检测记录\n\n"
                "本页用于展示典型缺陷样张与检测效果，正式交付时可替换为客户实测图片。"
            ),
            "ch10": self._validation_section(plan),
            "ch11": self._risk_section(plan),
            "ch12": self._device_summary_section(plan),
        }
        # 产品图引用 → 项目概述章
        wp_id = self._fig_id(plan, "workpiece")
        if wp_id:
            templates["ch1"] = templates["ch1"] + f"\n\n待测产品示意图：\n\n[[FIG:{wp_id}]]\n"
        # 工位布局/光路：用布局规格写第4章
        lkind, lspec = self._layout_spec(plan)
        if lkind == "optic" and lspec is not None:
            templates["ch4"] = (
                "## 系统组成与光路布局\n\n"
                "系统光路布局如下图所示：\n\n"
                f"[[FIG:{fig_id}]]\n\n"
                f"- 相机：{lspec.camera_label}（{lspec.camera_note}），镜头垂直向下；\n"
                f"- 成像光路：竖直虚线对准下方{lspec.object_label}，镜头端面到检测物基准平面 {lspec.lens_to_object}；\n"
                f"- 光源：{lspec.light_color}{lspec.light_label}，正视图摆放，安装角度 {int(lspec.tilt_min)}°~{int(lspec.tilt_max)}° 可调，底部距基准平台 {lspec.light_height}。\n"
            )
        elif lkind == "station" and lspec is not None:
            cam_lines = "\n".join(f"- {c.label}：{'竖直俯视' if c.orientation == 'down' else '侧面拍摄'}" for c in lspec.cameras)
            light_lines = "\n".join(f"- {l.label}（{l.kind}）" for l in lspec.lights)
            n_st = len(lspec.stations) if getattr(lspec, "stations", None) else 1
            templates["ch4"] = (
                "## 系统组成与工位布局\n\n"
                f"本项目共 {n_st} 个检测工位。系统工位架构如下图所示：\n\n"
                f"[[FIG:{fig_id}]]\n\n"
                f"相机布置（{lspec.camera_count} 台）：\n{cam_lines}\n\n"
                f"光源布置：\n{light_lines}\n\n"
                + (f"{lspec.notes}\n" if lspec.notes else "")
            )
        # 检测图引用 → 光路布局章
        det_id = self._fig_id(plan, "detection")
        if det_id:
            templates["ch4"] = templates["ch4"] + f"\n\n检测俯视示意图：\n\n[[FIG:{det_id}]]\n"

        body = templates.get(ch.id, f"## {ch.title}\n\n详见方案正文。")
        # 参考素材只进入 LLM Prompt，不写进客户正文
        return body

    @staticmethod
    def _validation_section(plan: TaskPlan) -> str:
        metrics = plan.key_metrics or {}
        cc = getattr(plan, "case_constraints", None) or {}
        rows = []
        for label, key in (("检测精度", "精度"), ("生产节拍", "速度"), ("视场", "视场"), ("工作距离", "工作距")):
            if label == "工作距离":
                val = cc.get("working_distance") or metrics.get(key) or metrics.get(label)
            elif label in ("检测精度", "视场"):
                val = cc.get({"检测精度": "accuracy", "视场": "fov"}[label]) or metrics.get(key) or metrics.get(label)
            else:
                val = metrics.get(key) or metrics.get(label) or cc.get("cycle_time", "")
            if val:
                rows.append(f"| {label} | {val} | 按技术协议与实测样件验证 |")
        for spec in cc.get("light_specs", []) or []:
            if spec.get("distance_to_object"):
                rows.append(f"| 光源到工件距离 | {spec['distance_to_object']} | 按技术协议与实测样件验证 |")
            if spec.get("angle"):
                rows.append(f"| 光源角度 | {spec['angle']} | 按技术协议与实测样件验证 |")
        if not rows:
            rows = ["| 检测精度 | 以技术协议为准 | 标准样件重复检测 |"]
        return ("## 验证数据与验收指标\n\n"
                "| 指标 | 要求 | 验证方法 |\n|---|---|---|\n" + "\n".join(rows) +
                "\n\n验收以双方确认的技术协议、标准样件和连续运行测试结果为准。")

    @staticmethod
    def _risk_section(plan: TaskPlan) -> str:
        cc = getattr(plan, "case_constraints", None) or {}
        items = []
        if cc.get("light_type"):
            items.append(f"光源需按 {cc['light_type']} 方案验证，避免反光或阴影影响缺陷对比度。")
        if cc.get("working_distance"):
            items.append(f"安装时需保证工作距离 {cc['working_distance']}，并预留调焦与维护空间。")
        if cc.get("cycle_time"):
            items.append(f"节拍要求 {cc['cycle_time']}，需通过曝光、传输和算法耗时联调确认。")
        items += [
            "来料表面状态、油污或粉尘可能影响成像稳定性，建议增加遮光罩与定期清洁。",
            "正式验收前需使用客户真实样件进行算法阈值标定。",
            "如现场环境光较强，应增加遮光帘或局部暗室结构。",
        ]
        return "## 风险与注意事项\n\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(items, 1))

    @staticmethod
    def _device_table_markdown(plan: TaskPlan) -> str:
        cc = getattr(plan, "case_constraints", None) or {}
        model_map = {
            "camera": cc.get("camera_model", ""),
            "lens": cc.get("lens", ""),
            "light_source": cc.get("light_type", ""),
            "controller": cc.get("controller", ""),
            "ipc": cc.get("ipc", ""),
        }
        rows = ["| 设备 | 型号/建议 | 数量 |", "|---|---|---|"]
        for d in plan.devices:
            hint = model_map.get(d.device_type, "") or d.spec_hint or "建议选型/待确认"
            rows.append(f"| {d.label or d.device_type} | {hint} | {d.quantity} |")
        if len(rows) == 2:
            rows.append("| 待选型 | 以最终 BOM 为准 | - |")
        return "\n".join(rows)

    def _ensure_device_summary(self, plan: TaskPlan, chapters: list[Chapter]) -> list[Chapter]:
        """LLM 正文漏写案例型号时，在设备参数章节补齐关键型号。"""
        cc = getattr(plan, "case_constraints", None) or {}
        pairs = [
            ("相机型号", cc.get("camera_model", "")),
            ("镜头", cc.get("lens", "")),
            ("控制器", cc.get("controller", "")),
            ("工控机", cc.get("ipc", "")),
        ]
        if cc.get("working_distance"):
            pairs.append(("相机工作距离", cc["working_distance"]))
        for spec in cc.get("light_specs", []) or []:
            if spec.get("angle"):
                pairs.append(("光源角度", spec["angle"]))
            if spec.get("distance_to_object"):
                pairs.append(("光源到工件距离", spec["distance_to_object"]))
        pairs = [(k, v) for k, v in pairs if v]
        if not pairs:
            return chapters
        ch = next((c for c in chapters if c.id == "ch12" or "设备参数汇总" in c.title), None)
        if ch is None:
            return chapters
        missing = [(k, v) for k, v in pairs if str(v) not in ch.content]
        if missing:
            ch.content = ch.content.rstrip() + "\n\n关键设备型号：\n" + "\n".join(
                f"- {k}：{v}" for k, v in missing)
        return chapters

    def _device_summary_section(self, plan: TaskPlan) -> str:
        cc = getattr(plan, "case_constraints", None) or {}
        body = "## 设备参数汇总\n\n" + self._device_table_markdown(plan)
        extra = []
        if cc.get("station_count"):
            extra.append(f"- 工位数：{cc['station_count']}")
        if cc.get("working_distance"):
            extra.append(f"- 相机工作距离：{cc['working_distance']}")
        for spec in cc.get("light_specs", []) or []:
            if spec.get("angle"):
                extra.append(f"- 光源角度：{spec['angle']}")
            if spec.get("distance_to_object"):
                extra.append(f"- 光源到工件距离：{spec['distance_to_object']}")
        if extra:
            body += "\n\n" + "\n".join(extra)
        return body

    def _case_ref_text(self) -> str:
        """命中历史方案时，给大模型注入的参考（复用框架/设备参数，禁止复制原文与旧案例文字）。"""
        cases = getattr(self, "case_ref", []) or []
        if not cases:
            return ""
        lines = ["以下历史方案与本需求高度相似，可复用其框架结构、设备参数与光路布局；"
                 "但不要原样复制原文、不要带出旧客户名/旧型号/旧参数："]
        for c in cases:
            snippet = " ".join(c["text"].split("\n")[:8])
            lines.append("- " + snippet[:300])
        return "\n".join(lines)

    def _kb_snippets(self, plan: TaskPlan, ch: Chapter) -> str:
        """从方案范文库 + 设备参数库检索该章节相关素材。"""
        if not self.kb:
            return ""
        q = f"{ch.title} {plan.detection_target} {' '.join(d.label for d in plan.devices)}"
        hits = self.kb.retrieve_multi(["proposals", "devices"], q, top_k=3)
        return "\n\n".join(h["text"] for h in hits if h["score"] > 0.02)

    @staticmethod
    def _optic_hint(plan: TaskPlan) -> str:
        """给大模型的布局提示（第4章必须按此写）。兼容光路图与工位架构图。"""
        lkind, lspec = WritingAgent._layout_spec(plan)
        if lkind == "optic" and lspec is not None:
            return (f"\n光路布局参数（第4章必须按此写并插入 [[FIG:optic-1]]）："
                    f"相机 {lspec.camera_label}（{lspec.camera_note}），镜头垂直向下，光路对准{lspec.object_label}，"
                    f"镜头端面到检测物基准平面 {lspec.lens_to_object}；{lspec.light_color}{lspec.light_label} 正视图摆放，"
                    f"角度 {int(lspec.tilt_min)}°~{int(lspec.tilt_max)}° 可调，底部距基准平台 {lspec.light_height}。")
        if lkind == "station" and lspec is not None:
            cams = "；".join(f"{c.label}{'竖直俯视' if c.orientation == 'down' else '侧面拍摄'}" for c in lspec.cameras)
            lights = "；".join(l.label for l in lspec.lights)
            return (f"\n工位布局参数（第4章必须按此写并插入 [[FIG:station-1]]）："
                    f"{lspec.camera_count} 台相机：{cams}；光源：{lights}；{lspec.notes}")
        return ""

    @staticmethod
    def _layout_spec(plan: TaskPlan):
        """取第一个图的光路/工位布局规格，返回 (kind, spec)。"""
        if plan.diagrams:
            d = plan.diagrams[0]
            if d.kind == "optic":
                return ("optic", getattr(d, "optic_spec", None))
            if d.kind == "station":
                return ("station", getattr(d, "station_spec", None))
        return (None, None)

    @staticmethod
    def _fig_id(plan: TaskPlan, kind: str):
        """按图类型找图 id。"""
        for d in plan.diagrams:
            if d.kind == kind:
                return d.id
        return None

    @staticmethod
    def _metrics_str(m: dict) -> str:
        """把指标字典拼成一行文字。"""
        return "；".join(f"{k}:{v}" for k, v in m.items()) or "以技术协议为准"