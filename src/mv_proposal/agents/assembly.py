"""
汇总输出 Agent：解析正文锚点 → 组装完整方案书 → 导出各格式 + 图文联动注册表。

锚点解析：[[FIG:optic-1]] → 内联图片；[[DEV:...]] → 设备名。
每解析一个锚点就在 linkage.json 里记一条，实现图文双向联动。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import document
from ..linkage import LinkageRegistry
from ..models import Chapter, DiagramArtifact, Proposal, TaskPlan, VerifyReport
from .base import BaseAgent


class AssemblyAgent(BaseAgent):
    name = "汇总输出Agent"

    def run(self, plan: TaskPlan, chapters: list[Chapter], artifacts: list[DiagramArtifact],
            report: VerifyReport, out_dir: Path) -> dict:
        self.log("组装方案书并导出…")
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # 组装成 Proposal 对象
        proposal = Proposal(
            project_name=plan.project_name,
            requirement_summary=plan.requirement_summary,
            chapters=chapters,
            diagrams=artifacts,
            report=report,
        )
        # 解析锚点，同时记录图文联动
        registry = LinkageRegistry()
        resolved = self._resolve(plan, chapters, artifacts, registry)

        # 导出 Markdown/HTML/Word/PDF
        doc = document.compose_markdown(proposal, resolved)
        exported = document.export_all(proposal, resolved, self.cfg, out_dir)

        # PPT 方案书（按模板）
        try:
            from .. import ppt_export
            template = self.cfg.ppt_template
            if template.exists():
                exported["pptx"] = ppt_export.export_ppt(
                    plan, artifacts, template, out_dir, chapters=chapters, report=report,
                    profile_path=self.cfg.ppt_profile)
        except Exception as e:
            print(f"  [汇总输出Agent] PPT 导出失败：{e}")

        # 项目持续规划文档（新增交付物）
        from .. import planning
        planning_doc = planning.generate_planning_doc(plan, report, image_count=self.image_lib.count() if self.image_lib else 0)
        (out_dir / "规划文档.md").write_text(planning_doc, encoding="utf-8")
        exported["planning"] = "规划文档.md"

        # 写联动注册表 + 汇总清单 + 结构化方案数据
        registry.save(out_dir / "linkage.json")
        manifest = {
            "project_name": plan.project_name,
            "verification_passed": report.passed,
            "issue_count": len(report.issues),
            "chapters": [c.title for c in chapters],
            "diagrams": [{"title": a.caption or a.title, "png": a.png_rel, "kind": a.kind} for a in artifacts],
            "exports": exported,
            "device_types_used": [n.device_type for a in artifacts for n in a.nodes],
            "layout_reasoning": getattr(plan, "layout_reasoning", {}),
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "proposal.json").write_text(
            proposal.model_dump_json(indent=2), encoding="utf-8")

        return manifest

    def _resolve(self, plan: TaskPlan, chapters: list[Chapter], artifacts: list[DiagramArtifact],
                 registry: LinkageRegistry) -> list[Chapter]:
        """把正文里的 [[FIG:xx]] / [[DEV:fig:node]] 锚点替换成图片/文字，并记录联动。"""
        art_by_id = {a.spec_id: a for a in artifacts}
        node_index: dict[str, dict] = {}
        for a in artifacts:
            for n in a.nodes:
                node_index[f"{a.spec_id}:{n.id}"] = {
                    "node": n, "diagram": a, "image_rel": n.image_rel,
                    "name": (n.image_meta or {}).get("name", ""),
                }

        resolved: list[Chapter] = []
        for ch in chapters:
            text = ch.content

            # 图锚点 [[FIG:optic-1]] → 内联图片
            def fig_repl(m: re.Match) -> str:
                fid = m.group(1)
                if fid in art_by_id:
                    a = art_by_id[fid]
                    registry.add(fid, "fig", ch.id, ch.title, diagram=fid,
                                 image_rel=a.png_rel, caption=a.caption)
                    return f"![{a.caption}]({a.png_rel})\n\n*{a.caption}*\n"
                return m.group(0)

            # 设备锚点 [[DEV:fig:node]] → 设备名
            def dev_repl(m: re.Match) -> str:
                fid, nid = m.group(1), m.group(2)
                key = f"{fid}:{nid}"
                if key in node_index:
                    info = node_index[key]
                    label = info["node"].label
                    name = info["name"]
                    registry.add(key, "dev", ch.id, ch.title, diagram=fid, node_id=nid,
                                 node_label=label, image_rel=info["image_rel"], name=name)
                    return f"**{label}**" + (f"（{name}）" if name else "")
                return m.group(0)

            text = re.sub(r"\[\[FIG:([A-Za-z0-9_\-]+)\]\]", fig_repl, text)
            text = re.sub(r"\[\[DEV:([A-Za-z0-9_\-]+):([A-Za-z0-9_\-]+)\]\]", dev_repl, text)
            resolved.append(Chapter(id=ch.id, title=ch.title, content=text,
                                    fig_refs=ch.fig_refs, dev_refs=ch.dev_refs))
        return resolved