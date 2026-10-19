"""
VLM 图像解析（Agent①）：读图提取结构化布局 JSON，供 schematic 渲染。
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

VLM_AGENT_PROMPT = (
    "你是机器视觉知识库图像解析Agent。读取图片，提取图内全部视觉元素、部件、相对位置、标注、连线。\n"
    "严格只输出 JSON，不要自然语言、不要 markdown、不要解释。\n"
    'JSON 结构：{"drawing_type":"示意图类型","view_type":"2D侧视/2D俯视",'
    '"component_list":[{"name":"部件名称","position":"位置描述","parent_group":"所属分组或null"}],'
    '"connection_list":[{"source":"源部件","target":"目标部件","line_style":"solid/dashed","color":"颜色","label":"标注文字"}],'
    '"light_spec_list":[{"name":"光源名称","type":"环形/圆顶/条形/同轴/面光/背光","angle":"倾角或范围，如45°、30-60°、65±5°","distance_to_object":"光源到被测物距离，如40±5mm","direction":"left/right/down/up","adjustable":true或false,"position":"位置描述"}],'
    '"camera_working_distance":"相机到被测物的距离，如300±10mm","dimension_list":["图中所有尺寸/角度标注"],'
    '"layout_direction":"LR或TB","note":"图内其它文字标注，没有填空字符串"}\n'
    "规则：只提取相对位置关系，不要脑补尺寸数值；只识别原理图部件，忽略渲染瑕疵；"
    "光轴固定 red dashed，物料输送箭头 solid black；parent_group 用于子图分组，无则 null。\n"
    "光源专项规则：只提取图中明确标注的光源倾角和光源到被测物/产品的距离；没有标注就填空字符串，禁止猜测。"
    "不要把相机到光源的距离当成光源到工件的距离；优先使用“光源→被测物/产品/物料”连线上的标注。"
    "角度支持单值、公差和范围；有“可调”文字时 adjustable=true。"
    "direction 表示出光朝向：向工件右侧→right，向工件左侧→left，垂直向下→down，从下往上→up；不得输出背离工件的方向。"
    "camera_working_distance 只取相机到被测物/平台的标注，不要把光源到工件距离当成相机工作距离；没有标注就留空。"
)


def extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    m = re.search(r"json\s*(\{.*\})\s*", text, re.S)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except Exception:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except Exception:
                pass
    return {}


class VLMClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.model = model
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def read_image(self, image_path: str | Path, prompt: str = VLM_AGENT_PROMPT) -> dict[str, Any]:
        data = base64.b64encode(Path(image_path).read_bytes()).decode()
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + data}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return extract_json(resp.choices[0].message.content)


def parse_image(image_path: str | Path, vlm: VLMClient) -> dict[str, Any]:
    return vlm.read_image(image_path, VLM_AGENT_PROMPT)

def image_to_schematic(vlm, image_path, out_dir, name="vlm_schematic"):
    """完整链路：VLM 读图 → 结构化 JSON → 渲染干净 SVG/PNG。"""
    from . import schematic
    data = vlm.read_image(image_path, VLM_AGENT_PROMPT)
    if not isinstance(data.get("component_list"), list):
        data["component_list"] = []
    if not isinstance(data.get("connection_list"), list):
        data["connection_list"] = []
    png, svg = schematic.render_schematic(data, out_dir, name=name)
    return data, png, svg
