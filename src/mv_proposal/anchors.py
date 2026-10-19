"""
图文锚点工具：正文里 [[FIG:id]] / [[DEV:fig:node]] 的提取与解析。
"""
from __future__ import annotations

import re

FIG_PAT = re.compile(r"\[\[FIG:([A-Za-z0-9_\-]+)\]\]")
DEV_PAT = re.compile(r"\[\[DEV:([A-Za-z0-9_\-]+):([A-Za-z0-9_\-]+)\]\]")


def extract_fig_refs(text: str) -> list[str]:
    """提取正文里的图引用 id 列表。"""
    return FIG_PAT.findall(text or "")


def extract_dev_refs(text: str) -> list[str]:
    """提取正文里的设备节点引用，返回 ["fig:node", ...]。"""
    return [f"{fig}:{node}" for fig, node in DEV_PAT.findall(text or "")]


def split_dev_ref(ref: str) -> tuple[str, str]:
    """把 "fig:node" 拆成 (fig, node)。"""
    fig, _, node = ref.partition(":")
    return fig, node