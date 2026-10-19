"""
光路布局参数解析：从需求文本里提取相机/镜头/光源/检测物/机位/尺寸/角度。

这是“文本生成图纸”的关键：把自然语言描述变成可绘制的结构化参数。
"""
from __future__ import annotations

import re

from .models import OpticLayoutSpec


def extract_optic_layout(text: str, spec: OpticLayoutSpec | None = None) -> OpticLayoutSpec:
    spec = spec or OpticLayoutSpec()

    # 相机型号 + 安装方式
    m = re.search(r"([A-Za-z][A-Za-z0-9\-]{0,8})\s*工业相机", text)
    if m:
        spec.camera_label = f"{m.group(1)}工业相机"
    m = re.search(r"(竖直|水平|垂直|倾斜)\s*(安装|放置|俯视)", text)
    if m:
        spec.camera_note = m.group(0)

    # 镜头类型：双远心/远心/定焦/变焦/微距/FA
    m = re.search(r"((?:双)?远心|定焦|变焦|微距|[Ff][Aa])镜头", text)
    if m:
        spec.lens_label = m.group(1) + "镜头"

    # 光源：要求带颜色，避免误匹配“设备要求：光源”
    m = re.search(r"(白|红|蓝|绿|紫|橙|紫外|红外)(?:色)?\s*(条形|环形|同轴|面|点|线|穹顶|隧道|圆顶)?\s*(光源|光)", text)
    if m:
        color = m.group(1)
        spec.light_color = (color if color in ("紫外", "红外") else color + "色")
        spec.light_label = f"{m.group(2) or ''}{m.group(3)}"

    # 倾斜角度范围：15°~45°
    m = re.search(r"(\d+)\s*[°度]\s*[~～\-—至到]\s*(\d+)\s*[°度]?", text)
    if m:
        spec.tilt_min = int(m.group(1))
        spec.tilt_max = int(m.group(2))
        mid = (spec.tilt_min + spec.tilt_max) / 2
        spec.tilt_shown = mid if 5 <= mid <= 80 else 30

    # 镜头端面到检测物距离：找“垂直距离/垂直高度/镜头端面到”附近的 mm
    m = re.search(r"(?:垂直距离|垂直高度|镜头端面到)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*mm", text)
    if m:
        spec.lens_to_object = f"{m.group(1)}mm"

    # 光源底部到平台高度：找“底部距离/底部距/高度为”附近的 mm
    m = re.search(r"(?:底部距离|底部距|高度为|距离底层基准平台)[^0-9]{0,10}(\d+(?:\.\d+)?)\s*mm", text)
    if m:
        spec.light_height = f"{m.group(1)}mm"

    # 相机机位
    if re.search(r"右上|右上方|右上角", text):
        spec.camera_position = "右上方"
    elif re.search(r"左上|左上方|左上角", text):
        spec.camera_position = "左上方"
    else:
        spec.camera_position = "上方"

    # 光源机位
    if re.search(r"两侧|左右各|双侧", text):
        spec.light_position = "两侧"
    elif re.search(r"同轴", text):
        spec.light_position = "同轴"
    elif re.search(r"右侧|右边", text):
        spec.light_position = "右侧"
    else:
        spec.light_position = "左侧"

    # 产品形状
    if re.search(r"环形|圆环|垫片|法兰|轴承|内径", text):
        spec.workpiece_shape = "环形"
    elif re.search(r"圆|球|Φ|φ|直径|药片|瓶盖", text):
        spec.workpiece_shape = "圆形"
    else:
        spec.workpiece_shape = "矩形"

    # 检测物
    if re.search(r"蓝色", text):
        spec.object_label = "待检测工件"
    return spec