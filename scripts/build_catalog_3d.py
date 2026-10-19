"""
海康 3D 视觉产品手册全量解析（一次性覆盖所有产品族）。

产品族与字段（据 PDF 表头）：
  DP(-P)  3D激光轮廓传感器(单线)    10字段
  DP(-D)  双目单线轮廓传感器          10字段
  DL      双目单线体积测量             8字段
  DS      3D结构光传感器              分辨率/帧率/基准距离/视场/Z范围/Z重复精度/像素间距/光源/IP
  DLS     激光振镜立体相机            近视场/远视场/分辨率/采集时间/出图延时/数据类型
  DPS     投影结构光立体相机          净距离/测量范围/近视场/远视场/检测精度/扫描帧率/数据类型/IP
  DB      感知相机(双目/深度)         视场角/工作范围/波长/测量精度/重复精度/分辨率/帧率/接口
  DT      感知相机(ToF)               视场角/工作范围/波长/精度/分辨率/帧率/接口
  SL      3D视觉套包                  套包(功能/处理器/内存/配套相机)
  RVM     物流视觉控制器              型号
"""
from __future__ import annotations
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data" / "catalog" / "海康3D视觉产品手册2026Q3.pdf"
OUT = ROOT / "data" / "catalog" / "products.json"


def extract_text(p: Path) -> str:
    import pdfplumber
    return "\n".join(pg.extract_text() or "" for pg in pdfplumber.open(str(p)).pages)


def _mm(ln): return [float(x) for x in re.findall(r"([\d.]+)\s*mm", ln)]
def _um(ln): return re.findall(r"([\d.]+\s*~\s*[\d.]+|[.\d]+)\s*µm", ln)
def _fps(ln): return re.findall(r"([\d.]+)\s*fps", ln)
def _deg(ln): return re.findall(r"([\d.]+)\s*°", ln)


def parse_dp(lines, i):
    ln = lines[i]
    m = re.search(r"(MV-DP\d+-\d+[PD])(?:\s+V([\d.]+))?", ln)
    if not m: return None
    model, ver = m.group(1), m.group(2)
    body = ln[m.end():]
    mm = _mm(body); um = _um(body)
    wl = re.search(r"(\d+)\s*nm", body)
    fps_inline = re.search(r"([\d.]+)k\s*Hz\s*~\s*([\d.]+)k\s*Hz", body)
    fps_min = re.search(r"([\d.]+)k\s*Hz\s*~", ln[:m.start()])
    fps_max = None
    for j in range(max(0, i - 3), min(len(lines), i + 4)):
        if j == i: continue
        fm = re.search(r"([\d.]+)k\s*Hz", lines[j])
        if fm and fm.group(1) != (fps_min.group(1) if fps_min else None):
            fps_max = fm.group(1); break
    ref = far = None
    for j in range(max(0, i - 3), min(len(lines), i + 4)):
        if j == i: continue
        l2 = lines[j]
        if ref is None:
            rm = re.search(r"([\d.]+)\s*mm@参考距离", l2)
            if rm: ref = rm.group(1)
        if far is None:
            fm = re.search(r"([\d.]+)\s*mm@远端", l2)
            if fm: far = fm.group(1)
    xrange = []
    if ref: xrange.append("%smm@参考距离" % ref)
    if len(mm) >= 3: xrange.append("%gmm@近端" % mm[2])
    if far: xrange.append("%smm@远端" % far)
    e = {"model": model, "类型": "双目单线3D轮廓传感器" if model.endswith("D") else "3D激光轮廓传感器", "版本": ver}
    pm = re.search(r"(\d+)\s", body)
    if pm: e["单轮廓点数"] = int(pm.group(1))
    if len(mm) >= 1: e["参考距离mm"] = mm[0]
    if len(mm) >= 2: e["Z轴测量范围mm"] = mm[1]
    if xrange: e["X轴测量范围"] = "；".join(xrange)
    if len(um) >= 1: e["Z轴分辨率µm"] = um[0].strip()
    if len(um) >= 2: e["Z轴重复精度µm"] = um[1].strip()
    if len(um) >= 3: e["轮廓数据间隔µm"] = um[2].strip()
    if fps_inline: e["扫描帧率"] = "%sk Hz ~ %sk Hz" % (fps_inline.group(1), fps_inline.group(2))
    elif fps_min and fps_max: e["扫描帧率"] = "%sk Hz ~ %sk Hz" % (fps_min.group(1), fps_max)
    if wl: e["激光波长nm"] = int(wl.group(1))
    return e


