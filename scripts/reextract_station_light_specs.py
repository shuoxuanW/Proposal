"""用新版 VLM Prompt 重新读取已有工位图，回填 light_spec_list。

只更新光源专项字段和 note，保留原有 component/connection/meta，避免破坏检索。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mv_proposal.config import Config
from src.mv_proposal.vision import VLMClient, VLM_AGENT_PROMPT


def normalize_specs(specs: list[dict], note: str) -> list[dict]:
    unit_mm = ("单位：mm" in note) or ("unit: mm" in note.lower())
    for spec in specs:
        d = str(spec.get("distance_to_object") or "").strip()
        if d and "mm" not in d.lower() and unit_mm:
            spec["distance_to_object"] = d + "mm"
        spec["angle"] = str(spec.get("angle") or "").strip()
        spec["distance_to_object"] = str(spec.get("distance_to_object") or "").strip()
    return specs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "data" / "station_diagrams"))
    ap.add_argument("--only", default="", help="只处理文件名包含该字符串的图")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--retry", type=int, default=2)
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    cfg = Config.load()
    vlm = VLMClient(cfg.vlm_base_url, cfg.vlm_api_key, cfg.vlm_model)
    root = Path(args.dir)
    files = sorted(root.glob("*.png"))
    if args.only:
        files = [p for p in files if args.only in p.name]
    if args.limit:
        files = files[:args.limit]
    print(f"re-extract light specs: {len(files)} images", flush=True)

    ok = 0
    specs_total = 0
    for i, png in enumerate(files, 1):
        js = png.with_suffix(".json")
        if not js.exists():
            print(f"[{i}/{len(files)}] SKIP no json {png.name}", flush=True)
            continue
        old = json.loads(js.read_text(encoding="utf-8"))
        data = None
        err = ""
        for attempt in range(args.retry + 1):
            try:
                data = vlm.read_image(png, VLM_AGENT_PROMPT)
                if data and (data.get("component_list") or data.get("light_spec_list")):
                    break
                err = "empty VLM result"
            except Exception as e:
                err = str(e)
            if attempt < args.retry:
                time.sleep(1.5 * (attempt + 1))
        if not data:
            print(f"[{i}/{len(files)}] FAIL {png.name}: {err}", flush=True)
            continue

        new_specs = data.get("light_spec_list") or []
        old_specs = old.get("light_spec_list") or []
        if new_specs:
            new_specs = normalize_specs(new_specs, old.get("note", "") or data.get("note", ""))
            # 用旧结果补齐新 VLM 漏掉的角度/距离
            for ns in new_specs:
                for os in old_specs:
                    same_name = ns.get("name") and os.get("name") and (
                        ns["name"] in os["name"] or os["name"] in ns["name"])
                    same_type = ns.get("type") and os.get("type") and ns["type"] == os["type"]
                    if same_name or same_type:
                        if not ns.get("angle"):
                            ns["angle"] = os.get("angle", "")
                        if not ns.get("distance_to_object"):
                            ns["distance_to_object"] = os.get("distance_to_object", "")
                        break
            old["light_spec_list"] = new_specs
            specs_total += len(new_specs)
        # 相机工作距离（只取相机到被测物/平台的标注）
        cam_wd = str(data.get("camera_working_distance") or "").strip()
        if cam_wd:
            note_for_unit = old.get("note", "") or data.get("note", "")
            if "mm" not in cam_wd.lower() and (("单位：mm" in note_for_unit) or ("unit: mm" in note_for_unit.lower())):
                cam_wd += "mm"
            old["camera_working_distance"] = cam_wd
        if data.get("dimension_list"):
            old["dimension_list"] = data["dimension_list"]
        # 保留原 note（通常包含更多尺寸/型号信息），只在原 note 为空时使用新 note
        if data.get("note") and not old.get("note"):
            old["note"] = data["note"]
        meta = old.get("meta") or {}
        meta["drawing_type"] = data.get("drawing_type") or old.get("drawing_type", "")
        meta["reextracted_at"] = datetime.now().isoformat(timespec="seconds")
        meta["reextract_source"] = "VLM light_spec_list pass"
        old["meta"] = meta
        js.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
        ok += 1
        print(f"[{i}/{len(files)}] OK {png.name} specs={len(new_specs)}", flush=True)
        if args.sleep:
            time.sleep(args.sleep)
    print(f"done: {ok} updated, {specs_total} light specs", flush=True)


if __name__ == "__main__":
    main()
