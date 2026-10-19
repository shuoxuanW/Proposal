"""
设备类型分类：按文本/文件名关键词判定（图片库与 PPT 导入共用）。

顺序即优先级——更具体的词在前（如“光源控制器”归 accessory 而不是 light_source）。
"""
from __future__ import annotations

DEVICE_RULES: list[tuple[list[str], str]] = [
    (["光源控制器", "频闪"], "accessory"),
    (["相机", "ccd", "cmos", "线扫", "面阵", "线阵"], "camera"),
    (["镜头", "远心", "lens"], "lens"),
    (["工控机", "工控"], "ipc"),
    (["显示器", "plc", "机器人", "机械手"], "output"),
    (["光源", "环形光", "条形光", "面光", "背光", "同轴", "线光", "隧道光", "圆顶", "点光", "无影", "照明", "打光"], "light_source"),
    (["滤镜", "偏振", "传感器", "编码器", "支架"], "accessory"),
]

DEVICE_LABELS: dict[str, str] = {
    "light_source": "光源", "lens": "镜头", "camera": "工业相机",
    "controller": "控制器/采集卡", "ipc": "工控机/视觉主机",
    "output": "执行输出", "accessory": "附件",
}


def classify_text(text: str, extra: str = "") -> str:
    """首个命中规则的类型；无命中归入 accessory。"""
    blob = f"{text} {extra}".lower()
    for kws, dtype in DEVICE_RULES:
        for kw in kws:
            if kw.lower() in blob:
                return dtype
    return "accessory"


def device_label(dtype: str) -> str:
    return DEVICE_LABELS.get(dtype, dtype)