def parse_dl(lines, i):
    ln = lines[i]
    m = re.search(r"(MV-DL\d+-\d+[HP]R?-R?)", ln)
    if not m: return None
    model = m.group(1)
    body = ln[m.end():]
    mm = _mm(body)
    acc = re.search(r"±\s*([\d.]+)\s*mm", body)
    speed = fps = None
    if i > 0:
        prev = lines[i - 1]
        sm = re.search(r"([\d.]+)\s*m/s", prev)
        if sm: speed = sm.group(1)
        fm = re.search(r"([\d.]+)\s*fps", prev)
        if fm: fps = fm.group(1)
    e = {"model": model, "类型": "双目单线3D轮廓传感器"}
    if len(mm) >= 1: e["近视场mm"] = mm[0]
    if len(mm) >= 2: e["远视场mm"] = mm[1]
    if len(mm) >= 3: e["净距离CDmm"] = mm[2]
    if len(mm) >= 4: e["测量范围MRmm"] = mm[3]
    if acc: e["检测精度"] = "±" + acc.group(1) + "mm"
    if speed: e["检测速度m/s"] = speed
    if fps: e["扫描帧率fps"] = fps
    return e


def parse_ds(lines, i):
    ln = lines[i]
    m = re.search(r"(MV-DS\d+-\d+[HP])", ln)
    if not m: return None
    model = m.group(1)
    body = ln[m.end():]
    e = {"model": model, "类型": "3D结构光传感器"}
    f = re.search(r"(\d+)\s*[×x]\s*(\d+)", body)
    if f: e["图像分辨率"] = "%s×%s" % (f.group(1), f.group(2))
    fps = _fps(body)
    if fps: e["全周期帧率fps"] = "/".join(fps)
    mm = _mm(body)
    if mm: e["基准距离mm"] = mm[0]
    fov = re.findall(r"([\d.]+)\s*mm\s*[×x]\s*([\d.]+)\s*mm", body)
    if fov: e["视场范围"] = "；".join("%s×%smm" % (a, b) for a, b in fov)
    f = re.search(r"±\s*([\d.]+)\s*mm", body)
    if f: e["Z轴测量范围"] = "±" + f.group(1) + "mm"
    f = re.search(r"<([\d.]+)\s*µm", body)
    if f: e["Z轴重复精度"] = "<" + f.group(1) + "µm"
    f = re.search(r"([\d.]+)\s*mm(?!\s*[×x])", body)
    f2 = re.search(r"(蓝光|白光|红光|红外)\s*(LED|激光)", body)
    if f2: e["光源类型"] = f2.group(0)
    f3 = re.search(r"IP(\d+)", body)
    if f3: e["IP防护"] = "IP" + f3.group(1)
    return e


def parse_dls(lines, i):
    ln = lines[i]
    m = re.search(r"(MV-DLS[A-Z0-9]+(?:-[A-Z0-9]+)*)", ln)
    if not m: return None
    model = m.group(1)
    body = ln[m.end():]
    e = {"model": model, "类型": "激光振镜立体相机"}
    mm = _mm(body)
    if mm: e["近视场mm"] = mm[0]
    if len(mm) >= 2: e["远视场mm"] = mm[1]
    f = re.search(r"(\d+)\s*[×x]\s*(\d+)", body)
    if f: e["分辨率"] = "%s×%s" % (f.group(1), f.group(2))
    f = re.search(r"Class\s*(\d+)", body)
    if f: e["激光等级"] = "Class " + f.group(1)
    f = re.search(r"IP(\d+)", body)
    if f: e["IP防护"] = "IP" + f.group(1)
    return e


def parse_dps(lines, i):
    ln = lines[i]
    m = re.search(r"(MV-DPS[A-Z0-9]+(?:-[A-Z0-9]+)*)", ln)
    if not m: return None
    model = m.group(1)
    body = ln[m.end():]
    e = {"model": model, "类型": "投影结构光立体相机"}
    mm = _mm(body)
    if len(mm) >= 1: e["净距离mm"] = mm[0]
    if len(mm) >= 2: e["测量范围mm"] = mm[1]
    f = re.search(r"IP(\d+)", body)
    if f: e["IP防护"] = "IP" + f.group(1)
    return e


