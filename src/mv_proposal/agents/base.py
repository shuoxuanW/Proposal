"""
Agent 基类：所有 Agent 继承它，拿到共享的配置与组件。
"""
from __future__ import annotations

from ..config import Config
from ..llm import LLMClient
from ..knowledge import KnowledgeBase
from ..image_library import ImageLibrary


class BaseAgent:
    name = "base"

    def __init__(self, cfg: Config, llm: LLMClient, kb: KnowledgeBase | None = None,
                 image_lib: ImageLibrary | None = None, template_lib=None, station_lib=None):
        self.cfg = cfg              # 全局配置
        self.llm = llm              # LLM 客户端
        self.kb = kb                # 文本知识库（3 集合）
        self.image_lib = image_lib  # 图片库（设备照片）
        self.template_lib = template_lib  # 模板库（透明底可拼模板）
        self.station_lib = station_lib  # 历史工位示意图库（检索→重画）

    def log(self, msg: str) -> None:
        """打印带 Agent 名前缀的日志，方便看每个 Agent 干了什么。"""
        print(f"  [{self.name}] {msg}")