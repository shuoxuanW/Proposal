"""
2D 工位架构图推理：让大模型根据结构化需求，自主推理相机数量/安装位置/光源布置，
输出「坐标式」布局 JSON（非模板化），再由绘图模块动态渲染。

能力自检：推理失败/未用 LLM 时返回 failed=True + 备选模型清单。
"""
from __future__ import annotations

from .models import StationCamera, StationLayoutSpec, StationLight, StationUnit

# 备选大模型清单（当 DeepSeek 无法完成布局推理时给出）
ALTERNATIVE_MODELS = [
    {"模型": "Qwen-Max（通义千问）", "说明": "中文理解强，结构化 JSON 输出稳定，适合中文工位布局推理"},
    {"模型": "GLM-4（智谱清言）", "说明": "中文逻辑推理强，支持 function calling 与 JSON 输出"},
    {"模型": "GPT-4o（OpenAI）", "说明": "综合推理最强，多模态可读图，适合复杂布局与图文校验"},
    {"模型": "Claude 3.5 Sonnet（Anthropic）", "说明": "长文本与结构化输出稳定，适合方案书撰写"},
]

_LAYOUT_PROMPT = (
    "你是工业视觉工位布局设计工程师。根据检测需求，自主推理工位数量、每工位相机与光源布置，"
    "输出 2D 工位架构 JSON，只输出 JSON 不要解释。\n"
    "【多工位拆分规则】需求里出现工位1/工位2/工位3，或存在多个独立检测项、多个拍摄面时，"
    "必须输出多个 station，每个 station 只包含自己的工件、相机和光源；"
    "禁止让多个工位共用同一个 workpiece，禁止把不同工位的相机/光源堆在同一个坐标场景中。\n"
    "【单工位坐标约定】每个工位使用独立坐标系：x -2.2~2.2，y 0~6；基准平台 y=0；工件中心 (0,0.6)。"
    "俯视相机放 (0,4.2)、orientation=down；侧面相机放 (±1.7,0.62)、orientation=side，"
    "光轴水平对准工件侧面中心，不要放到 y=2.8 的高位。"
    "每台侧视相机必须配一个同侧光源：相机在右(x>0)，光源也在右；相机在左(x<0)，光源也在左；"
    "光源 y 约 1.2~1.6，angle 为入射角；kind 用 环形/圆顶/条形/同轴/面光。"
    "direction 必须填写且朝向被测物：左侧斜射→right，右侧斜射→left，"
    "同轴/环形俯视→down，底部背光→up；禁止向外撇。方向不明确时按光源在工件左侧/右侧推断。"
    "同一工位有多台相机时用 x=-1.4/0/1.4 分散，不要重叠。\n"
    "【设备数量约束】每个工位默认只放 1 台俯视相机；只有需求明确要求多视角/多面同时拍摄时才增加相机。"
    "不得给单个检测项配置多个不相关光源；牙套/螺纹孔优先圆顶光，小孔毛边优先环形光。"
    "工作距离、视场、相机型号、镜头焦距优先从历史案例提取；历史案例没写就留空字符串，不要编造。"
    "如果给了历史工位图参考，优先复用它的部件类型、光源类型、布局方向与工作距离标注，但相机/光源数量与坐标必须满足当前需求。\n"
    "【输出格式】\n"
    '{"stations":[{"name":"工位1","detection":"检测项","accuracy":"0.008mm/pixel",'
    '"working_distance":"130±20mm","fov":"40×27mm",'
    '"workpiece":{"shape":"矩形","label":"金属加工件","size":"156×94mm"},'
    '"cameras":[{"label":"MV-CS200-10GM","x":0,"y":4.2,"orientation":"down","lens":"50mm FA","resolution":"2000万像素"}],'
    '"lights":[{"label":"白色圆顶光源","x":-1.2,"y":1.9,"angle":45,"kind":"圆顶"}],'
    '"notes":""}],"notes":"整体布局说明"}\n'
    "label 必须用需求里实际提到的具体型号/类型；需求没提具体型号才允许用「相机1」「光源1」这类泛化名。"
)


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _camera_from_dict(raw: dict) -> StationCamera:
    raw = dict(raw or {})
    orient = str(raw.get("orientation", "down")).lower()
    if "side" in orient or "侧" in orient:
        orient = "side"
    else:
        orient = "down"
    y = _clamp(raw.get("y"), 0.6, 5.6, 4.2)
    if orient == "side" and y > 1.2:
        y = 0.62  # 侧视相机必须与工件检测面同高，光轴才能水平
    return StationCamera(
        label=str(raw.get("label") or "工业相机"),
        x=_clamp(raw.get("x"), -2.2, 2.2, 0.0),
        y=y,
        orientation=orient,
        lens=str(raw.get("lens") or "工业镜头"),
        resolution=str(raw.get("resolution") or ""),
        photo=raw.get("photo"),
    )


