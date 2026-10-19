"""给工位图 sidecar JSON 补充结构化元数据（可重复执行）。"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "station_diagrams"
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_./+]{1,}|[\u4e00-\u9fff]{2,}")


def project_from_stem(stem: str) -> str:
    return re.sub(r"[-_]+", " ", re.sub(r"_slide\d+$", "", stem)).strip()


def keywords_for(stem: str, data: dict) -> list[str]:
    parts = [stem, data.get("drawing_type", ""), data.get("view_type", ""), data.get("note", "")]
    for c in data.get("component_list", []):
        parts += [c.get("name", ""), c.get("position", "")]
    seen, out = set(), []
    for p in parts:
        for tok in TOKEN_RE.findall(str(p or "")):
            t = tok.strip("-_./+")
            if len(t) >= 2 and t not in seen:
                seen.add(t); out.append(t)
    return out[:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    args = ap.parse_args()
    root = Path(args.dir)
    n = 0
    for js in sorted(root.glob("*.json")):
        if js.name == "VERSION.json":
            continue
        try:
            data = json.loads(js.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[skip] {js.name}: {e}")
            continue
        stem = js.stem
        data["meta"] = {
            "schema_version": 1,
            "project": project_from_stem(stem),
            "drawing_type": data.get("drawing_type", ""),
            "keywords": keywords_for(stem, data),
            "source_file": stem + ".png",
        }
        js.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        n += 1
    print(f"enriched {n} sidecar JSON files in {root}")


if __name__ == "__main__":
    main()
