"""
核心数据模型（Pydantic）：定义 5 个 Agent 之间传递的结构化对象。

这些是 Agent 之间的“合同”——每个 Agent 的输入输出都是这些对象，
保证流程清晰、可校验、可序列化（proposal.json）。
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

DeviceType = Literal["light_source", "lens", "camera", "controller", "ipc", "output", "accessory"]


class DevicePick(BaseModel):
    """需求解析得到的设备条目。"""
    device_type: str
    label: str = ""                 # 图中显示名，如“光源”
    spec_hint: str = ""             # 选型要求
    quantity: int = 1


class Chapter(BaseModel):
    """方案书中的一个章节。content 里可含 [[FIG:xx]] / [[DEV:fig:node]] 锚点。"""
    id: str
    title: str
    content: str = ""
    fig_refs: list[str] = Field(default_factory=list)   # 引用了哪些图
    dev_refs: list[str] = Field(default_factory=list)   # 引用了哪些设备节点


class DiagramNode(BaseModel):
    """设备框架图里的节点（仅框架图用；光路/产品/检测图不用节点）。"""
    id: str
    device_type: str
    label: str
    spec_hint: str = ""
    image_rel: Optional[str] = None   # 相对图片库根目录的图片路径
    image_meta: dict = Field(default_factory=dict)


class DiagramSpec(BaseModel):
    """图规格：framework=设备框架图；optic=光路布局示意图（由文本参数绘制）。"""
    id: str
    kind: str = "framework"
    title: str
    nodes: list[DiagramNode] = Field(default_factory=list)
    edges: list[list[str]] = Field(default_factory=list)   # [from_node_id, to_node_id]
    description: str = ""
    optic_spec: Any = None        # kind=optic 时：OpticLayoutSpec
    station_spec: Any = None      # kind=station 时：StationLayoutSpec（大模型推理的工位布局）
    meta: dict = Field(default_factory=dict)   # workpiece/detection 等其它图参数


class OpticLayoutSpec(BaseModel):
    """打光/光路成像布局示意图规格（机位、形状、尺寸、照片都在这）。"""
    camera_label: str = "工业相机"
    camera_note: str = "竖直安装"
    lens_label: str = "镜头"
    object_label: str = "待检测工件"          # 蓝色检测物
    light_label: str = "条形光源"
    light_color: str = "白色"
    platform_label: str = "基准平台"
    tilt_min: float = 15
    tilt_max: float = 45
    tilt_shown: float = 30
    lens_to_object: str = "49mm"             # 镜头端面到检测物垂直距离
    light_height: str = "20mm"               # 光源底部到基准平台高度
    optical_path_label: str = "成像光路"
    # 机位/形状/照片（由需求理解，非固定）
    camera_position: str = "上方"             # 上方 / 右上方 / 左上方
    light_position: str = "左侧"              # 左侧 / 右侧 / 两侧 / 同轴
    workpiece_shape: str = "矩形"             # 矩形 / 环形 / 圆形
    camera_photo: Optional[str] = None        # 图片库中相机照片相对路径
    light_photo: Optional[str] = None         # 图片库中光源照片相对路径


class DiagramArtifact(BaseModel):
    """绘图 Agent 产出的图（已渲染成文件）。"""
    spec_id: str
    title: str
    kind: str
    png_rel: str
    svg_rel: str
    nodes: list[DiagramNode] = Field(default_factory=list)
    caption: str = ""


class Issue(BaseModel):
    """校验问题。"""
    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    anchor_id: Optional[str] = None


class VerifyReport(BaseModel):
    """校验报告。passed = 无 error 级别问题。"""
    passed: bool
    issues: list[Issue] = Field(default_factory=list)


class RequirementChecklist(BaseModel):
    """结构化需求清单（7 类，多轮对话逐类补齐；missing 记录缺失字段供追问）。"""
    scene: str = ""                        # 1 项目场景
    detection_object: str = ""             # 2 检测对象
    defect_types: list[str] = Field(default_factory=list)     # 3 缺陷类型
    device_requirements: list[str] = Field(default_factory=list)  # 4 设备要求
    structure_requirements: list[str] = Field(default_factory=list)  # 5 结构要求
    optic_requirements: str = ""           # 6 光路要求
    delivery_requirements: str = ""        # 7 交付要求
    missing: list[str] = Field(default_factory=list)          # 缺失字段

    def check_missing(self) -> list[str]:
        """返回缺失字段名（供多轮对话追问）。"""
        missing = []
        if not self.scene:
            missing.append("项目场景")
        if not self.detection_object:
            missing.append("检测对象")
        if not self.defect_types:
            missing.append("缺陷类型")
        if not self.device_requirements:
            missing.append("设备要求")
        if not self.structure_requirements:
            missing.append("结构要求")
        if not self.optic_requirements:
            missing.append("光路要求")
        if not self.delivery_requirements:
            missing.append("交付要求")
        self.missing = missing
        return missing


class TaskPlan(BaseModel):
    """需求解析 Agent 输出（整个流程的总计划）。"""
    project_name: str = "机器视觉解决方案"
    requirement_summary: str = ""
    detection_target: str = ""      # 检测对象
    key_metrics: dict = Field(default_factory=dict)   # 精度/速度/工作距/视场
    devices: list[DevicePick] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    diagrams: list[DiagramSpec] = Field(default_factory=list)
    # PPT 模板所需字段
    customer_name: str = ""
    product_name: str = ""
    product_size: str = ""
    requirements: list[str] = Field(default_factory=list)
    tech_window: str = ""
    checklist: "RequirementChecklist" = Field(default_factory=lambda: RequirementChecklist())
    selection_advice: list[str] = Field(default_factory=list)  # 模型生成的选型建议（去硬编码）
    layout_reasoning: dict = Field(default_factory=dict)  # 工位布局推理自检结果 {status, reason, alternatives}
    case_constraints: dict = Field(default_factory=dict)  # 命中案例提取的关键参数/设备/光路约束


class Proposal(BaseModel):
    """最终方案书。"""
    project_name: str
    requirement_summary: str
    chapters: list[Chapter]
    diagrams: list[DiagramArtifact]
    report: VerifyReport = Field(default_factory=lambda: VerifyReport(passed=True))

# ---------- 2D 工位架构图（坐标式，非模板化，由大模型推理生成） ----------
class StationCamera(BaseModel):
    """工位中的一台相机。坐标 x∈[-5,5], y∈[0,6]，工件在 (0,0.5) 附近。"""
    label: str = "工业相机"
    x: float = 0.0
    y: float = 5.0
    orientation: str = "down"     # down=竖直俯视 / side=侧面
    lens: str = "镜头"
    resolution: str = ""          # 例如 2000万像素
    photo: Optional[str] = None   # 图片库匹配到的相机照片相对路径


class StationLight(BaseModel):
    """工位中的一处光源。angle=倾斜角(度)，光照向被测物。"""
    label: str = "条形光源"
    x: float = -3.0
    y: float = 1.0
    angle: float = 25.0
    angle_label: str = ""          # 图中明确标注的角度/范围，如 45°、30-60°、65±5°
    distance: str = ""             # 光源到被测物的距离，如 40±5mm
    direction: str = ""            # 出光朝向：right/left/down/up，必须朝工件
    kind: str = "条形"             # 条形/环形/同轴/面光
    photo: Optional[str] = None   # 图片库匹配到的光源照片相对路径


class StationUnit(BaseModel):
    """单个检测工位：独立工件 + 相机 + 光源，避免多工位共用一套坐标。"""
    name: str = "工位1"
    detection: str = ""
    accuracy: str = ""
    working_distance: str = ""
    fov: str = ""
    workpiece_shape: str = "矩形"     # 矩形/环形/圆形
    workpiece_label: str = "被测物"
    workpiece_size: str = ""
    cameras: list[StationCamera] = Field(default_factory=list)
    lights: list[StationLight] = Field(default_factory=list)
    notes: str = ""


class StationLayoutSpec(BaseModel):
    """2D 工位架构图规格：相机、光源、被测物的相对位置（由大模型推理）。"""
    camera_count: int = 1
    workpiece_shape: str = "矩形"     # 矩形/环形/圆形
    workpiece_label: str = "被测物"
    workpiece_size: str = ""
    cameras: list[StationCamera] = Field(default_factory=list)
    lights: list[StationLight] = Field(default_factory=list)
    stations: list[StationUnit] = Field(default_factory=list)  # 多工位时优先使用
    notes: str = ""                 # 布局推理说明
