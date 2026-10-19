"""
需求解析 Agent：把用户输入的需求文本拆解成结构化任务计划 TaskPlan。

输出包含：
  - 项目名 / 客户 / 产品名 / 产品尺寸 / 检测要求
  - 设备清单（光源/镜头/相机/...）
  - 检测精度/速度/工作距/视场
  - 光路机位参数（相机位置、光源位置、产品形状）——DeepSeek 理解、关键词兜底
"""
from __future__ import annotations

import re

from ..models import Chapter, DevicePick, DiagramNode, DiagramSpec, TaskPlan
from .base import BaseAgent

# 设备类型关键词（用于从需求文本里识别需要哪些设备）
DEVICE_KEYWORDS: dict[str, list[str]] = {
    "light_source": ["光源", "照明", "打光", "同轴光", "环形光", "背光", "条形光", "穹顶光", "light"],
    "lens": ["镜头", "远心", "焦距", "lens"],
    "camera": ["相机", "工业相机", "ccd", "cmos", "面阵", "线阵", "camera"],
    "controller": ["控制器", "采集卡", "controller"],
    "ipc": ["工控机", "主机", "视觉主机", "工业电脑", "计算机", "ipc"],
    "output": ["plc", "机器人", "显示器", "执行", "剔除", "分拣", "报警", "机械手"],
    "accessory": ["编码器", "传感器", "支架", "光源控制器", "滤镜", "偏振片"],
}


