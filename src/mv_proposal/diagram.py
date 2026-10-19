"""框架图渲染：把设备节点（框+嵌入图片库图片）按光路/数据链路连线，导出 PNG/SVG。

纯 matplotlib 实现，无 graphviz 依赖；节点图片来自图片库检索结果。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

from .models import DiagramSpec, StationUnit

_FONT_CANDIDATES = ["Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC", "DejaVu Sans"]


def setup_chinese_font() -> None:
    plt.rcParams["font.sans-serif"] = _FONT_CANDIDATES
    plt.rcParams["axes.unicode_minus"] = False


def _load_image(path: Path | None, fallback_label: str) -> Any:
    """读取图片（可选 PIL），失败返回 None。"""
    if path and Path(path).exists():
        try:
            from PIL import Image
            return Image.open(path).convert("RGBA")
        except Exception:
            return None
    return None


def _load_photo(path: Path | None, fallback_label: str) -> Any:
    """读取知识库模板图并裁掉透明留白，保证不同模板的视觉比例一致。"""
    img = _load_image(path, fallback_label)
    if img is None:
        return None
    try:
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
    except Exception:
        pass
    return img


def _group_of(cfg, device_type: str) -> str:
    return cfg.device_types.get(device_type, {}).get("group", "capture")


def _group_label(cfg, key: str) -> str:
    for g in cfg.framework_groups:
        if g.get("key") == key:
            return g.get("label", key)
    return key


def _layout_nodes(cfg, spec: DiagramSpec) -> tuple[dict[str, tuple[float, float]], dict[str, tuple[float, float]]]:
    """返回 node_id -> (x,y) 与 group_key -> (x_center, y_top, y_bottom)。数据坐标。"""
    groups: dict[str, list] = {}
    for n in spec.nodes:
        groups.setdefault(_group_of(cfg, n.device_type), []).append(n)

    # 列顺序：优先 capture/process/execute，其余追加
    order = [g["key"] for g in cfg.framework_groups]
    for k in groups:
        if k not in order:
            order.append(k)

    col_w = 3.2
    row_h = 2.2
    x0 = 1.5
    y_top = 9.0

    positions: dict[str, tuple[float, float]] = {}
    group_boxes: dict[str, tuple[float, float, float]] = {}
    for ci, gkey in enumerate(order):
        nodes = groups.get(gkey, [])
        if not nodes:
            continue
        x = x0 + ci * col_w
        n = len(nodes)
        ys = []
        for ri, node in enumerate(nodes):
            y = y_top - (ri + 0.5) * row_h
            positions[node.id] = (x, y)
            ys.append(y)
        group_boxes[gkey] = (x, y_top, ys[-1] - 0.9)

    return positions, group_boxes


def render_framework(spec: DiagramSpec, cfg, image_root: Path, out_dir: Path) -> tuple[str, str, dict]:
    """渲染框架图，返回 (png_rel, svg_rel, positions)。"""
    setup_chinese_font()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    positions, group_boxes = _layout_nodes(cfg, spec)

    xs = [p[0] for p in positions.values()] or [0]
    ys = [p[1] for p in positions.values()] or [0]
    fig_w = max(8.0, max(xs) - min(xs) + 5.0)
    fig_h = max(6.0, max(ys) - min(ys) + 5.0)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    # 分组背景框
    for gkey, (gx, gytop, gybot) in group_boxes.items():
        gx0, gx1 = gx - 1.45, gx + 1.45
        gy0, gy1 = gybot - 0.15, gytop + 0.55
        ax.add_patch(FancyBboxPatch(
            (gx0, gy0), gx1 - gx0, gy1 - gy0,
            boxstyle="round,pad=0.25,rounding_size=0.2",
            facecolor="#f2f6fb", edgecolor="#b9c9dd", linewidth=1.2, zorder=0,
        ))
        ax.text(gx, gy1 + 0.15, _group_label(cfg, gkey), ha="center", va="bottom",
                fontsize=12, color="#2c5f8a", weight="bold")

    box_w, box_h = 2.6, 2.0
    for node in spec.nodes:
        x, y = positions[node.id]
        # 节点框
        ax.add_patch(FancyBboxPatch(
            (x - box_w / 2, y - box_h / 2), box_w, box_h,
            boxstyle="round,pad=0.08,rounding_size=0.15",
            facecolor="white", edgecolor="#5b8bc4", linewidth=1.8, zorder=2,
        ))
        # 嵌入图片
        img_path = None
        if node.image_rel:
            img_path = Path(image_root) / node.image_rel
        img = _load_image(img_path, node.label)
        if img is not None:
            oi = OffsetImage(img, zoom=1.0)
            oi.image.axes = ax
            ab = AnnotationBbox(oi, (x, y + 0.32), frameon=False, box_alignment=(0.5, 0.5), zorder=3)
            ax.add_artist(ab)
            # 自适应缩放图片到节点框内
            _fit_offset_image(oi, img, box_w * 0.62, box_h * 0.58)
        else:
            ax.text(x, y + 0.32, "（无图）", ha="center", va="center", fontsize=9, color="#999", zorder=3)
        # 节点标题
        ax.text(x, y - 0.52, node.label, ha="center", va="center", fontsize=11, weight="bold",
                color="#1c3d5a", zorder=4)
        # 型号/规格提示
        hint = node.image_meta.get("name", "") if node.image_meta else ""
        if hint:
            ax.text(x, y - 0.80, hint, ha="center", va="center", fontsize=7.5, color="#666", zorder=4)

    # 连线（箭头）
    node_map = {n.id: n for n in spec.nodes}
    for a, b in spec.edges:
        if a in positions and b in positions:
            (x1, y1), (x2, y2) = positions[a], positions[b]
            # 跨列用水平箭头，同列用垂直箭头
            if abs(x2 - x1) > abs(y2 - y1):
                sx, ex = x1 + box_w / 2, x2 - box_w / 2
                sy, ey = y1, y2
            else:
                sx, ex = x1, x2
                sy, ey = y1 - box_h / 2, y2 + box_h / 2
            ax.add_patch(FancyArrowPatch(
                (sx, sy), (ex, ey), arrowstyle="-|>", mutation_scale=18,
                linewidth=1.6, color="#e07b39", zorder=1,
            ))

    ax.set_xlim(min(xs) - 2.2, max(xs) + 2.2)
    ax.set_ylim(min(ys) - 2.2, max(ys) + 2.2)
    ax.set_aspect("equal")
    ax.axis("off")
    plt.tight_layout(pad=0.6)

    png_path = out_dir / f"{spec.id}.png"
    svg_path = out_dir / f"{spec.id}.svg"
    fig.savefig(png_path, dpi=cfg.image_dpi, bbox_inches="tight", facecolor="white")
    fig.savefig(svg_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # 归一化坐标（用于图文联动定位）
    norm = {}
    if positions:
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        for nid, (x, y) in positions.items():
            norm[nid] = [
                round((x - xmin) / max(xmax - xmin, 1e-6), 4),
                round((y - ymin) / max(ymax - ymin, 1e-6), 4),
            ]
    (out_dir / f"{spec.id}.positions.json").write_text(
        json.dumps(norm, ensure_ascii=False, indent=2), encoding="utf-8")

    return f"{spec.id}.png", f"{spec.id}.svg", norm


def _fit_offset_image(oi: OffsetImage, img, max_w: float, max_h: float) -> None:
    """按数据坐标近似缩放图片到节点框内，保持宽高比（经验缩放，可按需微调）。"""
    w_in, h_in = img.width, img.height
    if w_in <= 0 or h_in <= 0:
        return
    px_per_data = 72.0   # 经验值：1 个数据单位约等于 72 像素
    zoom = min(max_w * px_per_data / w_in, max_h * px_per_data / h_in) * 0.92
    oi.set_zoom(zoom)


def render(spec: DiagramSpec, cfg, image_root: Path, out_dir: Path) -> tuple[str, str, dict]:
    if spec.kind == "process":
        # 流程框图：水平排布（复用 framework 布局，忽略分组列）
        return render_framework(spec, cfg, image_root, out_dir)
    return render_framework(spec, cfg, image_root, out_dir)



def render_optic_layout(spec, out_dir: Path, image_root: Path | None = None,
                        dpi: int = 150, style: dict | None = None, name: str = "optic_layout") -> tuple[str, str]:
    """按需求理解绘制打光成像布局：机位可变（相机上方/右上/左上，光源左/右/两侧/同轴），
    产品形状可变（矩形/环形/圆形），并嵌入图片库中的真实设备照片。"""
    import numpy as np
    from matplotlib.patches import Circle, FancyBboxPatch, Rectangle, Arc

    style = style or {}
    c_platform = style.get("platform_color", "#3c3c3c")
    c_path = style.get("optical_path_color", "#d62728")
    c_obj = style.get("object_color", "#4a90d9")
    c_illu = style.get("illumination_color", "#e8a020")
    c_angle = style.get("angle_color", "#e07b39")
    c_dim = style.get("dimension_color", "#555555")

    setup_chinese_font()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10.6, 6.8))
    ax.set_aspect("equal")

    # ---- 基准平台 ----
    ax.plot([-5.0, 5.0], [0.0, 0.0], color=c_platform, lw=3.2, zorder=1)
    ax.text(-5.0, -0.35, spec.platform_label, fontsize=11, color="#333")

    # ---- 相机+工件组 水平偏移 ----
    off = {"上方": 0.0, "右上方": 1.6, "左上方": -1.6}.get(spec.camera_position, 0.0)
    cam_x = off

    # ---- 工件（形状按需求）----
    obj_cy = 0.55
    shape = getattr(spec, "workpiece_shape", "矩形")
    if shape == "环形":
        ax.add_patch(Circle((cam_x, obj_cy), 0.55, facecolor=c_obj, edgecolor="#1f5c99", lw=2.2, zorder=3))
        ax.add_patch(Circle((cam_x, obj_cy), 0.30, facecolor="white", edgecolor="#1f5c99", lw=1.4, zorder=4))
    elif shape == "圆形":
        ax.add_patch(Circle((cam_x, obj_cy), 0.50, facecolor=c_obj, edgecolor="#1f5c99", lw=2.2, zorder=3))
    else:
        ax.add_patch(FancyBboxPatch((cam_x - 0.55, obj_cy - 0.32), 1.1, 0.64,
                     boxstyle="round,pad=0.04,rounding_size=0.1", facecolor=c_obj,
                     edgecolor="#1f5c99", lw=2.0, zorder=3))
    ax.text(cam_x, obj_cy, spec.object_label, color="white", fontsize=9.5, weight="bold",
            ha="center", va="center", zorder=5)

    # ---- 相机（嵌入真实照片）+ 镜头 ----
    lens_bottom = 4.1
    lens_h = 0.5
    cam_h = 1.5
    ax.add_patch(FancyBboxPatch((cam_x - 0.5, lens_bottom), 1.0, lens_h,
                 boxstyle="round,pad=0.03,rounding_size=0.06", facecolor="#f0f0f0",
                 edgecolor="#333", lw=1.4, zorder=6))
    ax.text(cam_x, lens_bottom + lens_h / 2, spec.lens_label, ha="center", va="center", fontsize=9.5, zorder=7)
    cam_cy = lens_bottom + lens_h + cam_h / 2
    cam_img = _load_image(Path(image_root) / spec.camera_photo, spec.camera_label) if (image_root and spec.camera_photo) else None
    if cam_img is not None:
        _embed_image(ax, cam_img, cam_x, cam_cy, 1.9, 1.8)
    else:
        ax.add_patch(FancyBboxPatch((cam_x - 0.55, lens_bottom + lens_h), 1.1, cam_h,
                     boxstyle="round,pad=0.03,rounding_size=0.06", facecolor="#ffffff",
                     edgecolor="#333", lw=1.6, zorder=6))
        ax.text(cam_x, cam_cy, spec.camera_label, ha="center", va="center", fontsize=9, weight="bold", zorder=7)
    ax.text(cam_x, lens_bottom + lens_h + cam_h + 0.18, f"{spec.camera_label}（{spec.camera_note}）",
            ha="center", va="bottom", fontsize=8.5, color="#555", zorder=7)

    # ---- 成像光路 ----
    y_bot = obj_cy + 0.35
    ax.plot([cam_x, cam_x], [y_bot, lens_bottom], linestyle=(0, (5, 4)), color=c_path, lw=1.6, zorder=2)
    ax.annotate("", xy=(cam_x, y_bot), xytext=(cam_x, lens_bottom + 0.02),
                arrowprops=dict(arrowstyle="-|>", color=c_path, lw=1.6), zorder=2)
    ax.text(cam_x + 0.16, (y_bot + lens_bottom) / 2, spec.optical_path_label, fontsize=8.5, color=c_path, va="center")

    # ---- 光源（位置可变 + 嵌入真实照片）----
    lp = getattr(spec, "light_position", "左侧")
    light_positions = []
    if lp == "两侧":
        light_positions = ["左", "右"]
    elif lp == "同轴":
        light_positions = []   # 同轴画在光路周围
    elif lp == "右侧":
        light_positions = ["右"]
    else:
        light_positions = ["左"]

    for side in light_positions:
        sign = -1 if side == "左" else 1
        lx = cam_x + sign * 2.7
        ly = 1.2
        th = np.radians(spec.tilt_shown)
        # 光源条（倾斜）
        L, lw = 1.8, 0.30
        R = np.array([[np.cos(sign * th), -np.sin(sign * th)], [np.sin(sign * th), np.cos(sign * th)]])
        corners = (np.array([[0, -lw/2], [L, -lw/2], [L, lw/2], [0, lw/2]]) @ R.T) + np.array([lx, ly])
        from matplotlib.patches import Polygon
        ax.add_patch(Polygon(corners, closed=True, facecolor="#fafafa", edgecolor="#333", lw=1.4, zorder=3))
        # 灯珠
        for k in (0.25, 0.5, 0.75):
            sx = lx + L * k * np.cos(sign * th); sy = ly + L * k * np.sin(sign * th)
            ax.scatter([sx], [sy], s=10, color="#ffd966", edgecolor="#b8860b", lw=0.3, zorder=4)
        # 照明光线
        ax.plot([lx + L * np.cos(sign * th), cam_x - sign * 0.5], [ly + L * np.sin(sign * th), obj_cy + 0.2],
                color=c_illu, lw=1.1, linestyle=(0, (3, 3)), alpha=0.9, zorder=2)
        # 光源照片（若库里有对应照片）
        light_img = _load_image(Path(image_root) / spec.light_photo, spec.light_label) if (image_root and spec.light_photo) else None
        label = f"{spec.light_color}{spec.light_label}"
        if light_img is not None:
            _embed_image(ax, light_img, lx + sign * 0.5, ly + 0.9, 1.5, 1.2)
        ax.text(lx + L / 2 * np.cos(sign * th), ly + L / 2 * np.sin(sign * th) + 0.35,
                label, ha="center", va="bottom", fontsize=8.5, color="#333", zorder=6)
        # 角度弧
        ax.add_patch(Arc((lx, ly), 1.6, 1.6, angle=0, theta1=0, theta2=spec.tilt_shown * sign,
                         color=c_angle, lw=1.2, zorder=2))

    if lp == "同轴":
        # 同轴光：光路周围的环
        ax.add_patch(Circle((cam_x, (y_bot + lens_bottom) / 2), 0.5, fill=False,
                            edgecolor=c_angle, lw=1.6, zorder=3))
        ax.text(cam_x + 0.6, (y_bot + lens_bottom) / 2, f"{spec.light_color}{spec.light_label}",
                fontsize=8.5, color="#b45f06", va="center")

    # ---- 尺寸标注 ----
    def dim_v(xd, y0, y1, label):
        ax.annotate("", xy=(xd, y1), xytext=(xd, y0), arrowprops=dict(arrowstyle="<->", color=c_dim, lw=1.1))
        ax.text(xd + 0.10, (y0 + y1) / 2, label, fontsize=9, color="#333", va="center")
    x_dim = 4.6
    ax.plot([cam_x, x_dim], [lens_bottom, lens_bottom], color="#999", lw=0.7, linestyle=":")
    ax.plot([cam_x, x_dim], [y_bot, y_bot], color="#999", lw=0.7, linestyle=":")
    dim_v(x_dim, y_bot, lens_bottom, spec.lens_to_object)

    # 光源底部高度
    if light_positions:
        lx = cam_x - 2.7 if "左" in light_positions else cam_x + 2.7
        dim_v(lx - 0.9, 0.0, 1.2, spec.light_height)

    # 角度标注
    if light_positions and spec.tilt_max:
        ax.text(cam_x - 2.9, 2.2, f"{int(spec.tilt_min)}°~{int(spec.tilt_max)}° 可调",
                fontsize=8.5, color="#b45f06")

    ax.set_xlim(-5.6, 5.6)
    ax.set_ylim(-0.8, 6.4)
    ax.axis("off")
    plt.tight_layout(pad=0.4)

    png_path = out_dir / f"{name}.png"
    svg_path = out_dir / f"{name}.svg"
    fig.savefig(png_path, dpi=dpi, bbox_inches="tight", facecolor="white")
    fig.savefig(svg_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return f"{name}.png", f"{name}.svg"


def _embed_image(ax, img, cx, cy, max_w, max_h, border: bool = True):
    """把设备照片精确嵌入到数据坐标 (cx, cy)，保持宽高比，不扭曲。返回 (宽, 高)。"""
    import numpy as np
    from matplotlib.patches import Rectangle
    arr = np.asarray(img.convert("RGBA"))
    h, w = arr.shape[:2]
    aspect = h / w
    ww = max_w
    hh = max_w * aspect
    if hh > max_h:
        hh = max_h
        ww = max_h / aspect
    ax.imshow(arr, extent=[cx - ww / 2, cx + ww / 2, cy - hh / 2, cy + hh / 2],
              zorder=8, aspect="auto")
    if border:
        ax.add_patch(Rectangle((cx - ww / 2, cy - hh / 2), ww, hh, fill=False,
                               edgecolor="#888888", lw=1.0, zorder=9))
    return ww, hh


def render_workpiece(name: str, size: str, out_dir: Path, dpi: int = 150,
                     fname: str = "workpiece", shape: str | None = None) -> tuple[str, str]:
    """产品/工件示意图：形状由模型给定(环形/圆形/矩形)，未给定则按名称关键词推断。"""
    import re
    import numpy as np
    from matplotlib.patches import Circle, FancyBboxPatch

    setup_chinese_font()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(5.4, 4.2))
    ax.set_aspect("equal")

    blob = f"{name} {size}"
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", size or "")]
    # 形状：模型显式给定优先，否则关键词推断
    if shape == "环形":
        is_ring, is_circle = True, False
    elif shape == "圆形":
        is_ring, is_circle = False, True
    elif shape == "矩形":
        is_ring, is_circle = False, False
    else:
        is_ring = bool(re.search(r"[Φφ环圈盘]", blob))
        is_circle = bool(re.search(r"[圆球药片瓶盖]", blob))

    if is_ring:
        R, r = 1.6, 0.95
        ax.add_patch(Circle((0, 0), R, facecolor="#dbeaf7", edgecolor="#1f5c99", lw=2.2, zorder=2))
        ax.add_patch(Circle((0, 0), r, facecolor="white", edgecolor="#1f5c99", lw=1.5, zorder=3))
        ax.text(0, 0, name or "工件", ha="center", va="center", fontsize=12, weight="bold", color="#1f3a5f", zorder=4)
        dim = f"外径 {nums[0]:g}mm" if nums else size
        if len(nums) >= 2:
            dim += f" / 内径 {nums[1]:g}mm"
        ax.text(0, -R - 0.35, dim or size or "", ha="center", va="top", fontsize=9.5, color="#555")
    elif is_circle:
        R = 1.5
        ax.add_patch(Circle((0, 0), R, facecolor="#dbeaf7", edgecolor="#1f5c99", lw=2.2, zorder=2))
        ax.text(0, 0, name or "工件", ha="center", va="center", fontsize=12, weight="bold", color="#1f3a5f", zorder=4)
        dim = f"直径 {nums[0]:g}mm" if nums else size
        ax.text(0, -R - 0.35, dim or size or "", ha="center", va="top", fontsize=9.5, color="#555")
    else:
        w, h = 2.5, 1.5
        ax.add_patch(FancyBboxPatch((-w/2, -h/2), w, h, boxstyle="round,pad=0.06,rounding_size=0.12",
                                    facecolor="#dbeaf7", edgecolor="#1f5c99", lw=2.2, zorder=2))
        ax.text(0, 0, name or "工件", ha="center", va="center", fontsize=12, weight="bold", color="#1f3a5f", zorder=4)
        dim = f"{nums[0]:g} x {nums[1]:g}mm" if len(nums) >= 2 else (size or "")
        ax.text(0, -h/2 - 0.35, dim, ha="center", va="top", fontsize=9.5, color="#555")

    ax.set_xlim(-2.4, 2.4)
    ax.set_ylim(-2.3, 2.1)
    ax.set_title("产品示意图", fontsize=13, color="#1f3a5f")
    ax.axis("off")
    plt.tight_layout(pad=0.4)
    png = out_dir / f"{fname}.png"
    svg = out_dir / f"{fname}.svg"
    fig.savefig(png, dpi=dpi, bbox_inches="tight", facecolor="white")
    fig.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return f"{fname}.png", f"{fname}.svg"


def render_detection(object_label: str, fov: str, regions: list[str], out_dir: Path,
                     dpi: int = 150, fname: str = "detection") -> tuple[str, str]:
    """检测示意图（俯视图）：相机俯视 + 视场范围 + 工件 + 检测点标注。"""
    import numpy as np
    from matplotlib.patches import Circle, FancyBboxPatch, Rectangle

    setup_chinese_font()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(5.4, 4.8))
    ax.set_aspect("equal")

    # 相机（俯视，顶部）
    ax.add_patch(Rectangle((-0.62, 3.55), 1.24, 1.1, facecolor="#ffffff", edgecolor="#333", lw=1.6, zorder=3))
    ax.add_patch(Circle((0, 3.4), 0.26, facecolor="#1f5c99", edgecolor="#333", lw=1.2, zorder=4))
    ax.text(0, 5.05, "相机（俯视）", ha="center", va="center", fontsize=11, weight="bold", color="#1f3a5f")
    # 光路虚线
    ax.plot([0, 0], [3.1, 2.15], linestyle=(0, (5, 4)), color="#d62728", lw=1.5, zorder=2)
    ax.annotate("", xy=(0, 2.15), xytext=(0, 3.1), arrowprops=dict(arrowstyle="-|>", color="#d62728", lw=1.5), zorder=2)

    # 视场范围
    ax.add_patch(Rectangle((-1.55, -1.0), 3.1, 2.1, fill=False, edgecolor="#28a745", lw=1.4,
                           linestyle=(0, (4, 3)), zorder=2))
    ax.text(1.62, 0.15, f"视场 {fov}", ha="left", va="center", fontsize=9.5, color="#28a745")

    # 工件（俯视）
    ax.add_patch(FancyBboxPatch((-0.72, -0.42), 1.44, 0.84, boxstyle="round,pad=0.04,rounding_size=0.1",
                                facecolor="#dbeaf7", edgecolor="#1f5c99", lw=1.8, zorder=3))
    ax.text(0, 0, object_label or "工件", ha="center", va="center", fontsize=10, weight="bold", color="#1f3a5f", zorder=4)

    # 检测点
    pts = [(-0.42, 0.18), (0.42, 0.18), (-0.42, -0.18), (0.42, -0.18)]
    for i in range(min(len(regions), len(pts))):
        px, py = pts[i]
        ax.plot(px, py, marker="x", color="#d9534f", markersize=11, markeredgewidth=2.2, zorder=5)
        ax.text(px + 0.14, py + 0.14, f"{i + 1}", fontsize=9, color="#d9534f", zorder=5)
    # 图例
    if regions:
        legend = "；".join(f"{i+1}.{r}" for i, r in enumerate(regions[:4]))
        ax.text(0, -1.55, legend, ha="center", va="top", fontsize=8.5, color="#555", wrap=True)

    ax.set_xlim(-2.3, 2.9)
    ax.set_ylim(-1.9, 5.4)
    ax.set_title("检测示意图（俯视图）", fontsize=13, color="#1f3a5f")
    ax.axis("off")
    plt.tight_layout(pad=0.4)
    png = out_dir / f"{fname}.png"
    svg = out_dir / f"{fname}.svg"
    fig.savefig(png, dpi=dpi, bbox_inches="tight", facecolor="white")
    fig.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return f"{fname}.png", f"{fname}.svg"


def _wrap_cn(text: str, width: int, max_lines: int = 2, ellipsis: bool = True) -> str:
    """按字符宽度换行：型号/数字单位作为整体，不在 MV-CS200 / 130±20mm 中间断开。"""
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-_./+±×°%]*|[\u4e00-\u9fff]+|\s+|[^\s]", text)
    lines: list[str] = []
    cur = ""
    for tok in tokens:
        if tok.isspace():
            if cur and not cur.endswith(" "):
                cur += " "
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", tok) and len(tok) > width:
            for i in range(0, len(tok), width):
                seg = tok[i:i + width]
                if not cur or len(cur) + len(seg) <= width:
                    cur += seg
                else:
                    lines.append(cur.rstrip())
                    cur = seg
            continue
        if not cur or len(cur) + len(tok) <= width:
            cur += tok
        else:
            lines.append(cur.rstrip())
            cur = tok
    if cur:
        lines.append(cur.rstrip())
    if len(lines) > max_lines:
        if ellipsis:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip("，,、；;") + "…"
        else:
            lines = lines[:max_lines - 1] + ["".join(lines[max_lines - 1:])]
    # 避免行尾孤零零的左括号、行首孤零零的右括号
    for i in range(len(lines) - 1):
        if lines[i].endswith(("（", "(")):
            lines[i] = lines[i][:-1].rstrip()
            lines[i + 1] = lines[i].endswith("（") and lines[i + 1] or ("（" + lines[i + 1])
        if lines[i + 1].startswith(("）", ")")):
            lines[i] += "）"
            lines[i + 1] = lines[i + 1][1:]
    return "\n".join(lines)

def _unit_signature(u: StationUnit):
    return (
        u.detection, u.accuracy, u.working_distance, u.fov,
        u.workpiece_shape, u.workpiece_label, u.workpiece_size,
        tuple((c.label, c.x, c.y, c.orientation, c.lens) for c in u.cameras),
        tuple((l.label, l.x, l.y, l.angle, l.direction, l.kind) for l in u.lights),
    )


def _station_units(spec) -> list[StationUnit]:
    units = list(getattr(spec, "stations", []) or [])
    if not units:
        units = [StationUnit(
            name="检测工位",
            detection=getattr(spec, "notes", "") or "",
            workpiece_shape=getattr(spec, "workpiece_shape", "矩形"),
            workpiece_label=getattr(spec, "workpiece_label", "被测物"),
            workpiece_size=getattr(spec, "workpiece_size", ""),
            cameras=list(getattr(spec, "cameras", []) or []),
            lights=list(getattr(spec, "lights", []) or []),
        )]

    # 相邻且配置完全相同的工位合并为一个面板，避免“工位1/工位2复制粘贴”的观感
    groups: list[tuple[StationUnit, list[str]]] = []
    for u in units:
        if groups and _unit_signature(u) == _unit_signature(groups[-1][0]):
            groups[-1][1].append(u.name)
        else:
            groups.append((u.model_copy(deep=True), [u.name]))
    merged: list[StationUnit] = []
    for u, names in groups:
        if len(names) > 1:
            u.name = " / ".join(names)
            tag = f"（{len(names)}套相同配置）"
            if tag not in u.detection:
                u.detection = (u.detection + tag).strip()
        merged.append(u)
    return merged


def _draw_workpiece(ax, unit: StationUnit) -> None:
    from matplotlib.patches import Circle, FancyBboxPatch, Rectangle
    import re

    cx, cy = 0.0, 0.62
    shape = getattr(unit, "workpiece_shape", "矩形") or "矩形"
    if shape == "环形":
        ax.add_patch(Circle((cx, cy), 0.82, facecolor="#4a90d9", edgecolor="#1f5c99", lw=1.8, zorder=4))
        ax.add_patch(Circle((cx, cy), 0.46, facecolor="white", edgecolor="#1f5c99", lw=1.1, zorder=5))
    elif shape == "圆形":
        ax.add_patch(Circle((cx, cy), 0.82, facecolor="#4a90d9", edgecolor="#1f5c99", lw=1.8, zorder=4))
    else:
        ax.add_patch(FancyBboxPatch((cx - 0.86, cy - 0.35), 1.72, 0.70,
                                    boxstyle="round,pad=0.02,rounding_size=0.08",
                                    facecolor="#4a90d9", edgecolor="#1f5c99", lw=1.8, zorder=4))
        ax.add_patch(Rectangle((cx - 0.86, cy - 0.35), 1.72, 0.70, fill=False,
                               edgecolor="#1f5c99", lw=1.8, zorder=4))

    label = _wrap_cn(getattr(unit, "workpiece_label", "被测物"), 8, 1)
    ax.text(cx, cy, label, color="white", fontsize=8, weight="bold",
            ha="center", va="center", zorder=6)

    # 按检测项里的「N处」画特征孔，增加图纸与需求的对应关系
    det_text = getattr(unit, "detection", "") or ""
    idx_match = re.search(r"第\s*([\d、,，\s]+)\s*处", det_text)
    if idx_match:
        counts = [len(re.findall(r"\d+", idx_match.group(1)))]
    else:
        counts = [int(n) for n in re.findall(r"(\d+)\s*处", det_text)]
    if counts and shape == "矩形":
        groups = min(len(counts), 2)
        for gi in range(groups):
            n = min(counts[gi], 6)
            xs = [-0.52 + (0.30 * i) for i in range(min(n, 3))] if gi == 0 else [0.28 + (0.20 * i) for i in range(min(n, 3))]
            for i in range(n):
                col = i // 3
                row = i % 3
                px = xs[row] if gi == 0 else 0.28 + 0.18 * row
                py = cy + (0.14 if col == 0 else -0.14)
                r = 0.045 if gi == 0 else 0.032
                ax.add_patch(Circle((px, py), r, facecolor="#f7fbff", edgecolor="#1f5c99",
                                    lw=0.8, zorder=7))
        det = getattr(unit, "detection", "") or ""
        n1 = "牙套孔" if "牙套" in det else "特征"
        n2 = "小孔" if ("小孔" in det or "毛边" in det) else "特征"
        if len(counts) == 1 and n2 != "特征":
            n1 = n2
        ax.text(-0.54, cy + 0.27, f"{counts[0]}×{n1}", ha="center", va="center",
                fontsize=6.0, color="#eaf4ff", zorder=8)
        if len(counts) > 1:
            ax.text(0.54, cy + 0.27, f"{counts[1]}×{n2}", ha="center", va="center",
                    fontsize=6.0, color="#eaf4ff", zorder=8)

    if getattr(unit, "workpiece_size", ""):
        ax.text(cx, cy - 0.52, str(unit.workpiece_size), ha="center", va="top",
                fontsize=7.2, color="#52667a", zorder=6)


def _camera_direction(cam, obj_x: float = 0.0) -> int:
    """-1=镜头朝左，1=镜头朝右；侧视相机必须朝向工件中心。"""
    return -1 if float(getattr(cam, "x", 0.0)) > obj_x else 1


def _draw_camera_vector(ax, cam) -> tuple[float, float, str, int]:
    """无知识库照片时的矢量兜底：返回 (镜头端点x, 镜头端点y, 朝向, 方向)。"""
    from matplotlib.patches import FancyBboxPatch, Polygon, Rectangle

    cx, cy = float(cam.x), float(cam.y)
    orient = getattr(cam, "orientation", "down")
    label = _wrap_cn(getattr(cam, "label", "工业相机"), 12, 2, ellipsis=False)
    lens = _wrap_cn(getattr(cam, "lens", ""), 16, 3, ellipsis=False)
    resolution = _wrap_cn(getattr(cam, "resolution", ""), 10, 1)

    if orient == "side":
        direction = _camera_direction(cam)
        ax.add_patch(FancyBboxPatch((cx - 0.32, cy - 0.52), 0.64, 1.04,
                                    boxstyle="round,pad=0.02,rounding_size=0.06",
                                    facecolor="#34495e", edgecolor="#1f2d3d", lw=1.2, zorder=9))
        base_x = cx + direction * 0.30
        tip_x = cx + direction * 0.62
        ax.add_patch(Polygon([[base_x, cy - 0.18], [tip_x, cy - 0.28],
                              [tip_x, cy + 0.28], [base_x, cy + 0.18]],
                             closed=True, facecolor="#5d6d7e", edgecolor="#1f2d3d", lw=1.0, zorder=10))
        ax.text(cx, cy + 0.78, label, ha="center", va="bottom", fontsize=7.6,
                color="#23384d", weight="bold", zorder=11)
        text_x = cx - direction * 0.55
        text_ha = "left" if direction < 0 else "right"
        if resolution:
            ax.text(text_x, cy + 0.16, resolution, ha=text_ha, va="center", fontsize=6.4,
                    color="#52667a", zorder=11)
        if lens:
            ax.text(text_x, cy - 0.18, lens, ha=text_ha, va="center", fontsize=6.8,
                    color="#52667a", zorder=11)
        return tip_x, cy, orient, direction

    ax.add_patch(FancyBboxPatch((cx - 0.45, cy + 0.02), 0.90, 0.52,
                                boxstyle="round,pad=0.02,rounding_size=0.07",
                                facecolor="#34495e", edgecolor="#1f2d3d", lw=1.2, zorder=9))
    ax.add_patch(FancyBboxPatch((cx - 0.18, cy - 0.40), 0.36, 0.42,
                                boxstyle="round,pad=0.01,rounding_size=0.04",
                                facecolor="#5d6d7e", edgecolor="#1f2d3d", lw=1.0, zorder=10))
    ax.add_patch(Rectangle((cx - 0.22, cy - 0.46), 0.44, 0.08,
                           facecolor="#8fa6bb", edgecolor="#1f2d3d", lw=0.7, zorder=11))
    ax.text(cx, cy + 0.70, label, ha="center", va="bottom", fontsize=7.6,
            color="#23384d", weight="bold", zorder=11)
    if resolution:
        ax.text(cx + 0.58, cy + 0.26, resolution, ha="left", va="center", fontsize=6.4,
                color="#52667a", zorder=11)
    if lens:
        ax.text(cx + 0.58, cy - 0.20, lens, ha="left", va="center", fontsize=6.8,
                color="#52667a", zorder=11)
    return cx, cy - 0.46, orient, 0


def _draw_camera_photo(ax, cam, image_root: Path | None):
    """用知识库真实相机模板拼图；侧视相机按左/右位置旋转，镜头始终朝向工件。"""
    if not image_root or not getattr(cam, "photo", None):
        return None
    img = _load_photo(Path(image_root) / str(cam.photo), getattr(cam, "label", "相机"))
    if img is None:
        return None

    cx, cy = float(cam.x), float(cam.y)
    orient = getattr(cam, "orientation", "down")
    label = _wrap_cn(getattr(cam, "label", "工业相机"), 12, 2, ellipsis=False)
    lens = _wrap_cn(getattr(cam, "lens", ""), 16, 3, ellipsis=False)
    resolution = _wrap_cn(getattr(cam, "resolution", ""), 10, 1)

    if orient == "side":
        direction = _camera_direction(cam)
        # 模板默认镜头朝下；逆时针转90°→朝右，顺时针转90°→朝左
        # 实测模板：+90°→镜头朝左，-90°→镜头朝右；按相机在工件的左侧/右侧选择
        img = img.rotate(-90 if direction > 0 else 90, expand=True)
        ww, hh = _embed_image(ax, img, cx, cy, 1.05, 0.98, border=False)
        tip_x = cx + direction * (ww / 2)
        ax.text(cx, cy + hh / 2 + 0.10, label, ha="center", va="bottom", fontsize=7.4,
                color="#23384d", weight="bold", zorder=11)
        text_x = cx - direction * 0.55
        text_ha = "left" if direction < 0 else "right"
        if resolution:
            ax.text(text_x, cy + 0.16, resolution, ha=text_ha, va="center", fontsize=6.4,
                    color="#52667a", zorder=11)
        if lens:
            ax.text(text_x, cy - 0.18, lens, ha=text_ha, va="center", fontsize=6.8,
                    color="#52667a", zorder=11)
        return tip_x, cy, orient, direction

    ww, hh = _embed_image(ax, img, cx, cy, 0.95, 0.82, border=False)
    tip_y = cy - hh / 2
    ax.text(cx, cy + hh / 2 + 0.10, label, ha="center", va="bottom", fontsize=7.4,
            color="#23384d", weight="bold", zorder=11)
    text_x = cx + ww / 2 + 0.12
    if resolution:
        ax.text(text_x, cy + 0.10, resolution, ha="left", va="center", fontsize=6.4,
                color="#52667a", zorder=11)
    if lens:
        ax.text(text_x, cy - 0.24, lens, ha="left", va="center", fontsize=6.8,
                color="#52667a", zorder=11)
    return cx, tip_y, orient, 0


def _light_angle_value(light) -> float:
    """把 45°、45°±15°、30-60°、65±5° 归一化成一个大概倾角。"""
    label = str(getattr(light, "angle_label", "") or "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-~至]\s*(\d+(?:\.\d+)?)\s*°", label)
    if m:
        return max(0.0, min(90.0, (float(m.group(1)) + float(m.group(2))) / 2))
    m = re.search(r"(\d+(?:\.\d+)?)\s*°?\s*±", label)
    if m:
        return max(0.0, min(90.0, float(m.group(1))))
    m = re.search(r"(\d+(?:\.\d+)?)\s*°", label)
    if m:
        return max(0.0, min(90.0, float(m.group(1))))
    try:
        return max(0.0, min(90.0, float(getattr(light, "angle", 0) or 0)))
    except Exception:
        return 0.0


def _light_direction(light) -> str:
    """出光朝向：优先用智能体给出的 direction，缺失时按光源在工件左/右侧推断。"""
    d = str(getattr(light, "direction", "") or "").lower()
    if "right" in d or "右" in d:
        return "right"
    if "left" in d or "左" in d:
        return "left"
    if "up" in d or "上" in d:
        return "up"
    if "down" in d or "下" in d:
        return "down"
    x = float(getattr(light, "x", 0.0))
    if x < 0:
        return "right"
    if x > 0:
        return "left"
    return "down"


def _light_rotation(light) -> float:
    """把出光方向转换成图标旋转角：右侧出光逆时针，左侧出光顺时针。"""
    angle = _light_angle_value(light)
    d = _light_direction(light)
    if d == "right":
        return angle
    if d == "left":
        return -angle
    return 0.0


def _light_label_text(light) -> str:
    """光源标注：名称 + 角度 + 光源到工件距离（有标注才显示）。"""
    parts = [_wrap_cn(getattr(light, "label", "工业光源"), 18, 2, ellipsis=False)]
    angle = str(getattr(light, "angle_label", "") or getattr(light, "angle_range", "") or "").strip()
    if angle:
        parts.append(_wrap_cn(f"角度 {angle}", 18, 2, ellipsis=False))
    distance = str(getattr(light, "distance", "") or "").strip()
    if distance:
        parts.append(_wrap_cn(f"距工件 {distance}", 18, 2, ellipsis=False))
    return "\n".join(parts)


def _draw_light_rays(ax, light, x: float, y: float, rot: float) -> None:
    """按光源倾角画照明光线：起点沿光源长轴分布，终点落在工件上表面。"""
    import math
    color = "#e8a020"
    a = math.radians(rot)
    # 光源下表面中心（局部坐标 (0,-0.10) 绕光源中心旋转）
    sx = x + 0.10 * math.sin(a)
    sy = y - 0.10 * math.cos(a)
    for off in (-0.32, 0.0, 0.32):
        ox = off * math.cos(a)
        oy = off * math.sin(a)
        ax.plot([sx + ox, off * 1.1], [sy + oy, 0.98], color=color,
                lw=0.9, ls=(0, (3, 3)), alpha=0.55, zorder=3)


def _draw_light_vector(ax, light) -> None:
    from matplotlib.patches import Arc, Ellipse, FancyBboxPatch, Rectangle
    from matplotlib.transforms import Affine2D

    x, y = float(light.x), float(light.y)
    kind = str(getattr(light, "kind", "环形") or "环形")
    label = _light_label_text(light)
    color = "#e8a020"
    rot = _light_rotation(light)
    trans = Affine2D().rotate_deg_around(x, y, rot) + ax.transData

    if "圆顶" in kind or "穹" in kind:
        ax.add_patch(Arc((x, y), 0.95, 0.85, theta1=0, theta2=180,
                         color=color, lw=2.0, zorder=8, transform=trans))
        ax.plot([x - 0.48, x + 0.48], [y, y], color=color, lw=2.0, zorder=8, transform=trans)
    elif "条形" in kind:
        ax.add_patch(Rectangle((x - 0.44, y - 0.10), 0.88, 0.20,
                               facecolor="#fff4dc", edgecolor=color, lw=1.6,
                               zorder=8, transform=trans))
    elif "同轴" in kind:
        ax.add_patch(Rectangle((x - 0.30, y - 0.22), 0.60, 0.44,
                               facecolor="#fff4dc", edgecolor=color, lw=1.6,
                               zorder=8, transform=trans))
        ax.add_patch(Ellipse((x, y), 0.24, 0.16, facecolor="white", edgecolor=color,
                             lw=1.2, zorder=9, transform=trans))
    elif "面光" in kind or "背光" in kind:
        ax.add_patch(FancyBboxPatch((x - 0.46, y - 0.16), 0.92, 0.32,
                                    boxstyle="round,pad=0.01,rounding_size=0.03",
                                    facecolor="#fff4dc", edgecolor=color, lw=1.5,
                                    zorder=8, transform=trans))
    else:
        ax.add_patch(Ellipse((x, y), 0.86, 0.34, fill=False, edgecolor=color,
                             lw=2.0, zorder=8, transform=trans))
        ax.add_patch(Ellipse((x, y), 0.48, 0.15, fill=False, edgecolor=color,
                             lw=1.2, zorder=8, transform=trans))

    if abs(x) < 0.15:
        # 中心同轴/背光：标注放到右侧，避免和相机 WD 标注混在一起
        ax.text(x + 0.55, y + 0.10, label, ha="left", va="center",
                fontsize=6.8, color="#9a6412", linespacing=1.15, zorder=10)
    else:
        ha = "right" if x < 0 else "left"
        ax.text(x + (-0.44 if x < 0 else 0.44), y + 0.34, label,
                ha=ha, va="bottom", fontsize=6.8, color="#9a6412", linespacing=1.15, zorder=10)
    _draw_light_rays(ax, light, x, y, rot)


def _draw_light_photo(ax, light, image_root: Path | None) -> bool:
    if not image_root or not getattr(light, "photo", None):
        return False
    img = _load_photo(Path(image_root) / str(light.photo), getattr(light, "label", "光源"))
    if img is None:
        return False
    x, y = float(light.x), float(light.y)
    label = _light_label_text(light)
    angle = _light_angle_value(light)
    rot = _light_rotation(light)
    if angle:
        img = img.rotate(rot, expand=True)
    ww, hh = _embed_image(ax, img, x, y, 0.95, 0.55, border=False)
    if abs(x) < 0.15:
        ax.text(x + ww / 2 + 0.15, y + 0.05, label, ha="left", va="center",
                fontsize=6.8, color="#9a6412", linespacing=1.15, zorder=10)
    else:
        ha = "right" if x < 0 else "left"
        ax.text(x + (-0.44 if x < 0 else 0.44), y + hh / 2 + 0.08, label,
                ha=ha, va="bottom", fontsize=6.8, color="#9a6412", linespacing=1.15, zorder=10)
    _draw_light_rays(ax, light, x, y, rot)
    return True


def _draw_station_panel(ax, unit: StationUnit, image_root: Path | None = None) -> None:
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon
    import numpy as np

    ax.set_xlim(-2.65, 2.65)
    ax.set_ylim(-1.15, 6.35)
    ax.set_aspect("equal")
    ax.axis("off")

    # 面板底与标题带
    ax.add_patch(FancyBboxPatch((-2.55, -1.05), 5.10, 7.25,
                                boxstyle="round,pad=0.02,rounding_size=0.10",
                                facecolor="#f8fafc", edgecolor="#d6e0ea", lw=1.0, zorder=0))
    ax.add_patch(FancyBboxPatch((-2.55, 5.18), 5.10, 1.02,
                                boxstyle="round,pad=0.02,rounding_size=0.10",
                                facecolor="#eaf2fb", edgecolor="#d6e0ea", lw=0.8, zorder=1))
    ax.plot([-2.55, 2.55], [5.18, 5.18], color="#c9d7e5", lw=0.8, zorder=2)
    ax.text(0, 5.88, str(unit.name or "检测工位"), ha="center", va="center",
            fontsize=11.5, weight="bold", color="#1f3a5f", zorder=3)
    det = _wrap_cn(unit.detection, 30, 2)
    if det:
        ax.text(0, 5.52, det, ha="center", va="center", fontsize=7.4,
                color="#486581", linespacing=1.25, zorder=3)

    # 基准平台 + 剖面线
    ax.plot([-2.25, 2.25], [0, 0], color="#3c4c5c", lw=2.2, zorder=2)
    for x in np.arange(-2.15, 2.16, 0.28):
        ax.plot([x, x - 0.07], [0, -0.11], color="#95a5a6", lw=0.6, zorder=1)
    ax.text(-2.25, -0.30, "基准平台", ha="left", va="top", fontsize=7.0, color="#5b6b7a", zorder=3)
    ax.add_patch(FancyBboxPatch((-2.20, 0.85), 4.10, 4.05,
                                boxstyle="round,pad=0.02,rounding_size=0.08",
                                facecolor="none", edgecolor="#b8c4d0", lw=0.8,
                                ls=(0, (5, 4)), zorder=1))
    ax.text(1.86, 4.82, "遮光罩", ha="right", va="bottom", fontsize=6.4, color="#8a99a8", zorder=2)

    _draw_workpiece(ax, unit)

    cameras = list(getattr(unit, "cameras", []) or [])
    lights = list(getattr(unit, "lights", []) or [])

    # 成像光轴 + 视场锥：真实知识库模板优先，缺失时才用矢量兜底
    lens_points = []
    for cam in cameras:
        photo = _draw_camera_photo(ax, cam, image_root)
        if photo is None:
            lx, ly, orient, direction = _draw_camera_vector(ax, cam)
        else:
            lx, ly, orient, direction = photo
        lens_points.append((lx, ly, orient, direction))

        if orient == "side":
            # 侧视：镜头朝向工件；工件靠近相机的一侧为视场落点
            target_x = -direction * 0.86
            target_y = 0.62  # 工件侧面中心
            ax.add_patch(Polygon([[lx, ly - 0.16], [lx, ly + 0.16],
                                  [target_x, target_y + 0.32], [target_x, target_y - 0.32]],
                                 closed=True, facecolor="#d62728", alpha=0.055,
                                 edgecolor="none", zorder=2))
            ax.plot([lx, target_x], [ly - 0.16, target_y - 0.32], color="#d62728", lw=0.7,
                    alpha=0.55, zorder=4)
            ax.plot([lx, target_x], [ly + 0.16, target_y + 0.32], color="#d62728", lw=0.7,
                    alpha=0.55, zorder=4)
            ax.annotate("", xy=(target_x, target_y), xytext=(lx, ly),
                        arrowprops=dict(arrowstyle="->", color="#d62728", lw=1.3,
                                        linestyle=(0, (5, 3))), zorder=6)
        else:
            ax.add_patch(Polygon([[lx - 0.18, ly], [lx + 0.18, ly],
                                  [0.86, 0.98], [-0.86, 0.98]],
                                 closed=True, facecolor="#d62728", alpha=0.055,
                                 edgecolor="none", zorder=2))
            ax.plot([lx - 0.18, -0.86], [ly, 0.98], color="#d62728", lw=0.7,
                    alpha=0.55, zorder=4)
            ax.plot([lx + 0.18, 0.86], [ly, 0.98], color="#d62728", lw=0.7,
                    alpha=0.55, zorder=4)
            ax.annotate("", xy=(0, 0.98), xytext=(lx, ly),
                        arrowprops=dict(arrowstyle="->", color="#d62728", lw=1.3,
                                        linestyle=(0, (5, 3))), zorder=6)

    for light in lights:
        if not _draw_light_photo(ax, light, image_root):
            _draw_light_vector(ax, light)

    # 工作距离标注（取第一台俯视相机）
    wd_cam = next((p for p in lens_points if p[2] == "down"), None)
    if wd_cam:
        _, ly, _, _ = wd_cam
        ax.add_patch(FancyArrowPatch((2.18, 0.98), (2.18, ly),
                                     arrowstyle="<->", mutation_scale=8,
                                     color="#7f8c8d", lw=0.8, zorder=7))
        wd = str(getattr(unit, "working_distance", "") or "").strip()
        txt = ("相机WD " + wd) if wd else "相机WD"
        ax.text(2.30, (0.98 + ly) / 2, _wrap_cn(txt, 14, 2, ellipsis=False), rotation=90,
                ha="center", va="center", fontsize=6.8, color="#5b6b7a", zorder=7)

    # 底部参数
    footer = []
    if getattr(unit, "accuracy", ""):
        footer.append("精度：" + str(unit.accuracy))
    if getattr(unit, "fov", ""):
        footer.append("视场：" + str(unit.fov))
    if footer:
        ax.text(-2.32, -0.55, "  |  ".join(footer), ha="left", va="top",
                fontsize=6.9, color="#486581", zorder=3)


def render_station_layout(spec, out_dir: Path, image_root: Path | None = None,
                          dpi: int = 150, name: str = "station") -> tuple[str, str]:
    """多工位 2D 架构图：每个工位独立面板，统一矢量图例，避免相机/光源堆叠。"""
    import math
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    setup_chinese_font()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    units = _station_units(spec)
    if not units:
        units = [StationUnit(name="检测工位")]
    n = len(units)
    ncols = min(n, 3)
    nrows = max(1, math.ceil(n / ncols))
    fig_w = 4.55 * ncols
    fig_h = 6.55 * nrows
    fig, axes = plt.subplots(nrows, ncols, figsize=(fig_w, fig_h), squeeze=False)
    for idx, unit in enumerate(units):
        r, c = divmod(idx, ncols)
        _draw_station_panel(axes[r][c], unit, image_root)
    for idx in range(n, nrows * ncols):
        r, c = divmod(idx, ncols)
        axes[r][c].axis("off")

    title = "多工位视觉检测光路布局示意" if n > 1 else "视觉检测光路布局示意"
    fig.suptitle(title, fontsize=15.5, weight="bold", color="#1f3a5f", y=0.985)
    note = _wrap_cn(getattr(spec, "notes", "") or "", 62, 1)
    if note:
        fig.text(0.5, 0.947, note, ha="center", va="top", fontsize=8.2, color="#6b7c8f")

    handles = [
        Line2D([0], [0], color="#d62728", lw=1.3, ls=(0, (5, 3)), label="成像光轴"),
        Line2D([0], [0], color="#e8a020", lw=1.0, ls=(0, (3, 3)), label="照明光线"),
        Patch(facecolor="#d62728", alpha=0.10, edgecolor="none", label="视场范围"),
        Line2D([0], [0], color="#3c4c5c", lw=2.2, label="基准平台"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False,
               fontsize=8.0, bbox_to_anchor=(0.5, 0.012), columnspacing=2.0, handlelength=2.4)

    fig.subplots_adjust(top=0.915 if note else 0.935, bottom=0.075,
                        left=0.02, right=0.98, wspace=0.06, hspace=0.10)
    png = out_dir / f"{name}.png"
    svg = out_dir / f"{name}.svg"
    fig.savefig(png, dpi=dpi, bbox_inches="tight", facecolor="white", pad_inches=0.12)
    fig.savefig(svg, bbox_inches="tight", facecolor="white", pad_inches=0.12)
    plt.close(fig)
    return f"{name}.png", f"{name}.svg"