def _light_from_dict(raw: dict) -> StationLight:
    raw = dict(raw or {})
    angle_raw = raw.get("angle")
    angle = _clamp(angle_raw, 0, 90, 45)
    angle_range = str(raw.get("angle_range") or "").strip()
    angle_label = angle_range or (f"{angle:g}°" if angle_raw is not None else "")
    distance = str(raw.get("distance") or raw.get("distance_to_object") or "").strip()
    kind = str(raw.get("kind") or "环形")
    d_raw = str(raw.get("direction") or "").lower()
    if "right" in d_raw or "右" in d_raw:
        direction = "right"
    elif "left" in d_raw or "左" in d_raw:
        direction = "left"
    elif "up" in d_raw or "上" in d_raw:
        direction = "up"
    elif "down" in d_raw or "下" in d_raw or "同轴" in kind:
        direction = "down"
    else:
        direction = ""
    x = _clamp(raw.get("x"), -2.2, 2.2, -1.2)
    y = _clamp(raw.get("y"), 0.7, 4.0, 1.9)
    # 条形/线光在工件左右两侧时，必须是右/左朝向工件；VLM/LLM 误写 down 也要纠正
    if "条形" in kind or "线光" in kind:
        if x < 0 and direction in ("", "down", "left"):
            direction = "right"
        elif x > 0 and direction in ("", "down", "right"):
            direction = "left"
    if not direction:
        if "背光" in kind and y < 1.0:
            direction = "up"
        elif "同轴" in kind or "环形" in kind or "圆顶" in kind or "面光" in kind or "背光" in kind:
            direction = "down"
        elif x < 0:
            direction = "right"
        elif x > 0:
            direction = "left"
        else:
            direction = "down"
    return StationLight(
        label=str(raw.get("label") or "工业光源"),
        x=x,
        y=y,
        angle=angle,
        angle_label=angle_label,
        distance=distance,
        direction=direction,
        kind=kind,
        photo=raw.get("photo"),
    )


def _station_from_dict(raw: dict, idx: int) -> StationUnit:
    raw = dict(raw or {})
    wp = raw.get("workpiece") or {}
    return StationUnit(
        name=str(raw.get("name") or f"工位{idx}"),
        detection=str(raw.get("detection") or ""),
        accuracy=str(raw.get("accuracy") or ""),
        working_distance=str(raw.get("working_distance") or ""),
        fov=str(raw.get("fov") or ""),
        workpiece_shape=str(wp.get("shape") or "矩形"),
        workpiece_label=str(wp.get("label") or "被测物"),
        workpiece_size=str(wp.get("size") or ""),
        cameras=[_camera_from_dict(c) for c in (raw.get("cameras") or []) if isinstance(c, dict)],
        lights=[_light_from_dict(l) for l in (raw.get("lights") or []) if isinstance(l, dict)],
        notes=str(raw.get("notes") or ""),
    )


def reason_station_layout(text: str, llm, case_text: str = "", station_ref: str = "") -> tuple[StationLayoutSpec | None, bool, str]:
    """
    让大模型推理工位布局。返回 (布局规格, 是否成功, 失败原因)。
    优先解析多工位 stations；旧格式（单工件 + cameras/lights）保持兼容。
    """
    if llm.is_mock:
        return None, False, "当前为离线 Mock 模式，未调用大模型推理"

    user = f"项目需求：\n{text}\n\n历史方案参考（只复用设备数量/工作距离/视场/光源类型，不要照抄客户名）：\n{case_text or '（无）'}"
    if station_ref:
        user += f"\n\n历史工位图参考（优先复用部件/连线/光源/工作距离，不要照抄客户名）：\n{station_ref}"
    data = llm.complete_json(_LAYOUT_PROMPT, user)
    if not data:
        return None, False, "大模型未返回有效布局 JSON"

    try:
        raw_stations = data.get("stations") or []
        stations = [_station_from_dict(st, i + 1) for i, st in enumerate(raw_stations)
                    if isinstance(st, dict)]
        if not stations:
            # 兼容旧格式
            wp = data.get("workpiece") or {}
            if not wp:
                return None, False, "大模型未返回有效布局 JSON（缺少工件信息）"
            stations = [StationUnit(
                name="检测工位",
                detection=str(data.get("detection") or ""),
                accuracy=str(data.get("accuracy") or ""),
                working_distance=str(data.get("working_distance") or ""),
                fov=str(data.get("fov") or ""),
                workpiece_shape=str(wp.get("shape") or "矩形"),
                workpiece_label=str(wp.get("label") or "被测物"),
                workpiece_size=str(wp.get("size") or ""),
                cameras=[_camera_from_dict(c) for c in (data.get("cameras") or []) if isinstance(c, dict)],
                lights=[_light_from_dict(l) for l in (data.get("lights") or []) if isinstance(l, dict)],
            )]

        first = stations[0]
        spec = StationLayoutSpec(
            camera_count=sum(len(st.cameras) for st in stations),
            workpiece_shape=first.workpiece_shape,
            workpiece_label=first.workpiece_label,
            workpiece_size=first.workpiece_size,
            cameras=first.cameras,
            lights=first.lights,
            stations=stations,
            notes=str(data.get("notes") or ""),
        )
        return spec, True, ""
    except Exception as e:
        return None, False, f"布局 JSON 解析失败：{e}"
