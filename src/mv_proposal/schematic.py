"""
结构化示意图渲染：把「component_list / connection_list / layout_direction」JSON
渲染成干净的 2D 原理示意图（PNG + SVG）。

契约与上游 VLM Agent 的输出对齐；本模块是确定性渲染（Agent② 的兜底实现），
「需求文本 → 结构 JSON」这一步由 LLM 生成（理解交给模型），图片解析由上游 VLM 做。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from matplotlib.patches import Circle, FancyBboxPatch

_FONTS = ["Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC", "DejaVu Sans"]

# 颜色规范
COLORS = {
    "red": "#d62728", "orange": "#e8a020", "black": "#222222",
    "gray": "#555555", "blue": "#4a90d9", "dark": "#1f5c99",
}


def _font() -> None:
    plt.rcParams["font.sans-serif"] = _FONTS
    plt.rcParams["axes.unicode_minus"] = False


def _box(ax, cx, cy, w, h, label, fill="#ffffff", edge="#333", lw=1.6, fs=10, bold=False, r=0.08):
    ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h,
                 boxstyle=f"round,pad=0.02,rounding_size={r}",
                 facecolor=fill, edgecolor=edge, lw=lw, zorder=5))
    ax.text(cx, cy, label, ha="center", va="center", fontsize=fs,
            weight="bold" if bold else "normal", color="#111", zorder=6)
    return (cx, cy, w, h)


def _embed_image(ax, img, cx, cy, max_w, max_h):
    """把透明底模板图精确嵌入数据坐标 (cx, cy)，保持宽高比。"""
    try:
        from PIL import Image
        im = Image.open(img).convert("RGBA")
    except Exception:
        return None
    box = OffsetImage(im, zoom=1.0)
    ab = AnnotationBbox(box, (cx, cy), frameon=False,
                        bboxprops=dict(boxstyle="square,pad=0"))
    ab._zoom = 1.0
    ax.add_artist(ab)
    # 用 AnnotationBbox 默认比例，再按目标尺寸缩放
    ax.draw_artist if False else None
    return ab


def _arrow(ax, x1, y1, x2, y2, color, style, label=None, lw=1.8, fs=9):
    ls = (0, (5, 4)) if style == "dashed" else "solid"
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw, linestyle=ls), zorder=3)
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2, label, ha="center", va="bottom",
                fontsize=fs, color=color, zorder=7, rotation=0)


def render_schematic(data: dict[str, Any], out_dir: Path, name: str = "schematic") -> tuple[str, str]:
    """把结构化 JSON 渲染成 PNG + SVG，返回 (png文件名, svg文件名)。"""
    _font()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    title = data.get("drawing_type", "示意图")
    direction = data.get("layout_direction", "TB")
    comps = data.get("component_list", [])
    conns = data.get("connection_list", [])

    # 布局：TB 光路图用形状定位；否则简单流式
    pos: dict[str, tuple[float, float]] = {}
    shape_of: dict[str, str] = {}

    # 形状映射
    def shape(c):
        return c.get("shape") or c.get("type") or "box"

    for c in comps:
        cname = c["name"]
        shape_of[cname] = shape(c)
        if "x" in c and "y" in c:
            pos[cname] = (float(c["x"]), float(c["y"]))

    if direction == "TB" and any(shape_of.get(n) in ("platform", "object", "camera") for n in shape_of):
        # 光路图专用布局：平台底 / 被测物中 / 相机顶 / 光源两侧
        for n, sh in shape_of.items():
            if n in pos:
                continue
            if sh == "platform":
                pos[n] = (0, 0.15)
            elif sh == "object":
                pos[n] = (0, 1.15)
            elif sh == "camera":
                pos[n] = (0, 4.4)
            elif sh == "lens":
                pos[n] = (0, 3.5)
            elif sh == "light":
                pos[n] = (-3.1, 1.5)
            elif sh == "light_right":
                pos[n] = (3.1, 1.5)
            else:
                pos[n] = (0, 2.6)
    else:
        # 流式布局
        step = 2.2
        for i, c in enumerate(comps):
            cname = c["name"]
            if cname in pos:
                continue
            pos[cname] = (i * step - (len(comps) - 1) * step / 2, 0) if direction == "LR" else (0, -i * 1.9)

    fig, ax = plt.subplots(figsize=(9.6, 6.4))
    ax.set_aspect("equal")

    # 绘制组件
    for c in comps:
        cname = c["name"]
        x, y = pos[cname]
        shape = shape_of[cname]
        if shape == "platform":
            ax.add_patch(FancyBboxPatch((-4.6, 0.0), 9.2, 0.30,
                         boxstyle="round,pad=0.02,rounding_size=0.06",
                         facecolor="#3c3c3c", edgecolor="#222", lw=1.4, zorder=2))
            ax.text(-4.5, -0.28, cname, ha="left", va="center", fontsize=10, color="#333")
        elif shape == "object":
            if "环形" in cname:
                ax.add_patch(Circle((x, y), 0.46, facecolor=COLORS["blue"], edgecolor=COLORS["dark"], lw=2.0, zorder=4))
                ax.add_patch(Circle((x, y), 0.24, facecolor="white", edgecolor=COLORS["dark"], lw=1.2, zorder=5))
            elif "圆形" in cname:
                ax.add_patch(Circle((x, y), 0.44, facecolor=COLORS["blue"], edgecolor=COLORS["dark"], lw=2.0, zorder=4))
            else:
                ax.add_patch(FancyBboxPatch((x - 0.52, y - 0.30), 1.04, 0.60,
                             boxstyle="round,pad=0.02,rounding_size=0.08",
                             facecolor=COLORS["blue"], edgecolor=COLORS["dark"], lw=1.8, zorder=4))
            ax.text(x, y, cname, ha="center", va="center", fontsize=9, weight="bold", color="white", zorder=6)
        elif shape == "light":
            _box(ax, x, y, 2.2, 0.55, cname, fill="#fff3cd", edge="#b8860b", lw=1.5, fs=9)
        elif shape == "light_right":
            _box(ax, x, y, 2.2, 0.55, cname, fill="#fff3cd", edge="#b8860b", lw=1.5, fs=9)
        elif shape == "lens":
            _box(ax, x, y, 1.2, 0.5, cname, fill="#f0f0f0", edge="#333", lw=1.4, fs=9)
        else:
            img = c.get("image")
            if img:
                _embed_image(ax, img, x, y, 1.7, 1.4)
                ax.text(x, y - 0.95, cname, ha="center", va="top", fontsize=9, color="#333", zorder=7)
            else:
                _box(ax, x, y, 1.7, 1.1, cname, fill="#ffffff", edge="#333", lw=1.6, fs=9.5)

    # 绘制连线
    for cn in conns:
        src, dst = cn["source"], cn["target"]
        if src not in pos or dst not in pos:
            continue
        x1, y1 = pos[src]
        x2, y2 = pos[dst]
        # 按组件形状微调起止点
        _arrow(ax, x1, y1, x2, y2, COLORS.get(cn.get("color", "black"), "#222"),
               cn.get("line_style", "solid"), cn.get("label"), lw=1.8)

    # 尺寸标注：镜头→被测物、光源高度
    note = data.get("note", "")
    if note:
        ax.text(4.7, 2.2, note, ha="left", va="center", fontsize=8, color="#777", wrap=True)

    ax.set_xlim(-5.4, 5.4)
    ax.set_ylim(-0.8, 5.6)
    ax.axis("off")
    ax.set_title(title, fontsize=13, pad=12)

    plt.tight_layout(pad=0.5)
    png = out_dir / f"{name}.png"
    svg = out_dir / f"{name}.svg"
    fig.savefig(png, dpi=150, bbox_inches="tight", facecolor="white")
    fig.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return f"{name}.png", f"{name}.svg"


def build_optic_json(ospec) -> dict[str, Any]:
    """从 OpticLayoutSpec 生成结构化 JSON（确定性兜底；LLM 可替代这一步）。"""
    shape = getattr(ospec, "workpiece_shape", "矩形")
    obj_name = "%s(%s)" % (ospec.object_label, shape)
    light_name = "%s%s" % (ospec.light_color, ospec.light_label)
    comps = [
        {"name": "工业相机", "shape": "camera"},
        {"name": "镜头", "shape": "lens"},
        {"name": obj_name, "shape": "object"},
        {"name": ospec.platform_label, "shape": "platform"},
    ]
    lp = getattr(ospec, "light_position", "左侧")
    if lp == "两侧":
        comps.append({"name": light_name + "(左)", "shape": "light", "x": -3.1, "y": 1.5})
        comps.append({"name": light_name + "(右)", "shape": "light_right", "x": 3.1, "y": 1.5})
    elif lp in ("右侧",):
        comps.append({"name": light_name, "shape": "light_right", "x": 3.1, "y": 1.5})
    else:
        comps.append({"name": light_name, "shape": "light", "x": -3.1, "y": 1.5})

    conns = [
        {"source": "工业相机", "target": "镜头", "line_style": "solid", "color": "black"},
        {"source": "镜头", "target": obj_name, "line_style": "dashed", "color": "red",
         "label": "%s\n%s" % (getattr(ospec, "optical_path_label", "成像光路"), ospec.lens_to_object)},
    ]
    for lname in [c["name"] for c in comps if c["shape"] in ("light", "light_right")]:
        conns.append({"source": lname, "target": obj_name, "line_style": "dashed", "color": "orange",
                      "label": "照明\n%g°" % float(getattr(ospec, "tilt_shown", 30))})

    note = "光源安装角度 %g°~%g° 可调；光源底部距平台 %s" % (
        float(getattr(ospec, "tilt_min", 15)), float(getattr(ospec, "tilt_max", 45)),
        getattr(ospec, "light_height", "20mm"))
    return {"drawing_type": "视觉检测工位光路示意图", "view_type": "2D侧视原理图",
            "layout_direction": "TB", "component_list": comps, "connection_list": conns, "note": note}
