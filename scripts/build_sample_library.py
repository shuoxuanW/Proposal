"""生成示例图片库：为每种设备类型绘制占位图 + sidecar 元数据。

用法：python scripts/build_sample_library.py
真实图片库接入：把你的图片按 目录名=设备类型 放进 data/image_library/<类型>/，
并在同目录放同名 .json 元数据即可（见 image_library.py 顶部说明）。
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "data" / "image_library"

FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
]


def _font(size: int):
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                pass
    return ImageFont.load_default()


SAMPLES = {
    "light_source": [
        ("红色环形光源", "#d9534f", {"类型": "环形光", "颜色": "红", "外径": "90mm"},
         "用于工件表面缺陷检测，低角度环形照明，突出划痕与凹坑。", ["环形光", "红色"]),
        ("白色条形光源", "#8a8a8a", {"类型": "条形光", "颜色": "白", "长度": "200mm"},
         "高均匀度条形照明，适合大幅面检测。", ["条形光", "白色"]),
    ],
    "lens": [
        ("25mm定焦镜头", "#5bc0de", {"焦距": "25mm", "接口": "C口", "靶面": "2/3\""},
         "C接口定焦镜头，适配2/3英寸500万像素相机。", ["定焦", "C口"]),
        ("0.5x远心镜头", "#428bca", {"倍率": "0.5x", "工作距": "110mm"},
         "双侧远心镜头，低畸变，适合高精度测量。", ["远心", "低畸变"]),
    ],
    "camera": [
        ("500万像素面阵相机", "#5cb85c", {"分辨率": "2448x2048", "帧率": "35fps", "接口": "GigE"},
         "黑白面阵相机，全局快门，适合在线检测。", ["面阵", "黑白", "GigE"]),
        ("1200万像素面阵相机", "#449d44", {"分辨率": "4096x3000", "帧率": "10fps", "接口": "USB3"},
         "高分辨率彩色面阵相机，适合细节检测。", ["面阵", "彩色", "USB3"]),
    ],
    "controller": [
        ("四路视觉控制器", "#f0ad4e", {"接口": "GigE x4", "输出": "IO x16"},
         "多相机视觉控制器，集成图像处理与IO输出。", ["控制器", "多相机"]),
    ],
    "ipc": [
        ("工业视觉工控机", "#6f42c1", {"CPU": "i7", "内存": "32G", "接口": "PCIe x4"},
         "工业级视觉主机，运行视觉软件与算法。", ["工控机", "视觉主机"]),
    ],
    "output": [
        ("PLC输出模块", "#d9534f", {"点数": "16DI/16DO", "通讯": "EtherCAT"},
         "接收视觉判定结果，驱动剔除/分拣机构。", ["PLC", "IO"]),
    ],
    "accessory": [
        ("频闪光源控制器", "#7f7f7f", {"通道": "4通道", "触发": "24V"},
         "为光源提供恒流/频闪驱动。", ["光源控制器", "频闪"]),
    ],
}


def make_image(name: str, color: str, size=(320, 240)) -> Image.Image:
    img = Image.new("RGB", size, "#f7f9fb")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([24, 24, size[0] - 24, size[1] - 24], radius=18, fill=color)
    d.rounded_rectangle([56, 56, size[0] - 56, size[1] - 56], radius=12, fill="#ffffff")
    f1 = _font(30)
    f2 = _font(18)
    d.text((size[0] // 2, size[1] // 2 - 22), name, font=f1, fill="#222222", anchor="mm")
    d.text((size[0] // 2, size[1] // 2 + 22), "设备示意图（占位）", font=f2, fill="#888888", anchor="mm")
    return img


def main() -> None:
    count = 0
    for dtype, items in SAMPLES.items():
        sub = LIB / dtype
        sub.mkdir(parents=True, exist_ok=True)
        for (name, color, params, desc, tags) in items:
            stem = name.replace(" ", "")
            img_path = sub / f"{stem}.png"
            make_image(name, color).save(img_path)
            meta = {
                "device_type": dtype,
                "name": name,
                "brand": "示例品牌",
                "description": desc,
                "params": params,
                "tags": tags,
            }
            (sub / f"{stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            count += 1
    print(f"示例图片库已生成：{count} 张 -> {LIB}")


if __name__ == "__main__":
    main()