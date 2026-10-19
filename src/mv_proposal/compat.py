"""
硬件强制配套校验（会议纪要定版）：设备层内置工程强制绑定关系。

参数来源优先级：设备目录 data/device_catalog.json（权威）> 型号/描述后缀推断（兜底）。
推断不出的项标注「无法校验」，不编造参数。

规则：
  1. 镜头卡口必须与相机卡口一致（C口 / M42 / M72）
  2. 相机数据接口（GigE / USB3 / 10GigE）必须有对应采集能力（工控机网口数、采集卡）
  3. 光源总路数 ≤ 光源控制器通道数
  4. 镜头标称分辨率（MP）≥ 相机像素（MP）
  5. 每个相机需要匹配其接口的线缆（目录里有 cable 条目时才校验）
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DeviceItem:
    """选型清单里的一项硬件。device_type 对齐 framework 配置。"""
    device_type: str          # camera / lens / light_source / controller / ipc / cable / output
    model: str = ""
    desc: str = ""
    qty: int = 1


@dataclass
class CompatCheck:
    rule: str
    passed: bool | None       # True 通过 / False 不通过 / None 数据不足无法校验
    message: str


@dataclass
class CompatReport:
    checks: list[CompatCheck] = field(default_factory=list)

    @property
    def failed(self) -> list[CompatCheck]:
        return [c for c in self.checks if c.passed is False]

    @property
    def passed(self) -> bool:
        return not self.failed


# ---------------- 设备目录（权威参数来源） ----------------
CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "device_catalog.json"
_catalog_cache: dict[str, dict] | None = None


def load_catalog(path: Path | None = None) -> dict[str, dict]:
    """读取设备目录，返回 {型号: {字段..., "device_type": 类型}}。"""
    p = Path(path) if path else CATALOG_PATH
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for dtype, rows in raw.items():
        if dtype.startswith("_") or not isinstance(rows, list):
            continue
        for r in rows:
            if isinstance(r, dict) and (r.get("model") or "").strip():
                r2 = dict(r)
                r2["device_type"] = dtype
                out[str(r["model"]).strip()] = r2
    return out


def _catalog() -> dict[str, dict]:
    global _catalog_cache
    if _catalog_cache is None:
        _catalog_cache = load_catalog()
    return _catalog_cache


def _cat(model: str, key: str):
    return _catalog().get(model, {}).get(key)


# ---------------- 推断辅助（目录优先，后缀兜底） ----------------
def _infer_interface(model: str, desc: str) -> str | None:
    v = _cat(model, "接口")
    if v:
        return str(v)
    t = (model + " " + desc).upper()
    if "USB" in t or "10U" in model.upper():
        return "USB3"
    if "90T" in model.upper() or "10GIGE" in t:
        return "10GigE"
    if "10G" in model.upper() or "网口" in desc or "GIGE" in t:
        return "GigE"
    return None


def _infer_mount(model: str, desc: str) -> str | None:
    v = _cat(model, "卡口")
    if v:
        return str(v)
    if "M42" in desc.upper():
        return "M42"
    if "M72" in desc.upper():
        return "M72"
    if "C口" in desc or "C 口" in desc:
        return "C口"
    return None


def _infer_channels(model: str, desc: str) -> int | None:
    v = _cat(model, "通道数")
    if v:
        return int(v)
    t = model + desc
    if "六通道" in t or "6通道" in t or "-6" in model or "6T" in model:
        return 6
    if "四通道" in t or "4通道" in t or "4T" in model:
        return 4
    if "双通道" in t or "二通道" in t or "2通道" in t or "2T" in model:
        return 2
    return None


def _infer_lens_mp(model: str, desc: str) -> float | None:
    v = _cat(model, "标称MP")
    if v:
        return float(v)
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", desc)
    if m:
        return float(m.group(1)) / 100.0
    m = re.search(r"(\d+)M(?:P)?\b", model + " " + desc)
    if m:
        return float(m.group(1))
    return None


def _infer_camera_mp(model: str, desc: str) -> float | None:
    v = _cat(model, "像素万")
    if v:
        return float(v) / 100.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", desc)
    if m:
        return float(m.group(1)) / 100.0
    return None


def _infer_ipc_ports(model: str, desc: str) -> int | None:
    v = _cat(model, "网口数")
    if v:
        return int(v)
    m = re.search(r"(\d+)\s*网口", desc)
    if m:
        return int(m.group(1))
    if "双网口" in desc or "二网口" in desc:
        return 2
    if "三网口" in desc:
        return 3
    if "四网口" in desc:
        return 4
    return None


# ---------------- 校验主体 ----------------
def check_compat(items: list[DeviceItem]) -> CompatReport:
    rep = CompatReport()
    by_type: dict[str, list[DeviceItem]] = {}
    for it in items:
        by_type.setdefault(it.device_type, []).append(it)
    cams = by_type.get("camera", [])
    lenses = by_type.get("lens", [])
    lights = by_type.get("light_source", [])
    ctrls = by_type.get("controller", [])
    ipcs = by_type.get("ipc", [])
    cables = by_type.get("cable", [])

    # 1) 镜头卡口 ↔ 相机卡口
    cam_mounts = {m for c in cams for m in [_infer_mount(c.model, c.desc)] if m}
    for ln in lenses:
        lm = _infer_mount(ln.model, ln.desc)
        if not lm or not cam_mounts:
            rep.checks.append(CompatCheck("镜头卡口", None, "镜头「%s」卡口无法判定" % (ln.model or ln.desc)))
            continue
        if lm in cam_mounts or ("C口" in cam_mounts and lm == "C口"):
            rep.checks.append(CompatCheck("镜头卡口", True, "镜头 %s ↔ 相机 %s 兼容" % (lm, sorted(cam_mounts))))
        else:
            rep.checks.append(CompatCheck("镜头卡口", False, "镜头 %s 与相机 %s 不兼容" % (lm, sorted(cam_mounts))))

    # 2) 相机接口 ↔ 采集能力
    for c in cams:
        iface = _infer_interface(c.model, c.desc)
        if not iface:
            rep.checks.append(CompatCheck("相机接口", None, "相机「%s」接口无法判定" % (c.model or c.desc)))
            continue
        if iface == "GigE":
            ports = None
            for ip in ipcs:
                ports = _infer_ipc_ports(ip.model, ip.desc)
                if ports:
                    break
            if ports is None:
                rep.checks.append(CompatCheck("相机接口", None, "%s 相机需网口，工控机网口数未标注" % iface))
            elif sum(x.qty for x in cams) <= ports:
                rep.checks.append(CompatCheck("相机接口", True, "%d 路 %s ≤ 工控机 %d 网口" % (len(cams), iface, ports)))
            else:
                rep.checks.append(CompatCheck("相机接口", False, "%d 路 %s > 工控机 %d 网口，需采集卡或换工控机" % (len(cams), iface, ports)))
        elif iface == "10GigE":
            has_card = any("采集卡" in x.desc or "板卡" in x.desc for x in by_type.get("output", []) + ipcs)
            rep.checks.append(CompatCheck("相机接口", True if has_card else None,
                "%s 相机" % iface + ("已配置采集卡/板卡" if has_card else "需确认是否配置万兆采集卡")))
        else:
            rep.checks.append(CompatCheck("相机接口", True, "%s 接口可用" % iface))

    # 3) 光源路数 ↔ 控制器通道数
    light_qty = sum(x.qty for x in lights)
    ch = None
    for ct in ctrls:
        ch = _infer_channels(ct.model, ct.desc)
        if ch:
            break
    if not lights:
        rep.checks.append(CompatCheck("光源通道", None, "清单未含光源"))
    elif ch is None:
        rep.checks.append(CompatCheck("光源通道", None, "%d 路光源，控制器通道数未标注" % light_qty))
    elif light_qty <= ch:
        rep.checks.append(CompatCheck("光源通道", True, "%d 路光源 ≤ 控制器 %d 通道" % (light_qty, ch)))
    else:
        rep.checks.append(CompatCheck("光源通道", False, "%d 路光源 > 控制器 %d 通道，需加控制器或减光源" % (light_qty, ch)))

    # 4) 镜头分辨率 ↔ 相机像素
    cam_mp = None
    for c in cams:
        v = _infer_camera_mp(c.model, c.desc)
        if v:
            cam_mp = max(cam_mp or 0, v)
    for ln in lenses:
        lm = _infer_lens_mp(ln.model, ln.desc)
        if lm is None or cam_mp is None:
            rep.checks.append(CompatCheck("镜头分辨率", None, "镜头「%s」或相机像素未标注，无法校验" % (ln.model or ln.desc)))
            continue
        if lm >= cam_mp:
            rep.checks.append(CompatCheck("镜头分辨率", True, "镜头 %gMP ≥ 相机 %gMP" % (lm, cam_mp)))
        else:
            rep.checks.append(CompatCheck("镜头分辨率", False, "镜头 %gMP < 相机 %gMP，镜头分辨率不足" % (lm, cam_mp)))

    # 5) 相机线缆配套（目录有 cable 条目时才校验）
    cable_ifaces = {str(c["适用接口"]) for c in _catalog().values() if c.get("device_type") == "cable" and c.get("适用接口")}
    if cable_ifaces and cams:
        for c in cams:
            iface = _infer_interface(c.model, c.desc)
            if not iface:
                continue
            matched = [k for k, v in _catalog().items() if v.get("device_type") == "cable" and v.get("适用接口") == iface]
            sel = [x for x in cables if x.model and any(k == x.model for k in matched)]
            if sel:
                rep.checks.append(CompatCheck("相机线缆", True, "%s 相机已配 %s" % (iface, sel[0].model)))
            elif matched:
                rep.checks.append(CompatCheck("相机线缆", None, "%s 相机未在清单里配线缆（目录有 %s）" % (iface, "、".join(matched[:3]))))
            else:
                rep.checks.append(CompatCheck("相机线缆", None, "%s 相机线缆目录缺失，请补充" % iface))

    return rep


def format_compat(rep: CompatReport) -> list[str]:
    out = []
    for c in rep.checks:
        icon = "✅" if c.passed else ("❌" if c.passed is False else "⚠️")
        out.append("%s [%s] %s" % (icon, c.rule, c.message))
    return out
