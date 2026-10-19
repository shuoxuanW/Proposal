"""
相机参数批量入库：按固定字段顺序解析 datasheet 行，写入 data/device_catalog.json。

字段顺序（9 个，空格分隔）：
  产品型号 | 传感器型号 | 靶面尺寸 | 像元尺寸 | 快门类型 | 分辨率 | 最大帧率 | 曝光时间 | 典型功耗

用法：
  python -X utf8 scripts/import_catalog.py cameras.txt      # 从文件读
  python -X utf8 scripts/import_catalog.py                 # 从 stdin 读（粘贴后 Ctrl+Z 回车）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "device_catalog.json"

SHUTTER_MAP = {"global": "全局", "全局": "全局", "rolling": "卷帘", "卷帘": "卷帘", "linescan": "线扫", "线扫": "线扫"}


def infer_interface(model: str) -> str:
    u = model.upper()
    if "90T" in u:
        return "10GigE"
    if "10U" in u:
        return "USB3"
    if re.search(r"10G|12G|25G", u):
        return "GigE"
    return "待确认"


def infer_color(model: str) -> str:
    m = re.search(r"(\d+)G([CM])\b", model)
    if m:
        return "彩色" if m.group(2) == "C" else "黑白"
    m = re.search(r"-([CM])\d{3}(?!\d)", model)
    if m:
        return "彩色" if m.group(1) == "C" else "黑白"
    return "待确认"


def parse_camera_line(line: str) -> dict | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    toks = line.split()
    if len(toks) < 7:
        return None
    model = toks[0]
    sensor = toks[1]
    target = toks[2]
    if target.endswith('"'):
        target = target[:-1] + "英寸"
    else:
        target = target.replace("inch", "英寸").strip()
    pixel = re.sub(r"[^0-9.]", "", toks[3])          # 6.9μm → 6.9
    shutter = SHUTTER_MAP.get(toks[4].lower(), toks[4])
    res = toks[5]                                   # 720×540
    fps = re.sub(r"[^0-9.]", "", toks[6])           # 125.2fps → 125.2
    power = toks[-1]                                # 2.2W@12VDC
    exposure = " ".join(toks[7:-1]) if len(toks) > 8 else ""

    m = re.search(r"(\d+)\s*[×xX]\s*(\d+)", res)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))

    entry: dict = {
        "model": model,
        "像素万": round(w * h / 10000.0, 2),
        "分辨率": "%d×%d" % (w, h),
        "快门": shutter,
        "接口": infer_interface(model),
        "卡口": "C口",           # 待人工确认（MV 系列多为 C 口）
        "颜色": infer_color(model),
        "传感器": target,
        "像元μm": float(pixel) if pixel else None,
        "帧率fps": float(fps) if fps else None,
        "备注": ("传感器 %s；曝光 %s；功耗 %s" % (sensor, exposure or "-", power)).strip(),
    }
    entry = {k: v for k, v in entry.items() if v is not None}
    return entry


def main() -> None:
    lines: list[str] = []
    if len(sys.argv) > 1:
        lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    else:
        lines = [l for l in sys.stdin.read().splitlines()]

    if not CATALOG.exists():
        print("缺少设备目录：%s" % CATALOG)
        sys.exit(1)
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    cat.setdefault("camera", [])

    added, skipped = [], []
    for ln in lines:
        e = parse_camera_line(ln)
        if not e:
            skipped.append(ln)
            continue
        # 去重：同型号覆盖
        cat["camera"] = [x for x in cat["camera"] if x.get("model") != e["model"]]
        cat["camera"].append(e)
        added.append(e)

    CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=2), "utf8")

    print("入库完成：新增/覆盖 %d 条相机" % len(added))
    for e in added:
        warn = []
        if e.get("接口") == "待确认":
            warn.append("接口待确认")
        if e.get("颜色") == "待确认":
            warn.append("颜色待确认")
        if e.get("卡口") == "C口":
            warn.append("卡口按C口(请确认)")
        print("  - %s | %s | %s | %s%s" % (e["model"], e["快门"], e["接口"], e["颜色"],
              ("  [%s]" % "、".join(warn)) if warn else ""))
    if skipped:
        print("跳过 %d 行（字段不足）：%s" % (len(skipped), skipped))


if __name__ == "__main__":
    main()
