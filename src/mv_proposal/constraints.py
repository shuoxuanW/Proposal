"""案例约束提取与覆盖率校验。

目标：
- 从命中案例中提取结构化关键参数，作为撰写/校验的硬约束；
- 检查最终正文是否覆盖这些参数；
- 检查设备类型与光路类型是否偏离案例。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .models import Chapter, Issue, TaskPlan

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _first(pattern: str, text: str, flags: int = 0) -> str:
    m = re.search(pattern, text or "", flags)
    return (m.group(1) if m and m.lastindex else "").strip(" ：:，,；;") if m else ""


def _nums(text: str) -> list[str]:
    return _NUM_RE.findall(text or "")


_MODEL_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*[-_/][A-Za-z0-9\-_/]*\d[A-Za-z0-9\-_/]*")


def _modelish(value: str) -> str:
    """只保留像型号的字符串，过滤“CST 工业相机，竖直安装”这类描述。"""
    s = str(value or "").strip()
    return s if s and _MODEL_RE.search(s) else ""


@dataclass
class CaseConstraints:
    product: str = ""
    product_size: str = ""
    material: str = ""
    detection_target: str = ""
    accuracy: str = ""
    cycle_time: str = ""
    fov: str = ""
    working_distance: str = ""
    camera_count: int = 0
    camera_model: str = ""
    lens: str = ""
    light_type: str = ""
    controller: str = ""
    ipc: str = ""
    station_count: int = 0
    source: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def prompt_text(self) -> str:
        rows = [
            ("产品", self.product), ("产品尺寸", self.product_size), ("材质", self.material),
            ("检测目标", self.detection_target), ("精度", self.accuracy), ("节拍", self.cycle_time),
            ("视场", self.fov), ("工作距离", self.working_distance),
            ("相机数量", str(self.camera_count) if self.camera_count else ""),
            ("相机型号", self.camera_model), ("镜头", self.lens), ("光源", self.light_type),
            ("控制器", self.controller), ("工控机", self.ipc),
            ("工位数", str(self.station_count) if self.station_count else ""),
        ]
        return "\n".join(f"- {k}：{v}" for k, v in rows if v)


def _from_plan(plan: TaskPlan) -> dict:
    m = plan.key_metrics or {}
    out = {
        "product": plan.product_name or "",
        "product_size": plan.product_size or "",
        "detection_target": plan.detection_target or "",
        "accuracy": str(m.get("精度") or m.get("accuracy") or ""),
        "cycle_time": str(m.get("速度") or m.get("节拍") or m.get("cycle") or ""),
        "fov": str(m.get("视场") or m.get("fov") or ""),
        "working_distance": str(m.get("工作距") or m.get("工作距离") or m.get("wd") or ""),
    }
    # 设备：只使用具体型号/参数，不用“工业相机/镜头”这类泛称占位
    for d in plan.devices:
        hint = (d.spec_hint or "").strip()
        if d.device_type == "camera":
            out["camera_count"] = max(int(out.get("camera_count") or 0), d.quantity)
            if hint and _modelish(hint):
                out["camera_model"] = out.get("camera_model") or hint
        elif d.device_type == "lens":
            if hint and _modelish(hint):
                out["lens"] = out.get("lens") or hint
        elif d.device_type == "light_source":
            if hint:
                out["light_type"] = out.get("light_type") or hint
        elif d.device_type == "controller":
            if hint and _modelish(hint):
                out["controller"] = out.get("controller") or hint
        elif d.device_type == "ipc":
            if hint and _modelish(hint):
                out["ipc"] = out.get("ipc") or hint
    wd = str(out.get("working_distance") or "")
    if wd and ("光源" in wd or "物料" in wd or "被测物" in wd) and "相机" not in wd:
        out["working_distance"] = ""
    # 工位
    for d in plan.diagrams:
        ss = getattr(d, "station_spec", None)
        if ss is not None:
            sts = getattr(ss, "stations", []) or []
            if sts:
                out["station_count"] = len(sts)
            else:
                out["station_count"] = 1 if getattr(ss, "cameras", None) else 0
            break
    return out


def extract_case_constraints(case_text: str, plan: TaskPlan, requirement_text: str = "") -> CaseConstraints:
    """从命中案例文本 + 当前需求 + plan 中提取关键约束。"""
    text = case_text or ""
    base = _from_plan(plan)
    blob = text + "\n" + (plan.requirement_summary or "") + "\n" + requirement_text

    def pick(key: str, *patterns: str) -> str:
        if base.get(key):
            return str(base[key])
        for p in patterns:
            v = _first(p, blob, re.S)
            if v:
                return v
        return ""

    product = pick("product", r"产品名称[：:]\s*([^\n；;]+)", r"产品[：:]\s*([^\n；;]+)")
    size = pick("product_size", r"产品尺寸[：:]\s*([^\n；;]+)", r"尺寸[：:]\s*([^\n；;]+)",
                r"尺寸\s*([0-9.]+\s*[×xX*]\s*[0-9.]+\s*mm)",
                r"(MAX\s*[\d×xX*.\s]+mm)")
    # 当前需求里的明确尺寸优先于历史案例/LLM 的尺寸（避免把新案例尺寸写错）
    req_size = _first(r"尺寸\s*([0-9.]+\s*[×xX*]\s*[0-9.]+\s*mm)", plan.requirement_summary or "")
    if req_size:
        size = req_size
    material = _first(r"材质[：:]\s*([^\n；;]+)", blob) or (
        next((k for k in ("金属", "塑料", "玻璃", "陶瓷", "PCB", "FPC", "硅胶", "橡胶") if k in blob), ""))
    target = pick("detection_target", r"检测项[：:]\s*([^\n]+)", r"检测目标[：:]\s*([^\n]+)",
                  r"检测要求[：:]\s*([^\n]+)")
    if not target or len(target) > 40 or "完整需求" in target:
        m = re.search(r"检测([^；;，,\n]{2,20})", plan.requirement_summary or "")
        if m:
            target = m.group(1).strip()
    accuracy = pick("accuracy", r"(?:检测精度|精度|分辨率)[：:]\s*([^\n；;]+)",
                    r"(±\s*\d+(?:\.\d+)?\s*mm)", r"(\d+(?:\.\d+)?\s*mm/pixel)")
    cycle = pick("cycle_time", r"(?:生产节拍|节拍|速度|产能)[：:\s]*([^\n；;，,]+)",
                 r"(\d+(?:\.\d+)?\s*(?:秒|s|件/分钟|件/小时|个/秒))")
    fov = pick("fov", r"(?:视野|视场)[：:]\s*([^\n；;]+)", r"(\d+(?:\.\d+)?\s*[×xX*]\s*\d+(?:\.\d+)?\s*mm)")
    # 优先使用明确写出的“相机工作距离”，避免把光源到物料距离误当相机 WD
    explicit_camera_wd = _first(
        r"(?:相机工作距离|相机工作距)[：:\s]*(\d+(?:\.\d+)?\s*(?:[~-]\s*\d+(?:\.\d+)?)?(?:\s*±\s*\d+(?:\.\d+)?)?\s*(?:mm)?)",
        blob)
    if explicit_camera_wd:
        wd = explicit_camera_wd
    else:
        wd = pick("working_distance", r"(?:工作距离|工作距|WD)[：:]\s*([^\n；;]+)",
                  r"(\d+(?:\.\d+)?\s*±\s*\d+(?:\.\d+)?\s*mm)")
        if wd and ("光源" in wd or "物料" in wd or "被测物" in wd) and "相机" not in wd:
            wd = ""

    camera_model = _modelish(base.get("camera_model") or _first(r"(MV-[A-Z0-9-]+|OPT-[A-Z0-9-]+|CST-[A-Z0-9-]+|HK-[A-Z0-9_-]+)", blob))
    lens = _modelish(base.get("lens") or _first(r"((?:YDA|YD|C-K)[A-Z0-9-]+\s*(?:\d+mm)?)", blob) or _first(r"(\d+mm\s*(?:FA|远心|定焦))", blob))
    light = base.get("light_type") or _first(r"(?:光源|打光)[：:]\s*([^\n；;]+)", blob)
    if not light or len(light) <= 3 or light in ("光源", "打光", "工业光源"):
        light = next((k for k in ("圆顶光", "环形光", "条形光", "同轴光", "面光", "背光") if k in blob), "")
    if light.startswith("光源"):
        light = light[2:].strip(" ：:")
    for kind in ("圆顶", "环形", "条形", "同轴", "背光", "面光"):
        if kind in light:
            light = kind
            break
    controller = _modelish(base.get("controller") or _first(r"(?:控制器|采集卡)[：:]\s*([^\n；;]+)", blob))
    ipc = _modelish(base.get("ipc") or _first(r"(IPC-[A-Z0-9-]+)", blob))
    camera_count = int(base.get("camera_count") or 0)
    if not camera_count:
        m = re.search(r"(\d+)\s*台[^\n]{0,12}相机", blob)
        camera_count = int(m.group(1)) if m else 0

    station_count = int(base.get("station_count") or 0)
    if not station_count:
        idx = set(re.findall(r"工位\s*([0-9一二三四五六七八九十]+)", blob))
        station_count = len(idx) if idx else (1 if "单工位" in blob else 0)

    return CaseConstraints(
        product=product, product_size=size, material=material, detection_target=target,
        accuracy=accuracy, cycle_time=cycle, fov=fov, working_distance=wd,
        camera_count=camera_count, camera_model=camera_model, lens=lens, light_type=light,
        controller=controller, ipc=ipc, station_count=station_count,
        source="命中案例" if case_text else "需求文本",
    )


def _has_value(text: str, value: str) -> bool:
    if not value:
        return True
    nums = _nums(value)
    if nums:
        return all(n in text for n in nums)
    return value in text


def check_case_constraints(plan: TaskPlan, chapters: list[Chapter]) -> list[Issue]:
    """检查正文是否覆盖命中案例的关键参数，并给出覆盖率。"""
    raw = getattr(plan, "case_constraints", None) or {}
    if not raw or raw.get("source") != "命中案例":
        return []
    text = "\n".join(c.content for c in chapters)
    fields = [
        ("产品尺寸", raw.get("product_size", "")),
        ("检测精度", raw.get("accuracy", "")),
        ("生产节拍", raw.get("cycle_time", "")),
        ("视场", raw.get("fov", "")),
        ("相机工作距离", raw.get("working_distance", "")),
        ("相机型号", raw.get("camera_model", "")),
        ("镜头", raw.get("lens", "")),
        ("控制器", raw.get("controller", "")),
        ("工控机", raw.get("ipc", "")),
    ]
    light_specs = raw.get("light_specs", []) or []
    if light_specs:
        for spec in light_specs:
            if spec.get("type"):
                fields.append((f"光源类型（{spec['type']}）", spec["type"]))
            if spec.get("angle"):
                fields.append(("光源角度", spec["angle"]))
            if spec.get("distance_to_object"):
                fields.append(("光源到工件距离", spec["distance_to_object"]))
    else:
        fields.append(("光源类型", raw.get("light_type", "")))
    issues: list[Issue] = []
    total = 0
    hit = 0
    for label, value in fields:
        if not value:
            continue
        total += 1
        if _has_value(text, str(value)):
            hit += 1
        else:
            issues.append(Issue(code="PARAM_MISSING", severity="warning",
                                message=f"命中案例关键参数「{label}」未在正文中覆盖：{value}"))
    if raw.get("camera_count"):
        total += 1
        if "相机" in text:
            hit += 1
        else:
            issues.append(Issue(code="PARAM_MISSING", severity="warning",
                                message=f"命中案例要求 {raw['camera_count']} 台相机，正文未说明"))
    if raw.get("station_count"):
        total += 1
        if "工位" in text:
            hit += 1
        else:
            issues.append(Issue(code="PARAM_MISSING", severity="warning",
                                message=f"命中案例为 {raw['station_count']} 工位，正文未说明"))
    if total:
        score = round(hit * 100 / total, 1)
        issues.append(Issue(code="PARAM_COVERAGE", severity="info",
                            message=f"命中案例参数覆盖率：{hit}/{total} = {score}%"))
    # 设备类型一致性
    dev_types = {d.device_type for d in plan.devices}
    for typ, label, val in (("camera", "相机", raw.get("camera_model", "")),
                            ("lens", "镜头", raw.get("lens", "")),
                            ("light_source", "光源", raw.get("light_type", ""))):
        if val and typ not in dev_types:
            issues.append(Issue(code="DEVICE_MISMATCH", severity="warning",
                                message=f"命中案例包含{label}信息，但当前设备计划缺少 {typ}"))
    # 光路类型一致性（有结构化 light_specs 时以每条光源的类型为准）
    if not light_specs:
        light = str(raw.get("light_type", "") or "")
        for kind in ("圆顶", "环形", "条形", "同轴", "面光", "背光"):
            if kind in light and kind not in text:
                issues.append(Issue(code="OPTICAL_MISMATCH", severity="warning",
                                    message=f"命中案例使用「{kind}」光源，正文未体现该光路类型"))
                break
    return issues