def parse_db(lines, i):
    ln = lines[i]
    m = re.search(r"(MV-DB[A-Z0-9]+(?:-[A-Z0-9]+)*)", ln)
    if not m: return None
    model = m.group(1)
    body = ln[m.end():]
    e = {"model": model, "类型": "感知相机(双目/深度)"}
    mm = _mm(body)
    if len(mm) >= 1: e["工作范围近mm"] = mm[0]
    if len(mm) >= 2: e["工作范围远mm"] = mm[1]
    f = re.search(r"(\d+)\s*fps@\s*(\d+)\s*[×x]\s*(\d+)", body)
    if f: e["帧率"] = f.group(1) + "fps"; e["分辨率"] = "%s×%s" % (f.group(2), f.group(3))
    f = re.search(r"(GigE|USB3|10GigE|CameraLink|CoaXPress)", body)
    if f: e["接口"] = f.group(1)
    return e


def parse_dt(lines, i):
    ln = lines[i]
    m = re.search(r"(MV-DT[A-Z0-9]+(?:-[A-Z0-9]+)*)", ln)
    if not m: return None
    model = m.group(1)
    body = ln[m.end():]
    e = {"model": model, "类型": "感知相机(ToF)"}
    f = re.search(r"(\d+)\s*°\s*[x×]\s*(\d+)\s*°", body)
    if f: e["视场角"] = "%s°×%s°" % (f.group(1), f.group(2))
    f = re.search(r"([\d.]+~[\d.]+)\s*m\b", body)
    if f: e["工作范围m"] = f.group(1)
    f = re.search(r"(\d+)\s*nm", body)
    if f: e["波长nm"] = int(f.group(1))
    f = re.search(r"±\s*（?([^）m]+)mm", body)
    if f: e["测量精度"] = "±" + f.group(1) + "mm"
    f = re.search(r"(\d+)\s*[×x]\s*(\d+)", body)
    if f: e["分辨率"] = "%s×%s" % (f.group(1), f.group(2))
    f = re.search(r"(\d+)\s*fps", body)
    if f: e["帧率fps"] = f.group(1)
    f = re.search(r"(GigE|USB3|10GigE)", body)
    if f: e["接口"] = f.group(1)
    return e


def parse_sl(lines, i):
    ln = lines[i]
    m = re.search(r"(MV-SL-\d+-\d+)", ln)
    if not m: return None
    model = m.group(1)
    body = ln[m.end():]
    e = {"model": model, "类型": "3D视觉套包"}
    f = re.search(r"（([^）]+)）", body)
    if f: e["套包"] = f.group(1)
    f = re.search(r"MV-RVM\d+", body)
    if f: e["配套控制器"] = f.group(0)
    f = re.search(r"处理器：([^ ]+)", body)
    if f: e["处理器"] = f.group(1)
    f = re.search(r"内存：([^ ]+)", body)
    if f: e["内存"] = f.group(1)
    return e


def parse_3dc(lines, i):
    ln = lines[i]
    m = re.search(r"(MV-3DC-[A-Z0-9-]+)", ln)
    if not m: return None
    return {"model": m.group(1), "类型": "3D相机", "原文参数": ln.strip()[:100]}


def parse_rvm(lines, i):
    ln = lines[i]
    m = re.search(r"(MV-RVM\d+)", ln)
    if not m: return None
    return {"model": m.group(1), "类型": "物流视觉控制器", "原文参数": ln.strip()[:100]}


