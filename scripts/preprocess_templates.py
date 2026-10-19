"""
素材预处理工具：把知识库里的设备示意图，统一处理成「可拼图」的模板。

处理步骤：
  1. 白底透明化（保留设备内部的白色，只去掉与边缘相连的背景）
  2. 裁剪到内容边界
  3. 缩放到标准尺寸 + 居中放到透明画布上
  4. 从文件名解析 设备类型/视角/角度/颜色，写 sidecar 元数据

用法：python -X utf8 scripts/preprocess_templates.py [输入目录] [输出目录]
默认：输入 D:/20261012/知识库数据，输出 D:/20261012/data/image_templates
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# 设备类型分类（与 src/mv_proposal/device_classify.py 一致）
DEVICE_RULES = [
    (["光源控制器", "频闪"], "accessory"),
    (["相机", "ccd", "cmos", "线扫", "面阵", "线阵"], "camera"),
    (["镜头", "远心", "lens"], "lens"),
    (["工控机", "工控"], "ipc"),
    (["显示器", "plc", "机器人", "机械手"], "output"),
    (["光源", "环形光", "条形光", "面光", "背光", "同轴", "线光", "隧道光", "圆顶", "点光", "无影", "照明", "打光"], "light_source"),
    (["滤镜", "偏振", "传感器", "编码器", "支架"], "accessory"),
]


def classify(name: str) -> str:
    blob = name.lower()
    for kws, dtype in DEVICE_RULES:
        for kw in kws:
            if kw.lower() in blob:
                return dtype
    return "accessory"


def extract_meta(stem: str, dtype: str) -> dict:
    """从文件名解析视角/角度/颜色。"""
    view = ""
    for v in ["正视图", "仰视图", "侧视图", "测视图", "俯视图"]:
        if v in stem:
            view = v.replace("测视图", "侧视图")
            break
    angle = ""
    m = re.search(r"(\d+)\s*°", stem)
    if m:
        angle = f"{m.group(1)}°"
    color = ""
    m = re.search(r"(白|红|蓝|绿|紫|橙|紫外|红外)", stem)
    if m:
        color = m.group(1)
    return {"device_type": dtype, "view": view, "angle": angle, "color": color}


def remove_white_background(img: Image.Image, threshold: int = 238) -> Image.Image:
    """把与边缘相连的白色背景设为透明，保留设备内部的白色。"""
    import numpy as np
    arr = np.array(img.convert("RGBA"))
    h, w = arr.shape[:2]
    is_bg = (arr[:, :, 0] >= threshold) & (arr[:, :, 1] >= threshold) & (arr[:, :, 2] >= threshold)

    visited = np.zeros((h, w), dtype=bool)
    stack = []
    # 从四边出发 flood fill
    for i in range(h):
        for j in (0, w - 1):
            if is_bg[i, j] and not visited[i, j]:
                visited[i, j] = True
                stack.append((i, j))
    for j in range(w):
        for i in (0, h - 1):
            if is_bg[i, j] and not visited[i, j]:
                visited[i, j] = True
                stack.append((i, j))
    while stack:
        i, j = stack.pop()
        for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < h and 0 <= nj < w and not visited[ni, nj] and is_bg[ni, nj]:
                visited[ni, nj] = True
                stack.append((ni, nj))
    arr[visited, 3] = 0
    return Image.fromarray(arr)


def normalize(img: Image.Image, max_size: int = 400, canvas: int = 480) -> Image.Image:
    """裁剪到内容 + 缩放 + 居中放到透明画布。"""
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    x = (canvas - img.width) // 2
    y = (canvas - img.height) // 2
    out.paste(img, (x, y), img)
    return out


def main(argv: list[str] | None = None) -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("D:/20261012/知识库数据")
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("D:/20261012/data/image_templates")
    dst.mkdir(parents=True, exist_ok=True)

    count = 0
    manifest = []
    for f in sorted(src.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in IMAGE_EXTS or f.name.startswith(("_", "~$")):
            continue
        try:
            img = Image.open(f)
            transparent = remove_white_background(img)
            normalized = normalize(transparent)
        except Exception as e:
            print(f"  跳过 {f.name}: {e}")
            continue

        # 设备类型：优先读同名 sidecar JSON 的 device_type，否则按文件名分类
        dtype = None
        sidecar = f.with_suffix(".json")
        if sidecar.exists():
            try:
                dtype = json.loads(sidecar.read_text(encoding="utf-8")).get("device_type")
            except Exception:
                dtype = None
        dtype = dtype or classify(f.stem)
        meta = extract_meta(f.stem, dtype)
        meta["source"] = str(f)
        out_dir = dst / dtype
        out_dir.mkdir(parents=True, exist_ok=True)
        out_png = out_dir / f"{f.stem}.png"
        normalized.save(out_png)
        (out_dir / f"{f.stem}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.append({"file": str(out_png.relative_to(dst)).replace("\\", "/"), **meta})
        count += 1

    (dst / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"预处理完成：{count} 张模板 -> {dst}")
    print(f"清单：{dst / 'manifest.json'}")


if __name__ == "__main__":
    main()