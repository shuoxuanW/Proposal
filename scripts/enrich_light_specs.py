"""从已有工位图 sidecar JSON 中回填光源角度/光源到工件距离。

原则：只使用明确标注，不猜测；优先使用“光源→被测物/产品/物料”连线上的标注。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "station_diagrams"

LIGHT_KEYS = ("光源", "打光", "环形", "圆顶", "条形", "同轴", "背光", "面光")
EXCLUDE_KEYS = ("示意图", "正视图", "配置", "规格", "表格", "说明")
OBJECT_KEYS = ("产品", "被测物", "物料", "工件", "平台", "吸塑盘", "引线", "玻璃", "PCB", "FPC")

ANGLE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:±\s*\d+(?:\.\d+)?\s*)?°(?:\s*±\s*\d+(?:\.\d+)?\s*°)?(?:\s*[-~至]\s*\d+(?:\.\d+)?\s*°)?")
DIST_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:±\s*\d+(?:\.\d+)?\s*)?mm", re.I)
BARE_DIST_RE = re.compile(r"\d+(?:\.\d+)?\s*±\s*\d+(?:\.\d+)?")
NOTE_ANGLE_RES = [
    re.compile(r"(\d+(?:\.\d+)?\s*[-~至]\s*\d+(?:\.\d+)?\s*°)[^。；\n]{0,8}(?:角度)?可调"),
    re.compile(r"(\d+(?:\.\d+)?\s*°\s*±\s*\d+(?:\.\d+)?\s*°)[^。；\n]{0,8}(?:角度)?可调"),
    re.compile(r"(?:角度|可调)[^。；\n]{0,12}?(\d+(?:\.\d+)?\s*°(?:\s*±\s*\d+(?:\.\d+)?\s*°)?(?:\s*[-~至]\s*\d+(?:\.\d+)?\s*°)?)"),
]
NOTE_DIST_RES = [
    re.compile(r"(?:光源到被测物距离|光源距离|距被测物|距产品|光源到产品)[：:\s]*(\d+(?:\.\d+)?\s*(?:±\s*\d+(?:\.\d+)?\s*)?mm)", re.I),
    re.compile(r"(\d+(?:\.\d+)?\s*±\s*\d+(?:\.\d+)?\s*mm)\s*[（(]?\s*光源"),
    re.compile(r"(\d+(?:\.\d+)?\s*±\s*\d+(?:\.\d+)?\s*(?:mm)?)\s*[（(]\s*光源到被测物距离"),
]


def is_light(name: str) -> bool:
    s = str(name or "")
    return any(k in s for k in LIGHT_KEYS) and not any(k in s for k in EXCLUDE_KEYS)


def is_object(name: str) -> bool:
    s = str(name or "")
    return any(k in s for k in OBJECT_KEYS) and not is_light(s)


def first_match(patterns, text: str) -> str:
    for pat in patterns:
        m = pat.search(text or "")
        if m:
            return m.group(1).strip()
    return ""


def note_value_with_kinds(patterns, note: str) -> tuple[str, list[str]]:
    for pat in patterns:
        m = pat.search(note or "")
        if m:
            prefix = (note or "")[max(0, m.start() - 28):m.start()]
            kinds = [k for k in ("圆顶", "环形", "条形", "同轴", "背光", "面光") if k in prefix]
            return m.group(1).strip(), kinds
    return "", []


def infer_kind(name: str, note: str) -> str:
    blob = name + " " + note
    for k in ("圆顶", "环形", "条形", "同轴", "背光", "面光"):
        if k in blob:
            return k
    return ""


def light_specs(data: dict) -> list[dict]:
    comps = data.get("component_list") or []
    conns = data.get("connection_list") or []
    note = data.get("note") or ""
    out = []
    for comp in comps:
        name = str(comp.get("name") or "")
        if not is_light(name):
            continue
        labels = []
        for c in conns:
            src, tgt = str(c.get("source") or ""), str(c.get("target") or "")
            if not ((is_light(src) and is_object(tgt)) or (is_light(tgt) and is_object(src))):
                continue
            # 只关联与当前光源名称匹配的连线，避免把光源1的标注复制给光源2
            if name and not (name in src or src in name or name in tgt or tgt in name):
                continue
            labels.append(str(c.get("label") or ""))
        angle = ""
        distance = ""
        for lab in labels:
            if not angle:
                m = ANGLE_RE.search(lab)
                if m:
                    angle = m.group(0)
            if not distance:
                m = DIST_RE.search(lab)
                if m:
                    distance = m.group(0)
                elif "°" not in lab:
                    m = BARE_DIST_RE.search(lab)
                    if m and ("单位：mm" in note or "unit: mm" in note.lower() or "mm" in note.lower()):
                        distance = m.group(0) + "mm"
        light_count = sum(1 for c in comps if is_light(str(c.get("name") or "")))
        if not angle:
            angle, kinds = note_value_with_kinds(NOTE_ANGLE_RES, note)
            if angle and light_count > 1:
                if kinds:
                    if not any(k in name for k in kinds):
                        angle = ""
                elif "条形" in name:
                    # 泛称“光源需角度可调”时，优先归到倾斜安装的条形光源
                    pass
                else:
                    angle = ""
        if not distance:
            distance, kinds = note_value_with_kinds(NOTE_DIST_RES, note)
            if distance and light_count > 1:
                if kinds:
                    if not any(k in name for k in kinds):
                        distance = ""
                else:
                    distance = ""
        if not angle and not distance:
            continue
        out.append({
            "name": name,
            "type": infer_kind(name, note),
            "angle": angle,
            "distance_to_object": distance,
            "adjustable": ("可调" in note) or any("可调" in x for x in labels),
            "position": comp.get("position", ""),
            "source": "connection" if labels else "note",
        })
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--force", action="store_true", help="已有 light_spec_list 也覆盖")
    args = ap.parse_args()
    root = Path(args.dir)
    n = 0
    for js in sorted(root.glob("*.json")):
        try:
            data = json.loads(js.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[skip] {js.name}: {e}")
            continue
        if data.get("light_spec_list") and not args.force:
            print(f"[skip] {js.name} 已有 VLM light_spec_list")
            continue
        specs = light_specs(data)
        data["light_spec_list"] = specs
        js.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if specs:
            n += 1
            print(f"{js.name}: " + " | ".join(
                f"{s['name']} angle={s['angle'] or '-'} dist={s['distance_to_object'] or '-'} adj={s['adjustable']}"
                for s in specs))
    print(f"\nupdated {n} files with light specs")


if __name__ == "__main__":
    main()
