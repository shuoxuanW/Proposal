"""
主流程编排：把 5 个 Agent 串成一条流水线。

流程：
  需求文本 → ①需求解析 → ②方案撰写 → ③绘图 → ④校验 → ⑤汇总输出

normalize_plan() 负责把各 Agent 产出的图规格规范化，保证下游引用一致。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .agents import AssemblyAgent, DrawingAgent, RequirementAgent, VerificationAgent, WritingAgent
from .config import Config
from .context import build_context
from .models import DiagramNode, DiagramSpec, TaskPlan


def _slug(s: str, max_len: int = 40) -> str:
    """把项目名转成安全的目录名（去特殊字符，限长）。"""
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", s).strip("-")
    return s[:max_len] or "proposal"



def _station_case_query(ctx, plan: TaskPlan) -> str:
    """用命中的工位图 note/光源规格构造文本案例检索词，用于对齐同一项目的文本案例。"""
    hit = (getattr(plan, "layout_reasoning", {}) or {}).get("station_hit") or {}
    sid = hit.get("id")
    if not sid:
        return ""
    entry = next((e for e in getattr(ctx.station_lib, "entries", []) if e.get("id") == sid), None)
    if entry is None:
        return ""
    data = entry.get("data") or {}
    parts = [str(data.get("note", "") or "")]
    for spec in data.get("light_spec_list", []) or []:
        parts += [str(spec.get("name", "")), str(spec.get("type", "")),
                  str(spec.get("angle", "")), str(spec.get("distance_to_object", ""))]
    if hit.get("camera_working_distance"):
        parts.append(str(hit["camera_working_distance"]))
    return " ".join(p for p in parts if p).strip()


def _rerank_cases_by_station(ctx, plan: TaskPlan, cases: list[dict]) -> list[dict]:
    """优先把与命中工位图同一技术参数的文本案例排到第一位。"""
    query = _station_case_query(ctx, plan)
    if not query:
        return cases
    try:
        hits = ctx.kb.retrieve("proposals", query, top_k=3)
    except Exception:
        return cases
    if not hits or hits[0].get("score", 0) < 0.70:
        return cases
    top = hits[0]
    src = top["source"]
    full = "\n\n".join(ch.text for ch in ctx.kb.chunks.get("proposals", []) if ch.source == src)
    first = {"source": src, "score": round(float(top["score"]), 4), "text": full or top.get("text", "")}
    return [first] + [c for c in cases if c.get("source") != src]


def normalize_plan(plan: TaskPlan, cfg: Config) -> TaskPlan:
    """
    规范化 TaskPlan 里的图规格：
    - 光路/产品/检测等示意图：原样保留（id、meta、optic_spec 不变）；
    - 设备框架图：统一 id=framework-N，节点 id=<设备类型>-<序号>，并按 config.chain 补全链路。
    """
    new_diagrams: list[DiagramSpec] = []
    for idx, spec in enumerate(plan.diagrams):
        if spec.kind != "framework":
            # 非框架图（光路/产品/检测）直接保留，避免被改名
            new_diagrams.append(spec)
            continue
        # 框架图：编号从 1 开始
        sid = f"framework-{sum(1 for d in new_diagrams if d.kind == 'framework') + 1}"
        counters: dict[str, int] = {}
        old_to_new: dict[str, str] = {}
        new_nodes: list[DiagramNode] = []
        # 节点 id 规范化为 <设备类型>-<序号>
        for n in spec.nodes:
            counters[n.device_type] = counters.get(n.device_type, 0) + 1
            nid = f"{n.device_type}-{counters[n.device_type]}"
            old_to_new[n.id] = nid
            new_nodes.append(DiagramNode(
                id=nid, device_type=n.device_type,
                label=n.label or cfg.device_label(n.device_type),
                spec_hint=n.spec_hint, image_rel=n.image_rel, image_meta=n.image_meta,
            ))
        # 连线：保留原有 + 按 config.chain 补全光路/数据链路
        new_edges: list[list[str]] = []
        for a, b in spec.edges:
            na, nb = old_to_new.get(a), old_to_new.get(b)
            if na and nb and [na, nb] not in new_edges:
                new_edges.append([na, nb])
        node_ids_by_type = {n.device_type: n.id for n in new_nodes}
        for a, b in cfg.chain:
            if a in node_ids_by_type and b in node_ids_by_type:
                e = [node_ids_by_type[a], node_ids_by_type[b]]
                if e not in new_edges:
                    new_edges.append(e)
        new_diagrams.append(DiagramSpec(
            id=sid, kind=spec.kind, title=spec.title, nodes=new_nodes,
            edges=new_edges, description=spec.description,
            optic_spec=getattr(spec, "optic_spec", None),
            station_spec=getattr(spec, "station_spec", None),
            meta=getattr(spec, "meta", {}) or {},
        ))
    plan.diagrams = new_diagrams
    return plan


def generate(requirement_text: str, cfg: Config | None = None, llm_provider: str | None = None,
             out_dir: Path | None = None, ctx=None) -> dict:
    """
    主入口：输入需求文本，跑完整流程，返回结果字典。

    参数：
        requirement_text: 需求文本
        cfg:            配置（不传则自动加载）
        llm_provider:   deepseek/mock（不传用 config 默认）
        out_dir:        输出目录（不传自动生成 output/<时间戳>-<项目名>）
        ctx:            共享组件（Web 服务常驻时传入，避免重复加载模型）
    """
    cfg = cfg or Config.load()
    # 复用已有上下文（服务端），否则新建（CLI）
    if ctx is None:
        ctx = build_context(cfg, llm_provider)
    elif llm_provider and getattr(ctx.llm, "provider", "") != llm_provider.lower():
        # 服务端常驻 ctx 默认用配置里的模型；请求显式指定 mock/其他模型时只替换 LLM，复用知识库
        from types import SimpleNamespace
        from .llm import LLMClient
        ctx = SimpleNamespace(**{**vars(ctx), "llm": LLMClient(
            provider=llm_provider, base_url=cfg.llm_base_url, api_key=cfg.api_key,
            model=cfg.llm_model, temperature=cfg.llm_temperature)})

    print(f"== {cfg.name} ==")
    print(f"  LLM: {ctx.llm.provider} | 文本知识库: {ctx.kb.count()} 块 | 图片库: {ctx.image_lib.count()} 张"
          f"（类型: {', '.join(ctx.image_lib.list_types()) or '无'}）")

    # 实例化 5 个 Agent
    req_agent = RequirementAgent(cfg, ctx.llm, ctx.kb, ctx.image_lib, ctx.template_lib, ctx.station_lib)
    writing_agent = WritingAgent(cfg, ctx.llm, ctx.kb, ctx.image_lib, ctx.template_lib, ctx.station_lib)
    drawing_agent = DrawingAgent(cfg, ctx.llm, ctx.kb, ctx.image_lib, ctx.template_lib, ctx.station_lib)
    verify_agent = VerificationAgent(cfg, ctx.llm, ctx.kb, ctx.image_lib, ctx.template_lib, ctx.station_lib)
    assembly_agent = AssemblyAgent(cfg, ctx.llm, ctx.kb, ctx.image_lib, ctx.template_lib, ctx.station_lib)

    # ①.0 案例召回：先召回，需求解析/工位布局/正文撰写共用同一批案例
    from .selection import recall_cases
    matched_cases = recall_cases(ctx, requirement_text, top_k=3)
    if matched_cases:
        print("  命中历史案例：" + "、".join(c["source"] for c in matched_cases))
    else:
        print("  未命中历史案例（动态生成）")

    # ① 需求解析：文本 → 结构化任务计划（含光路机位参数，案例参数一并参考）
    plan = req_agent.run(requirement_text, case_ref=matched_cases)
    plan = normalize_plan(plan, cfg)
    print(f"  项目：{plan.project_name} | 设备 {len(plan.devices)} 类 | 章节 {len(plan.chapters)} | 图 {len(plan.diagrams)}")
    before = matched_cases[0]["source"] if matched_cases else ""
    matched_cases = _rerank_cases_by_station(ctx, plan, matched_cases)
    if matched_cases and matched_cases[0]["source"] != before:
        print("  案例重排（与工位图对齐）：" + matched_cases[0]["source"])
    writing_agent.case_ref = matched_cases

    # ② 方案撰写：生成 8 章正文（含 [[FIG:...]] 锚点）
    chapters = writing_agent.run(plan)

    # ③ 绘图：生成光路/产品/检测图（光路图嵌入知识库真实照片）
    run_dir = Path(out_dir) if out_dir else cfg.output_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{_slug(plan.project_name)}"
    figures_dir = run_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    artifacts = drawing_agent.run(plan, figures_dir)

    # ④ 校验：图文一致性检查
    report = verify_agent.run(plan, chapters, artifacts)

    # ⑤ 汇总输出：组装方案书 + 导出 + 图文联动注册表
    manifest = assembly_agent.run(plan, chapters, artifacts, report, run_dir)

    # 打印结果
    print(f"  校验：{'通过' if report.passed else '未通过'}（{len(report.issues)} 条）")
    for it in report.issues:
        print(f"    - [{it.severity}] {it.code}: {it.message}")
    print(f"  输出目录：{run_dir}")
    for k, v in manifest.get("exports", {}).items():
        print(f"    - {k}: {v}")

    manifest["matched_cases"] = [{"source": c["source"], "score": round(c["score"], 4)} for c in matched_cases]
    # 回写 manifest.json：assembly 先落盘，案例命中后补写，保证磁盘清单与接口返回一致
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"run_dir": run_dir, "plan": plan, "chapters": chapters,
            "artifacts": artifacts, "report": report, "manifest": manifest,
            "matched_cases": manifest["matched_cases"]}