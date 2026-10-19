"""
售前选型顾问（对话式需求调研）。

客户侧：只输出自然语言顾问对话；不泄露相似度/路径/召回标记/原始案例文档。
后台侧：召回命中、相似度、配套校验结果单独返回，供后台面板展示。

流程（每轮）：
  1. 后台 RAG 案例召回（作参考素材，不进客户对话）
  2. 从对话提取 7 类必要信息（规则提取仅作提示，理解交给模型）
  3. 模型扮演顾问：信息不足→礼貌追问；足够→通俗初步方案概述
"""
from __future__ import annotations

import re

from .compat import check_compat, format_compat
from .selection import recall_cases, _dynamic_selection

# 7 类必要信息：中文标签 + 提取正则（规则只作提示）
REQUIRED_FIELDS = [
    ("产品外形尺寸/材质", r"尺寸|mm|cm|材质|金属|塑料|玻璃|陶瓷|PCB|FPC|硅胶|橡胶"),
    ("检测目标", r"检测|识别|测量|有无|缺陷|划痕|定位|扫码|漏装|漏焊|少胶|点胶|气泡"),
    ("检测精度", r"精度|0\.\d+\s*mm|±\d|um|μm|0\.\d+mm"),
    ("生产节拍/产能", r"节拍|CT|秒|分钟|件/|ppm|速度|产能"),
    ("安装空间限制", r"空间|占地|高度限制|尺寸限制|安装尺寸"),
    ("现场环境", r"光照|粉尘|震动|温度|湿度|环境|油污|反光"),
    ("安装方式", r"工位|流水线|在线|离线|固定|移动|飞拍|定拍|台面|机台"),
]

QUESTIONS = {
    "产品外形尺寸/材质": "产品的外形尺寸和材质是什么？",
    "检测目标": "需要检测什么？是尺寸测量、缺陷检测还是有/无判断？",
    "检测精度": "检测精度要求多少（例如 ±0.1mm）？",
    "生产节拍/产能": "产线节拍或产能要求是多少（例如 120 件/分钟）？",
    "安装空间限制": "现场安装空间有没有尺寸限制？",
    "现场环境": "现场环境如何？有无光照、粉尘、震动等干扰？",
    "安装方式": "是固定工位检测，还是流水线在线检测？",
}

SYSTEM = (
    "你是机器视觉售前选型顾问，面向客户做交互式需求调研。\n"
    "规则：\n"
    "1) 渐进式问诊：不要一次性输出完整硬件清单；识别缺失的关键参数后依次提问，每次只问 1~3 个最关键的问题；\n"
    "2) 只有信息足够时，才输出简洁、通俗的初步方案概述，不使用内部技术术语，不出现具体型号；\n"
    "3) 后台提供的检索资料只作参考素材，绝不能向客户展示相似度数值、文件路径、召回标记、向量库信息、原始 Markdown；\n"
    '4) 只输出 JSON：{"reply":"给客户看的自然语言回复","sufficient":true或false,"requirement":"结构化需求结论或空字符串"}；\n'
    '5) 当 sufficient 为 true 时，requirement 用「字段：值」分行列出（产品名称/产品尺寸/材质/检测目标/检测精度/节拍/安装方式/现场环境），可直接作为方案书需求输入；当 sufficient 为 false 时，requirement 置空字符串。'
)


def extract_fields(text: str) -> dict[str, bool]:
    return {label: bool(re.search(pat, text, re.I)) for label, pat in REQUIRED_FIELDS}


def _case_ref_text(cases) -> str:
    lines = []
    for i, c in enumerate(cases[:3], 1):
        snippet = " ".join(c["text"].split("\n")[:6])
        lines.append("参考案例%d：%s" % (i, snippet[:260]))
    return "\n".join(lines)


def _device_ref_text(items, compat) -> str:
    lines = []
    for it in items:
        lines.append("%s：%s" % (it.device_type, it.model or it.desc))
    lines += format_compat(compat)
    return "\n".join(lines)


def _mock_reply(missing: list[str]) -> str:
    if missing:
        picked = missing[:3]
        q = "\n".join("%d. %s" % (i, QUESTIONS[k]) for i, k in enumerate(picked, 1))
        return "收到，为了给你更准确的方案，还想再确认几点：\n" + q
    return "信息已齐全。根据你的需求，初步建议采用面阵相机配合适配光源的定拍检测方案，具体参数我整理后给你确认。"


def advise(ctx, history: list[dict], user_msg: str, llm) -> dict:
    """返回 {"reply": 客户侧回复, "debug": 后台日志}。"""
    # 0) 完整需求文本（对话累积，案例召回/动态选型都必须用它，而非最后一条消息）
    full = "\n".join(str(m.get("content", "")) for m in (history or [])) + "\n" + user_msg

    # 1) 后台 RAG 案例召回（用完整需求，不进客户对话）
    cases = recall_cases(ctx, full, top_k=3)

    # 2) 7 类信息提取（规则提示）
    fields = extract_fields(full)
    missing = [label for label, _ in REQUIRED_FIELDS if not fields[label]]

    # 完整对话记录（关键：模型必须看到全部上下文，而不是只看最后一条）
    transcript = "\n".join(
        ("客户：" if m.get("role") == "user" else "顾问：") + str(m.get("content", ""))
        for m in (history or [])
    )

    # 3) 后台参考素材（案例优先，无案例才动态选型）
    ref = _case_ref_text(cases) if cases else "（无足够匹配的历史案例）"
    compat_checks: list[str] = []
    if not cases:
        try:
            items, _ = _dynamic_selection(ctx, full)
            compat = check_compat(items)
            ref = _device_ref_text(items, compat)
            compat_checks = format_compat(compat)
        except Exception:
            pass

    # 4) 模型扮演顾问
    if llm.is_mock:
        reply = _mock_reply(missing)
        sufficient = not missing
        requirement = ""
        if sufficient:
            user_texts = [str(m.get("content", "")) for m in (history or [])
                          if m.get("role") == "user"]
            user_texts.append(user_msg)
            requirement = "\n".join(t.strip() for t in user_texts if t and t.strip())
    else:
        user = (
            "客户信息状态：%s\n\n"
            "对话记录：\n%s\n客户：%s\n\n"
            "历史/设备后台参考（仅供你参考，严禁向客户泄露）：\n%s\n\n"
            "请根据完整对话记录回复客户（信息足够时，把对话中已确认的信息汇总进 requirement）。"
            % (("已具备全部关键参数" if not missing else "缺失：" + "、".join(missing)), transcript, user_msg, ref)
        )
        try:
            data = llm.complete_json(SYSTEM, user)
            reply = str(data.get("reply", "")).strip() or _mock_reply(missing)
            sufficient = bool(data.get("sufficient", False))
            requirement = str(data.get("requirement", "")).strip()
        except Exception:
            reply = _mock_reply(missing)
            sufficient = not missing
            requirement = ""

    return {
        "reply": reply,
        "sufficient": sufficient,
        "requirement": requirement,
        "debug": {
            "selected_source": "案例库召回" if cases else "AI动态选型",
            "matched": [{"source": c["source"], "score": round(c["score"], 4)} for c in cases],
            "missing_fields": missing,
            "provided_fields": [label for label, _ in REQUIRED_FIELDS if fields[label]],
            "compat": compat_checks,
        },
    }