class RequirementAgent(BaseAgent):
    name = "需求解析Agent"

    def run(self, text: str, case_ref: list[dict] | None = None) -> TaskPlan:
        """解析需求：优先用大模型，失败回退离线解析；再做工位架构图推理（能力自检）。"""
        self.log("解析需求，拆解任务…")
        if not self.llm.is_mock:
            plan = self._run_llm(text)
            if plan is not None:
                self.log("已用大模型解析需求")
            else:
                self.log("大模型输出不可用，回退离线解析")
                plan = self._run_mock(text)
        else:
            plan = self._run_mock(text)
        return self._attach_station_layout(plan, text, case_ref)

    def _attach_station_layout(self, plan: TaskPlan, text: str,
                               case_ref: list[dict] | None = None) -> TaskPlan:
        """让大模型自主推理相机/光源布局，生成坐标式 2D 工位架构图；失败则自检报告 + 备选模型。"""
        from types import SimpleNamespace
        from ..models import DiagramSpec
        from ..station import ALTERNATIVE_MODELS, reason_station_layout

        if case_ref is None and self.kb is not None:
            try:
                from ..selection import recall_cases
                case_ref = recall_cases(SimpleNamespace(kb=self.kb), text, top_k=3)
            except Exception:
                case_ref = []
        parts: list[str] = []
        for c in (case_ref or [])[:3]:
            src = str(c.get("source", ""))
            full = ""
            if self.kb is not None:
                full = "\n\n".join(ch.text for ch in self.kb.chunks.get("proposals", [])
                                     if ch.source == src)
            body = full or str(c.get("text", ""))
            parts.append(f"参考案例（{src}）：\n{body[:4000]}")
        case_text = "\n\n".join(parts)

        # 提取命中案例的结构化关键参数，作为撰写/校验硬约束
        try:
            from ..constraints import extract_case_constraints
            plan.case_constraints = extract_case_constraints(case_text, plan, text).to_dict()
        except Exception as e:
            self.log(f"案例约束提取失败：{e}")
            plan.case_constraints = {}

        # 检索历史工位图作为布局参考（高置信命中才注入；否则纯 LLM 推理）
        station_ref = ""
        station_hit = None
        hit_light_specs: list[dict] = []
        hit_camera_wd = ""
        note_fov = ""
        note_acc = ""
        note_cam = ""
        note_lens = ""
        note_lights = ""
        if self.station_lib is not None:
            try:
                hits = self.station_lib.search(text, top_k=1)
                if hits and hits[0]["score"] >= 0.55:
                    h = hits[0]
                    data = h.get("data") or {}
                    note_text = data.get("note", "") or ""
                    note_fov, note_acc = self._station_note_metrics(note_text)
                    note_cam, note_lens, note_lights = self._station_note_devices(note_text)
                    comps = "；".join(
                        f"{c.get('name', '')}({c.get('position', '')})"
                        for c in data.get("component_list", []) if c.get("name"))
                    conns = "；".join(
                        f"{c.get('source', '')}→{c.get('target', '')}({c.get('line_style', '')},{c.get('label', '')})"
                        for c in data.get("connection_list", []) if c.get("source"))
                    lights = "；".join(
                        " ".join(filter(None, [
                            str(s.get("name", "")),
                            ("角度" + str(s.get("angle"))) if s.get("angle") else "",
                            ("距工件" + str(s.get("distance_to_object"))) if s.get("distance_to_object") else "",
                            ("方向" + str(s.get("direction"))) if s.get("direction") else "",
                            ("可调" if s.get("adjustable") else ""),
                        ]))
                        for s in (data.get("light_spec_list") or []))
                    hit_camera_wd = str(data.get("camera_working_distance") or "").strip()
                    station_ref = (
                        f"{h.get('id', '')}｜{data.get('drawing_type', '')}｜"
                        f"相机工作距离：{hit_camera_wd or '未标注'}｜部件：{comps}｜连线：{conns}｜"
                        f"光源规格：{lights or '未标注'}｜备注：{(data.get('note', '') or '')[:500]}"
                    )
                    hit_light_specs = data.get("light_spec_list") or []
                    station_hit = {
                        "id": h.get("id", ""),
                        "project": h.get("project", ""),
                        "drawing_type": data.get("drawing_type", ""),
                        "score": round(h["score"], 4),
                        "camera_working_distance": hit_camera_wd,
                        "light_specs": hit_light_specs,
                    }
                    self.log(f"命中历史工位图：{h.get('id', '')}（{h['score']:.3f}）")
            except Exception:
                station_hit = None
                station_ref = ""

        if hit_light_specs:
            plan.case_constraints = dict(plan.case_constraints or {})
            plan.case_constraints["light_specs"] = hit_light_specs
        if hit_camera_wd:
            plan.case_constraints = dict(plan.case_constraints or {})
            plan.case_constraints["working_distance"] = hit_camera_wd
            plan.key_metrics["工作距"] = hit_camera_wd
        if note_fov:
            plan.case_constraints = dict(plan.case_constraints or {})
            plan.case_constraints["fov"] = note_fov
            plan.key_metrics["视场"] = note_fov
        if note_acc:
            plan.case_constraints = dict(plan.case_constraints or {})
            plan.case_constraints["accuracy"] = note_acc
            plan.key_metrics["精度"] = note_acc
        if note_cam:
            plan.case_constraints = dict(plan.case_constraints or {})
            plan.case_constraints["camera_model"] = note_cam
        if note_lens:
            plan.case_constraints = dict(plan.case_constraints or {})
            plan.case_constraints["lens"] = note_lens
        if note_lights:
            plan.case_constraints = dict(plan.case_constraints or {})
            plan.case_constraints["light_type"] = note_lights
        if plan.case_constraints.get("product_size"):
            plan.product_size = plan.case_constraints["product_size"]

        spec, ok, reason = reason_station_layout(text, self.llm, case_text, station_ref)
        # LLM 没写光源角度/距离时，用命中案例的明确标注兜底（按光源类型匹配）
        if ok and spec is not None and hit_light_specs:
            units = list(getattr(spec, "stations", []) or [spec])
            for unit in units:
                for lt in getattr(unit, "lights", []) or []:
                    if lt.distance and lt.angle_label:
                        continue
                    kind = str(getattr(lt, "kind", "") or "")
                    label = str(getattr(lt, "label", "") or "")
                    candidates = [
                        x for x in hit_light_specs
                        if (x.get("type") and x["type"] in kind)
                        or (x.get("name") and (x["name"] in label or label in x["name"]))
                    ]
                    chosen = candidates[0] if candidates else (hit_light_specs[0] if len(hit_light_specs) == 1 else None)
                    if chosen:
                        if not lt.distance:
                            lt.distance = str(chosen.get("distance_to_object", "") or "")
                        hist_angle = str(chosen.get("angle", "") or "")
                        if hist_angle and (
                                not lt.angle_label
                                or ("±" in hist_angle and "±" not in lt.angle_label)
                                or ("-" in hist_angle and "-" not in lt.angle_label)):
                            lt.angle_label = hist_angle
                        if not lt.direction:
                            lt.direction = str(chosen.get("direction", "") or "")
        if ok and spec is not None:
            # 推理成功：用工位架构图替换光路示意图（光路图仅作 Mock/失败兜底）
            plan.diagrams = [d for d in plan.diagrams if d.kind != "optic"]
            plan.diagrams.insert(0, DiagramSpec(
                id="station-1", kind="station", title="2D工位架构与光路图",
                station_spec=spec, description="大模型推理的工位布局（非模板化）"))
            # 把模型推理出的工件形状/名称/尺寸同步给产品图
            for d in plan.diagrams:
                if d.kind == "workpiece":
                    d.meta["shape"] = spec.workpiece_shape
                    d.meta["name"] = spec.workpiece_label
                    if spec.workpiece_size:
                        d.meta["size"] = spec.workpiece_size
            plan.layout_reasoning = {"status": "success", "reason": "", "alternatives": [],
                                       "station_hit": station_hit}
            n_st = len(spec.stations) if spec.stations else 1
            n_light = sum(len(st.lights) for st in spec.stations) if spec.stations else len(spec.lights)
            self.log(f"工位布局推理成功：{n_st} 个工位 / {spec.camera_count} 相机 / {n_light} 光源")
        else:
            plan.layout_reasoning = {
                "status": "mock" if self.llm.is_mock else "failed",
                "reason": reason,
                "alternatives": ALTERNATIVE_MODELS,
                "station_hit": station_hit,
            }
            if not self.llm.is_mock:
                self.log(f"工位布局推理失败：{reason}（已记录备选模型）")
        return plan

    # ---------------- 离线解析 ----------------
    def _run_mock(self, text: str) -> TaskPlan:
        """离线（关键词）解析，不调用大模型。"""
        devices = self._ensure_core_devices(self._detect_devices(text))
        meta = self._extract_meta(text)
        metrics = self._metrics(text)
        return TaskPlan(
            project_name=self._project_name(text),
            requirement_summary=self._summary(text),
            detection_target=self._detection_target(text),
            key_metrics=metrics,
            devices=devices,
            chapters=self._build_chapters(text, metrics, devices),
            diagrams=self._build_diagrams(devices, text, meta),
            customer_name=meta["customer_name"],
            product_name=meta["product_name"],
            product_size=meta["product_size"],
            requirements=meta["requirements"],
            tech_window=meta["tech_window"],
            checklist=self._extract_checklist(text, meta, devices),
        )

    # ---------------- 字段提取 ----------------
    @staticmethod
    def _extract_meta(text: str) -> dict:
        """提取客户名称/技术窗口/产品名称/产品尺寸/检测要求。"""
        m = re.search(r"客户(?:名称)?[：:]\s*([^\n/；;]+)", text)
        customer = m.group(1).strip() if m else ""
        m = re.search(r"技术窗口[：:]\s*([^\n/；;]+)", text)
        tech = m.group(1).strip() if m else ""
        m = re.search(r"产品名称[：:]\s*([^\n]+)", text)
        product = m.group(1).strip() if m else ""
        m = re.search(r"产品尺寸[：:]\s*([^\n]+)", text)
        size = m.group(1).strip() if m else ""
        reqs: list[str] = []
        m = re.search(r"检测要求[：:]?\s*(.+)", text, re.S)  # re.S 让 . 匹配换行，抓多条要求
        if m:
            reqs = [i.strip() for i in re.findall(r"\d+[.、]\s*([^\n；;]+)", m.group(1)) if i.strip()]
        return {"customer_name": customer, "product_name": product,
                "product_size": size, "requirements": reqs, "tech_window": tech}

    def _extract_checklist(self, text: str, meta: dict, devices: list) -> "RequirementChecklist":
        """把零散需求归类成 7 类结构化清单（用于方案/PPT/图纸生成依据）。"""
        from ..models import RequirementChecklist

        # 1 项目场景：从检测内容推断
        scene = "表面缺陷检测"
        if re.search(r"尺寸|测量|公差", text):
            scene = "尺寸测量"
        elif re.search(r"定位|引导|对位", text):
            scene = "定位引导"

        # 3 缺陷类型：从检测要求里抽名词（划痕/凹坑/针孔/毛刺/异物…）
        defect_kw = ["划痕", "凹坑", "锈斑", "针孔", "气泡", "污点", "裂纹", "砂眼",
                     "毛刺", "缺口", "掉粉", "露箔", "异物", "崩边", "虚焊", "连锡", "错位", "缺失"]
        defects = [k for k in defect_kw if k in text]

        # 5 结构要求：从结构/安装/工位关键词抽句子
        structure = []
        for line in text.splitlines():
            if re.search(r"结构|安装|支架|工位|机构|载具|平台", line):
                structure.append(line.strip().lstrip("#").strip())

        # 6 光路要求：光路布局描述段落
        optic = ""
        m = re.search(r"光路布局描述[：:]?\s*(.+)", text, re.S)
        if m:
            optic = m.group(1).strip()[:200]

        # 7 交付要求：交付/验收/售后相关
        delivery = ""
        for line in text.splitlines():
            if re.search(r"交付|验收|售后|质保|培训|节拍|稼动", line):
                delivery += line.strip().lstrip("#").strip() + "；"

        ck = RequirementChecklist(
            scene=scene,
            detection_object=self._detection_target(text),
            defect_types=defects,
            device_requirements=[d.label for d in devices],
            structure_requirements=structure,
            optic_requirements=optic,
            delivery_requirements=delivery.strip("；"),
        )
        ck.check_missing()
        return ck

    @staticmethod
    def _project_name(text: str) -> str:
        """项目名：优先 # 标题，其次含“方案/项目”且不是“字段:值”的行。"""
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("#"):
                return s.lstrip("#").strip()[:40]
        for line in text.splitlines():
            s = line.strip()
            if any(k in s for k in ("方案", "项目")) and "：" not in s and ":" not in s:
                return s[:40]
        return "机器视觉解决方案"

    @staticmethod
    def _detection_target(text: str) -> str:
        """检测对象：优先“检测对象/产品名称”字段。"""
        m = re.search(r"检测对象[：:]\s*([^\n]+)", text)
        if m:
            return m.group(1).strip()[:60]
        m = re.search(r"产品名称[：:]\s*([^\n]+)", text)
        if m:
            return m.group(1).strip()[:60]
        for line in text.splitlines():
            if any(k in line for k in ("检测", "识别", "测量", "定位")):
                return line.strip().lstrip("#").strip()[:60]
        return "工件表面缺陷检测"

    @staticmethod
    def _metrics(text: str) -> dict:
        """提取关键指标：精度/速度/工作距/视场（值+单位）。"""
        m: dict = {}
        pairs = [
            ("精度", r"(?:检测精度|精度)[：:\s]*([0-9.]+(?:\s*±\s*[0-9.]+)?)\s*(mm/pixel|um|μm|微米|mm|毫米|px|像素)?"),
            ("速度", r"(?:生产节拍|节拍|速度|产能)[：:\s]*([0-9.]+)\s*(秒/件|秒/个|件/秒|个/秒|件/分钟|件/分|个/分钟|个/分|件/小时|ppm|fps|帧/秒)?"),
            ("工作距", r"(?:工作距离|工作距|WD)[：:\s]*([0-9.]+\s*(?:[~-]\s*[0-9.]+)?(?:\s*±\s*[0-9.]+)?)\s*(mm|毫米)?"),
            ("视场", r"(?:视场|视野)[：:\s]*([0-9.]+\s*(?:mm)?\s*[×xX*]\s*[0-9.]+(?:\s*mm)?)\s*(mm|毫米)?"),
        ]
        for key, pat in pairs:
            r = re.search(pat, text, re.I)
            if r:
                m[key] = f"{r.group(1)}{r.group(2) or ''}"
        return m

    def _detect_devices(self, text: str) -> list[DevicePick]:
        """按关键词识别设备类型；核心三件套默认补全。"""
        found: dict[str, str] = {}
        for dtype, kws in DEVICE_KEYWORDS.items():
            for kw in kws:
                if kw.lower() in text.lower():
                    found[dtype] = kw
                    break
        picks = []
        for dtype in ("light_source", "lens", "camera", "controller", "ipc", "output", "accessory"):
            if dtype in found:
                picks.append(DevicePick(device_type=dtype, label=self.cfg.device_label(dtype), spec_hint=""))
        return picks

    def _ensure_core_devices(self, devices: list[DevicePick]) -> list[DevicePick]:
        """视觉方案至少补齐相机/镜头/光源三类核心设备（不改变已有项）。"""
        types = {d.device_type for d in devices}
        if types & {"camera", "lens", "light_source"}:
            for core in ("camera", "lens", "light_source"):
                if core not in types:
                    devices.append(DevicePick(device_type=core, label=self.cfg.device_label(core),
                                              spec_hint=""))
                    types.add(core)
        return devices

    @staticmethod
    def _station_note_devices(note: str) -> tuple[str, str, str]:
        """从工位图 note 提取相机/镜头/光源描述，覆盖错误的历史文本案例设备。"""
        cam = re.search(r"相机[-：:]\s*([^；;\n]+)", note or "")
        lens = re.search(r"镜头[-：:]\s*([^；;\n]+)", note or "")
        lights = re.findall(r"光源[12][-：:]\s*([^；;\n]+)", note or "")
        return (cam.group(1).strip() if cam else "",
                lens.group(1).strip() if lens else "",
                "、".join(x.strip() for x in lights if x.strip()))

    @staticmethod
    def _station_note_metrics(note: str) -> tuple[str, str]:
        """从工位图 note 中提取视野/像素精度（如“视野-53*44mm；单像素精度-0.021mm/pixel”）。"""
        fov = re.search(r"视野[-：:]\s*([0-9.]+\s*[×xX*]\s*[0-9.]+\s*mm)", note or "")
        acc = re.search(r"单像素精度[-：:]\s*([0-9.]+\s*(?:mm/pixel|mm/px))", note or "", re.I)
        return (fov.group(1) if fov else "", acc.group(1) if acc else "")

    def _build_chapters(self, text: str = "", metrics: dict | None = None,
                        devices: list | None = None) -> list[Chapter]:
        """动态章节大纲：基础 8 章 + 校验/风险/参数附录。"""
        titles = [
            ("ch1", "项目概述"),
            ("ch2", "需求分析"),
            ("ch3", "总体方案设计"),
            ("ch4", "系统组成与光路布局"),
            ("ch5", "设备选型说明"),
            ("ch6", "系统软件与算法"),
            ("ch7", "安装调试与验收"),
            ("ch8", "服务与售后"),
            ("ch9", "检测效果与缺陷样张"),
            ("ch10", "验证数据与验收指标"),
            ("ch11", "风险与注意事项"),
        ]
        if devices:
            titles.append(("ch12", "设备参数汇总"))
        return [Chapter(id=i, title=t) for i, t in titles]

    # ---------------- 机位理解 ----------------
    def _refine_layout_llm(self, text: str, ospec):
        """让大模型理解检测机位与产品形状，覆盖关键词兜底。"""
        try:
            sys = ("你是机器视觉检测机位分析助手，只输出 JSON："
                   "{camera_position: 上方|右上方|左上方, light_position: 左侧|右侧|两侧|同轴, "
                   "workpiece_shape: 矩形|环形|圆形}")
            data = self.llm.complete_json(sys, f"项目需求：\n{text}")
            if data.get("camera_position") in ("上方", "右上方", "左上方"):
                ospec.camera_position = data["camera_position"]
            if data.get("light_position") in ("左侧", "右侧", "两侧", "同轴"):
                ospec.light_position = data["light_position"]
            if data.get("workpiece_shape") in ("矩形", "环形", "圆形"):
                ospec.workpiece_shape = data["workpiece_shape"]
        except Exception:
            pass
        return ospec

    @staticmethod
    def _has_optic_layout(text: str) -> bool:
        """判断需求里是否描述了光路布局（有光路相关词 + mm 数值）。"""
        return bool(re.search(r"(光路|打光|布局|竖直|俯视|成像光路|检测物|基准平面)", text)) \
            and bool(re.search(r"\d+\s*mm", text))

    def _build_diagrams(self, devices: list[DevicePick], text: str = "", meta: dict | None = None) -> list[DiagramSpec]:
        """构建要生成的图：光路图（主）+ 产品图 + 检测图。"""
        meta = meta or {}
        diagrams: list[DiagramSpec] = []
        # 1) 光路布局示意图（由需求文本中的光路参数 + 机位理解绘制）
        if self._has_optic_layout(text):
            from ..optic import extract_optic_layout
            ospec = extract_optic_layout(text)
            if not self.llm.is_mock:
                ospec = self._refine_layout_llm(text, ospec)
            diagrams.append(DiagramSpec(
                id="optic-1", kind="optic", title="光路布局示意图",
                optic_spec=ospec, description="由需求文本提取的光路布局参数绘制",
            ))
        # 2) 产品/工件示意图（客户未提供产品信息则不生成，PPT 第4页留白）
        if meta.get("product_name") or meta.get("product_size"):
            diagrams.append(DiagramSpec(
                id="workpiece-1", kind="workpiece", title="产品示意图",
                meta={"name": meta.get("product_name") or self._detection_target(text),
                      "size": meta.get("product_size", "")},
            ))
        # 3) 检测示意图（俯视图）
        diagrams.append(DiagramSpec(
            id="detection-1", kind="detection", title="检测示意图",
            meta={"object": self._detection_target(text),
                  "fov": self._metrics(text).get("视场", ""),
                  "regions": meta.get("requirements", [])},
        ))
        return diagrams

    @staticmethod
    def _summary(text: str) -> str:
        """需求摘要：取前 4 行。"""
        lines = [l.strip().lstrip("#").strip() for l in text.splitlines() if l.strip()]
        return "；".join(lines[:4])[:200] or text.strip()[:200]

    # ---------------- 真实 LLM（模型全权理解需求，去硬编码） ----------------
    def _run_llm(self, text: str) -> TaskPlan | None:
        """一次调用让大模型输出完整结构化需求 JSON，构建 TaskPlan。"""
        sys = (
            "你是机器视觉方案需求解析专家。仔细阅读客户需求，输出一个 JSON（只输出 JSON，不要任何解释）：\n"
            "字段说明：\n"
            "- project_name: 项目名\n"
            "- customer_name: 客户名称\n"
            "- product_name: 产品名称\n"
            "- product_size: 产品尺寸（没有则空字符串）\n"
            "- detection_target: 检测对象\n"
            "- requirements: 检测要求，字符串数组\n"
            "- key_metrics: 对象 {精度, 速度, 工作距, 视场}，没有的字段填空字符串\n"
            "- devices: 数组 [{device_type, label, spec_hint}]，device_type 只能取 light_source/lens/camera/controller/ipc/output/accessory；只列出需求中明确提到的设备，不要臆造未提到的设备\n"
            "- selection_advice: 选型建议，字符串数组，至少覆盖工业相机/镜头/光源/工控机/控制器五类\n"
            "- checklist: 对象 {scene(项目场景), detection_object(检测对象), defect_types(缺陷类型字符串数组), "
            "device_requirements(设备要求字符串数组), structure_requirements(结构要求字符串数组), "
            "optic_requirements(光路要求), delivery_requirements(交付要求)}"
        )
        data = self.llm.complete_json(sys, f"客户需求：\n{text}")
        if not data or not data.get("project_name"):
            return None
        try:
            from ..models import RequirementChecklist
            devices = self._ensure_core_devices([DevicePick(**d) for d in data.get("devices", [])])
            ck_data = data.get("checklist", {}) or {}
            ck = RequirementChecklist(
                scene=ck_data.get("scene", ""),
                detection_object=ck_data.get("detection_object", ""),
                defect_types=ck_data.get("defect_types", []),
                device_requirements=ck_data.get("device_requirements", []),
                structure_requirements=ck_data.get("structure_requirements", []),
                optic_requirements=ck_data.get("optic_requirements", ""),
                delivery_requirements=ck_data.get("delivery_requirements", ""),
            )
            ck.check_missing()
            meta = {
                "customer_name": data.get("customer_name", ""),
                "product_name": data.get("product_name", ""),
                "product_size": data.get("product_size", ""),
                "requirements": data.get("requirements", []),
                "tech_window": "",
            }
            metrics = data.get("key_metrics", {}) or {}
            return TaskPlan(
                project_name=data.get("project_name", ""),
                requirement_summary=self._summary(text),
                detection_target=data.get("detection_target", ""),
                key_metrics=metrics,
                devices=devices,
                chapters=self._build_chapters(text, metrics, devices),
                diagrams=self._build_diagrams(devices, text, meta),
                customer_name=meta["customer_name"],
                product_name=meta["product_name"],
                product_size=meta["product_size"],
                requirements=meta["requirements"],
                tech_window="",
                checklist=ck,
                selection_advice=data.get("selection_advice", []),
            )
        except Exception as e:
            self.log(f"LLM 输出解析失败：{e}")
            return None