SERIES = [
    {"系列": "3D激光轮廓传感器", "设备类型": "sensor3d", "前缀": ["MV-DP"], "排除": ["-01D", "-03D"],
     "定位": "提供高帧率、微米级精度的点云、深度图、亮度图数据。",
     "适用场景": "在线、非接触式、高精度3D测量（轮廓/高度/段差）"},
    {"系列": "双目单线3D轮廓传感器", "设备类型": "sensor3d", "前缀": ["-01D", "-03D", "MV-DL"],
     "定位": "双图像传感器设计，消除视野盲区，抑制杂散光；重复精度亚微米，扫描最高46.7kHz；MV-DL面向动态体积测量。",
     "适用场景": "存在视野盲区、杂散光干扰的轮廓测量；动态体积测量(DWS)"},
    {"系列": "3D结构光传感器", "设备类型": "sensor3d", "前缀": ["MV-DS"],
     "定位": "定制化莎姆光学系统，成像质量优异；多曝光模式材质鲁棒性强；一体式集成，点云输出最高9fps。",
     "适用场景": "高节拍、在线静态非接触3D检测"},
    {"系列": "激光振镜/投影结构光立体相机", "设备类型": "stereo", "前缀": ["MV-DLS", "MV-DPS"],
     "定位": "高帧率高完整性立体成像，提供深度图、RGB图。",
     "适用场景": "3D视觉定位引导、拆码垛、工件抓取"},
    {"系列": "感知相机", "设备类型": "perception", "前缀": ["MV-DB", "MV-DT", "MV-USB"],
     "定位": "双目立体匹配/ToF，高帧率RGB-D图像，多平台SDK。",
     "适用场景": "环境感知、物体识别"},
    {"系列": "3D视觉套包", "设备类型": "sensor3d", "前缀": ["MV-SL"],
     "定位": "3D视觉成套解决方案（含控制器、相机、软件）。",
     "适用场景": "拆码垛、工件抓取、料框拆垛"},
    {"系列": "物流视觉控制器", "设备类型": "logistics", "前缀": ["MV-RVM"],
     "定位": "面向快递/仓储物流的视觉处理平台。",
     "适用场景": "拆码垛、料框拆垛、全功能视觉"},
]


def summarize(e):
    t = e.get("类型", "")
    if t in ("3D激光轮廓传感器", "双目单线3D轮廓传感器") and e.get("近视场mm") is not None:
        ex = []
        if e.get("测量范围MRmm") is not None: ex.append("MR%gmm" % e["测量范围MRmm"])
        if e.get("检测精度"): ex.append(e["检测精度"])
        return "%s（%s）" % (e["model"], "，".join(ex))
    if t in ("3D激光轮廓传感器", "双目单线3D轮廓传感器"):
        ex = []
        if e.get("激光波长nm"): ex.append("%dnm" % e["激光波长nm"])
        if e.get("Z轴测量范围mm") is not None: ex.append("Z范围%gmm" % e["Z轴测量范围mm"])
        return "%s（%s）" % (e["model"], "，".join(ex))
    # 其它 3D 类型：通用取关键字段
    keys = ("图像分辨率", "分辨率", "视场角", "工作范围m", "工作范围近mm", "波长nm", "接口", "IP防护", "套包", "光源类型")
    ex = [str(e[k]) for k in keys if e.get(k)]
    return "%s（%s）" % (e["model"], "，".join(ex))

def main():
    lines = extract_text(PDF).splitlines()
    grp_of = {"3D激光轮廓传感器": "sensor3d", "双目单线3D轮廓传感器": "sensor3d",
              "3D结构光传感器": "sensor3d", "3D视觉套包": "sensor3d",
              "激光振镜立体相机": "stereo", "投影结构光立体相机": "stereo",
              "感知相机(双目/深度)": "perception", "感知相机(ToF)": "perception",
              "物流视觉控制器": "logistics", "3D相机": "stereo"}
    parsers = [parse_dp, parse_dl, parse_ds, parse_dls, parse_dps, parse_db, parse_dt, parse_sl, parse_3dc, parse_rvm]
    groups = {"sensor3d": [], "stereo": [], "perception": [], "logistics": []}
    seen = set()
    for i, ln in enumerate(lines):
        ln = ln.strip()
        for fn in parsers:
            e = fn(lines, i)
            if e and e["model"] not in seen:
                seen.add(e["model"])
                groups[grp_of.get(e["类型"], "sensor3d")].append(e)
                break

    d = json.load(open(OUT, encoding="utf-8")) if OUT.exists() else {}
    for k in groups: d[k] = groups[k]
    names = {s["系列"] for s in SERIES}
    series_out = [x for x in d.get("series", []) if x.get("系列") not in names]
    for s in SERIES:
        models = []
        for t in groups:
            for e in groups[t]:
                if any(pr in e["model"] for pr in s["前缀"]) and not any(ex in e["model"] for ex in s.get("排除", [])):
                    models.append(summarize(e))
        series_out.append({"系列": s["系列"], "设备类型": s["设备类型"], "定位": s["定位"],
                           "适用场景": s["适用场景"], "关联型号数": len(models), "关联型号": models[:200]})
    d["series"] = series_out
    json.dump(d, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    for k in groups: print("  %-12s %d 条" % (k, len(groups[k])))


if __name__ == "__main__":
    main()
