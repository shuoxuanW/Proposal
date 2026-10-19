"""
从海康标准产品手册 PDF 解析全量产品，写入 data/catalog/products.json。

覆盖：面阵相机(CS/CU/CT/CH)、板级相机(CB)、线阵相机(CL)、红外相机(CI)、
      镜头(MVL)、采集卡(MV-GT)、线缆(MV-AC)、系列(定位/适用场景→关联型号)。

用法：python -X utf8 scripts/build_catalog.py
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data" / "catalog" / "海康机器视觉标准产品手册2026Q3.pdf"
OUT = ROOT / "data" / "catalog" / "products.json"

MOUNT_MAP = {"C-Mount": "C口", "CS-Mount": "CS口", "S-Mount": "S口", "M42": "M42",
             "M72": "M72", "F-Mount": "F口", "M12": "M12"}


def extract_text(pdf_path: Path) -> str:
    import pdfplumber
    pdf = pdfplumber.open(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in pdf.pages)


def iface(u: str) -> str:
    if re.search(r"A[0-9]", u): return "XoFLink"
    if re.search(r"90[TGX]|10T", u): return "10GigE"
    if re.search(r"6[01][GN]", u): return "CoaXPress"
    if re.search(r"10C", u): return "CameraLink"
    if re.search(r"(?:10|11|13|20|24|80|91|92)G", u): return "GigE"
    if re.search(r"(?:10|20|60|61|80|90)U", u): return "USB3"
    return "待确认"


def color(m: str) -> str:
    if m.endswith("C"): return "彩色"
    if m.endswith("M") or m.endswith("N"): return "黑白"
    return "待确认"


# ---- 面阵 + 板级 ----
AREA_RE = re.compile(
    r"^(?P<model>MV-C[STUHB][A-Z0-9-]*(?:\(POE\))?)\s+(?P<sensor>.*?)\s+"
    r"(?P<target>\d+(?:/\d+(?:\.\d+)?|\.\d+)?)(?:\"|'')\s+"
    r"(?P<pixel>[\d.]+)\s*μm\s+(?P<shutter>Global|Rolling)\s+(?P<w>\d+)\s*[×x]\s*(?P<h>\d+)\s+"
    r"(?P<fps>[\d.]+)\s*fps\s+(?P<exposure>.*?)\s+(?P<power>[\d.]+)\s*W@\s*[\d.]+\s*VDC"
    r"(?:\s+(?P<mount>C-Mount|CS-Mount|M42|M72|F-Mount))?"
)
LINE_RE = re.compile(
    r"^(?P<model>MV-CL[A-Z0-9-]*)\s+(?P<pixel>[\d.]+)\s*μm\s*[×x]\s*[\d.]+\s*μm\s+"
    r"(?P<w>\d+)\s*[×x]\s*(?P<h>\d+)\s+(?P<rate>[\d.]+)\s*kHz.*?(?P<power>[\d.]+)\s*W@\s*[\d.]+\s*VDC"
)


def parse_camera(ln: str):
    m = AREA_RE.match(ln)
    if not m:
        return None
    d = m.groupdict()
    model = d["model"]
    if "MV-CL" in model:
        return None
    w, h = int(d["w"]), int(d["h"])
    sensor = d["sensor"].strip()
    if not re.search(r"(IMX|CMV|BSI|Gpixel|GMAX|Pregius|Starvis|索尼|Sony)", sensor, re.I):
        sensor = sensor if 2 <= len(sensor) <= 12 else ""
    kind = "板级相机" if model.startswith("MV-CB") else "面阵相机"
    return {"model": model, "类型": kind, "传感器": sensor, "靶面": d["target"] + "英寸",
            "像元μm": float(d["pixel"]), "快门": "全局" if d["shutter"] == "Global" else "卷帘",
            "分辨率": "%s×%s" % (w, h), "像素万": round(w * h / 10000.0, 2),
            "帧率fps": float(d["fps"]), "曝光时间": d["exposure"].strip(),
            "典型功耗W": float(d["power"]), "接口": iface(model.upper()),
            "卡口": MOUNT_MAP.get(d.get("mount")) or ("C口" if not model.startswith("MV-CB") else None),
            "颜色": color(model)}


def parse_linescan(ln: str):
    m = LINE_RE.match(ln)
    if not m:
        return None
    d = m.groupdict()
    w, h = int(d["w"]), int(d["h"])
    return {"model": d["model"], "类型": "线阵相机", "像元μm": float(d["pixel"]),
            "分辨率": "%s×%s" % (w, h), "行频kHz": float(d["rate"]),
            "典型功耗W": float(d["power"]), "接口": iface(d["model"].upper()), "颜色": color(d["model"])}


def parse_infrared(ln: str):
    m = re.match(r"^(MV-CI\S+)", ln)
    if not m:
        return None
    model = m.group(1)
    e = {"model": model, "类型": "红外相机"}
    f = re.search(r"(长波|短波)", ln)
    if f: e["波段"] = f.group(1)
    f = re.search(r"(观测型|测温型)", ln)
    if f: e["类型2"] = f.group(1)
    f = re.search(r"([\d.]+-[\d.]+)\s*(?:μm|um)", ln)
    if f: e["波段μm"] = f.group(1)
    f = re.search(r"(\d+)\s*[×x]\s*(\d+)", ln)
    if f: e["分辨率"] = "%s×%s" % (f.group(1), f.group(2))
    f = re.search(r"([\d.]+)\s*(?:fps|kHz)", ln)
    if f: e["帧率"] = float(f.group(1))
    f = re.search(r"<([\d.]+)\s*mk", ln)
    if f: e["热灵敏度mk"] = float(f.group(1))
    return e


def parse_lens(ln: str):
    m = re.match(r"^(MVL-\S+)", ln)
    if not m:
        return None
    model = m.group(1)
    e = {"model": model, "类型": "镜头"}
    f = re.search(r"([\d.]+)\s*mm", ln)
    if f: e["焦距mm"] = float(f.group(1))
    f = re.search(r"(?<=\s)F[\d.]+(?:~F[\d.]+)?", ln)
    if f: e["光圈范围"] = f.group(0)
    f = re.search(r"(-?[\d.]+\s*%|<[\d.]+\s*%)", ln)
    if f: e["畸变"] = f.group(1).replace(" ", "")
    fovs = re.findall(r"([\d.]+)\s*°", ln)
    if len(fovs) >= 3:
        e["视场角D°"], e["视场角H°"], e["视场角V°"] = map(float, fovs[:3])
    f = re.search(r"([\d.]+)\s*m\b", ln)
    if f: e["最近摄距m"] = float(f.group(1))
    f = re.search(r"M[\d.]+(?:\s*[×x]\s*P?[\d.]+)?", ln)
    if f: e["滤镜螺纹"] = f.group(0).replace(" ", "")
    f = re.search(r"(C-Mount|CS-Mount|S-Mount|M42|M72|F-Mount|M12)", ln)
    if f: e["卡口"] = MOUNT_MAP.get(f.group(1), f.group(1))
    mp = re.search(r"-(\d+)MPE?\b", model)
    if mp: e["标称MP"] = int(mp.group(1))
    return e


def parse_framegrabber(ln: str):
    m = re.match(r"^(MV-GT\d+[A-Z]*)\s+", ln)
    if not m:
        return None
    model = m.group(1)
    e = {"model": model, "类型": "采集卡"}
    f = re.search(r"PCI-E\s*gen\S*\s*[×x]\s*\S+", ln)
    if f: e["总线接口"] = f.group(0)
    f = re.search(r"(\d+)\s*[×x]\s*RJ45", ln)
    if f: e["网口数"] = int(f.group(1))
    f = re.search(r"([\d./]+)\s*(Gbps|Mbps)", ln)
    if f: e["带宽"] = f.group(1) + f.group(2)
    f = re.search(r"([\d.]+)\s*W", ln)
    if f: e["功耗W"] = float(f.group(1))
    return e


CABLE_IFACE = [("MV-ACU3", "USB3"), ("MV-ACG", "GigE"), ("MV-AC10G", "10GigE"),
               ("MV-ACCL", "CameraLink"), ("MV-ACXP", "CoaXPress"), ("MV-ACP", "I/O触发"),
               ("MV-AC100G", "100G光纤"), ("MV-AC50G", "50G光纤")]


def parse_cable(ln: str):
    m = re.search(r"(MV-AC\S+)", ln)
    if not m:
        return None
    model = m.group(1)
    iface = next((v for k, v in CABLE_IFACE if model.startswith(k)), "待确认")
    pre = ln[:m.start()].strip()
    e = {"model": model, "类型": "线缆", "接口": iface, "类别": pre if len(pre) <= 10 else ""}
    f = re.search(r"([\d.]+\s*m(?:\s*/\s*[\d.]+\s*m)*|\d+\s*m)", ln)
    if f: e["长度"] = f.group(1).replace(" ", "")
    return e


SERIES = [
    {"系列": "CS系列面阵相机", "设备类型": "camera", "前缀": ["MV-CS"], "排除": [],
     "定位": "海康面阵相机基础系列，新一代外观结构，支持四面安装，装配精度高、电压接入宽、温宽大。",
     "适用场景": "通用工业检测、定位引导、测量、读码"},
    {"系列": "CU系列面阵相机", "设备类型": "camera", "前缀": ["MV-CU"], "排除": [],
     "定位": "通用型面阵相机，全新硬件设计，同Sensor功耗较其他系列降低20%以上。",
     "适用场景": "对功耗、散热有要求的通用工业应用"},
    {"系列": "CT系列面阵相机", "设备类型": "camera", "前缀": ["MV-CT"], "排除": [],
     "定位": "专为工业应用设计，行业领先的性能与可靠性。",
     "适用场景": "工业产线定位引导、测量、缺陷检测"},
    {"系列": "CH系列面阵相机", "设备类型": "camera", "前缀": ["MV-CH"], "排除": [],
     "定位": "高端型系列，覆盖400万~6.04亿像素，兼顾高分辨率与高帧率，具备风扇/TEC制冷型号。",
     "适用场景": "新能源、电子半导体、面板、PCB等高精尖应用"},
    {"系列": "CB系列板级相机", "设备类型": "camera", "前缀": ["MV-CB"], "排除": [],
     "定位": "单板或多板堆叠设计，支持GigE及USB3.0，结构紧凑易集成。",
     "适用场景": "对空间要求高的工业、嵌入式应用"},
    {"系列": "CL系列线阵相机", "设备类型": "linescan", "前缀": ["MV-CL"], "排除": [],
     "定位": "线阵相机系列，分辨率覆盖2k~16k，支持GigE/USB3/CameraLink/CoaXPress/XoFLink。",
     "适用场景": "大幅面、连续物料高速扫描（薄膜、板材、印刷品）"},
    {"系列": "CI系列红外相机", "设备类型": "infrared", "前缀": ["MV-CI"], "排除": [],
     "定位": "长波用氧化钒探测器（测温），短波用铟镓砷传感器（可见光到短波）。",
     "适用场景": "新能源、半导体、农业测温与短波成像"},
    {"系列": "FA镜头", "设备类型": "lens", "前缀": ["MVL-HF", "MVL-MF", "MVL-KF", "MVL-AF", "MVL-LF"], "排除": ["-05S", "-12S"],
     "定位": "高性能、低成本FA镜头，高清晰度、中心边缘一致、高相对照度。",
     "适用场景": "面阵相机通用成像，定位/测量/缺陷检测"},
    {"系列": "远心镜头", "设备类型": "lens", "前缀": ["MVL-LBT"], "排除": [],
     "定位": "高解像力、低畸变、高远心度，透视畸变极小。",
     "适用场景": "高精度定位与尺寸测量"},
    {"系列": "M12/嵌入式镜头", "设备类型": "lens", "前缀": ["-05S", "-12S"], "排除": [],
     "定位": "全金属镜筒+全玻璃镜片，500万分辨率，体积小巧。",
     "适用场景": "嵌入式、紧凑空间视觉"},
    {"系列": "采集卡", "设备类型": "framegrabber", "前缀": ["MV-GT"], "排除": [],
     "定位": "机器视觉核心配件，涵盖千兆/万兆网口、USB3、CameraLink等接口，不丢包。",
     "适用场景": "多相机带宽汇聚、HOST端低负荷采集"},
    {"系列": "线缆", "设备类型": "cable", "前缀": ["MV-AC"], "排除": [],
     "定位": "数据线/供电IO线/光模块，部分支持运动拖链、扭转、弯折。",
     "适用场景": "相机供电与数据传输、运动场景布线"},
]


def summarize(t: str, e: dict) -> str:
    if t in ("camera", "linescan", "infrared"):
        return "%s（%s）" % (e["model"], e.get("分辨率", ""))
    if t == "lens":
        return "%s（%gmm，%s）" % (e["model"], e.get("焦距mm", 0) or 0, e.get("卡口", ""))
    if t == "framegrabber":
        return "%s（%s，%s口）" % (e["model"], e.get("总线接口", ""), e.get("网口数", ""))
    if t == "cable":
        return "%s（%s，%s）" % (e["model"], e.get("接口", ""), e.get("长度", ""))
    return e["model"]


def main() -> None:
    text = extract_text(PDF)
    groups = {"camera": [], "linescan": [], "infrared": [], "lens": [], "framegrabber": [], "cable": []}
    seen = set()
    for ln in text.splitlines():
        ln = ln.strip()
        for name, fn in (("camera", parse_camera), ("linescan", parse_linescan)):
            e = fn(ln)
            if e and e["model"] not in seen:
                seen.add(e["model"]); groups[name].append(e); break
        else:
            e = parse_infrared(ln)
            if e and e["model"] not in seen:
                seen.add(e["model"]); groups["infrared"].append(e); continue
            e = parse_lens(ln)
            if e and e["model"] not in seen:
                seen.add(e["model"]); groups["lens"].append(e); continue
            e = parse_framegrabber(ln)
            if e and e["model"] not in seen:
                seen.add(e["model"]); groups["framegrabber"].append(e); continue
            e = parse_cable(ln)
            if e and e["model"] not in seen:
                seen.add(e["model"]); groups["cable"].append(e); continue

    series_out = []
    for s in SERIES:
        models = []
        for t in ("camera", "linescan", "infrared", "lens", "framegrabber", "cable"):
            for e in groups.get(t, []):
                m = e["model"]
                if any(pr in m for pr in s["前缀"]) and not any(ex in m for ex in s["排除"]):
                    models.append(summarize(t, e))
        series_out.append({"系列": s["系列"], "设备类型": s["设备类型"],
                           "定位": s["定位"], "适用场景": s["适用场景"],
                           "关联型号数": len(models), "关联型号": models[:200]})

    out = dict(groups)
    out["series"] = series_out
    os.makedirs(OUT.parent, exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    for k in ("camera", "linescan", "infrared", "lens", "framegrabber", "cable", "series"):
        print("  %-14s %d 条" % (k, len(out[k])))


if __name__ == "__main__":
    main()
