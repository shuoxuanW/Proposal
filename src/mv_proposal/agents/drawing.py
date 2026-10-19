"""
绘图 Agent：按需求参数 + 图例规范库 + 图片库真实照片生成图纸。

支持 3 类图：
  - optic（光路布局示意图）：机位可变，嵌入相机/光源真实照片；
  - workpiece（产品示意图）：形状按需求（矩形/环形/圆形）；
  - detection（检测俯视图）：相机俯视 + 视场 + 检测点。
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import diagram
from ..models import DiagramArtifact, DiagramSpec, TaskPlan
from .base import BaseAgent


class DrawingAgent(BaseAgent):
    name = "绘图Agent"

    def run(self, plan: TaskPlan, out_dir: Path) -> list[DiagramArtifact]:
        """按图规格逐张渲染，返回产物列表。"""
        self.log(f"生成 {len(plan.diagrams)} 张图纸…")
        artifacts: list[DiagramArtifact] = []
        for spec in plan.diagrams:
            if spec.kind == "optic" and getattr(spec, "optic_spec", None) is not None:
                from .. import schematic
                # ① 先检索历史工位示意图；命中则用其 sidecar JSON 重画
                hit = None
                if self.station_lib:
                    q = " ".join([plan.detection_target, plan.requirement_summary,
                                  getattr(spec.optic_spec, "object_label", "")])
                    hits = self.station_lib.search(q, top_k=1)
                    if hits and hits[0]["score"] >= 0.45:
                        hit = hits[0]
                if hit:
                    data = hit["data"]
                    self.log(f"命中历史工位图：{hit['id']}（{hit['score']:.3f}）")
                else:
                    # ② 降级：按需求推理布局
                    data = schematic.build_optic_json(spec.optic_spec)
                png_rel, svg_rel = schematic.render_schematic(data, out_dir, name=spec.id)
            elif spec.kind == "workpiece":
                # 产品图（形状由模型给定）
                png_rel, svg_rel = diagram.render_workpiece(
                    spec.meta.get("name", "工件"), spec.meta.get("size", ""),
                    out_dir, dpi=self.cfg.image_dpi, fname=spec.id,
                    shape=spec.meta.get("shape"))
            elif spec.kind == "station" and getattr(spec, "station_spec", None) is not None:
                self._attach_station_photos(spec.station_spec)
                png_rel, svg_rel = diagram.render_station_layout(
                    spec.station_spec, out_dir, image_root=self.cfg.template_dir,
                    dpi=self.cfg.image_dpi, name=spec.id)
            elif spec.kind == "detection":
                # 检测俯视图
                png_rel, svg_rel = diagram.render_detection(
                    spec.meta.get("object", "工件"), spec.meta.get("fov", ""),
                    spec.meta.get("regions", []), out_dir, dpi=self.cfg.image_dpi, fname=spec.id)
            else:
                # 设备框架图兜底
                spec = self._attach_images(spec, plan)
                png_rel, svg_rel, positions = diagram.render(
                    spec, self.cfg, self.cfg.image_library_dir, out_dir)
            artifacts.append(DiagramArtifact(
                spec_id=spec.id, title=spec.title, kind=spec.kind,
                png_rel=f"figures/{png_rel}", svg_rel=f"figures/{svg_rel}",
                nodes=spec.nodes, caption=spec.title))
        return artifacts

    def _attach_photos(self, ospec) -> None:
        """从模板库检索并绑定相机/光源可拼模板（向量模糊 + 精准匹配）。"""
        if not self.template_lib:
            return
        cam = self.template_lib.best("camera", f"{ospec.camera_label} 相机")
        if cam:
            ospec.camera_photo = cam["rel_path"]
            self.log(f"相机模板：{cam['rel_path']}（精准={cam['precise']}）")
        light = self.template_lib.best("light_source", f"{ospec.light_color}{ospec.light_label}")
        if light:
            ospec.light_photo = light["rel_path"]
            self.log(f"光源模板：{light['rel_path']}（精准={light['precise']}）")

    def _template_by_name(self, name: str):
        for e in getattr(self.template_lib, "entries", []):
            if e.name == name:
                return e
        return None

    def _attach_camera_photo(self, cam) -> None:
        """优先用知识库里与相机类型匹配的真实模板图（面阵/线扫/远心）。"""
        label = str(getattr(cam, "label", "") or "")
        lens = str(getattr(cam, "lens", "") or "")
        blob = f"{label} {lens}"
        entry = self._template_by_name(label)
        if entry is None:
            if "远心" in blob:
                target = "相机加远心镜头"
            elif "线扫" in blob or "线阵" in blob:
                target = "线扫相机"
            else:
                target = "相机加fa镜头"
            entry = self._template_by_name(target)
        if entry is not None:
            cam.photo = entry.rel_path
            return
        hit = self.template_lib.best("camera", blob)
        if hit:
            cam.photo = hit["rel_path"]

    def _attach_light_photo(self, lt) -> None:
        """按光源类型/颜色/角度选知识库模板，避免向量检索把环形光配成其他光型。"""
        label = str(getattr(lt, "label", "") or "")
        kind = str(getattr(lt, "kind", "") or "")
        if not kind:
            for k in ("圆顶", "同轴", "条形", "面光", "背光", "环形"):
                if k in label:
                    kind = k
                    break
        color = "红" if "红" in label else ("蓝" if "蓝" in label else "白")
        target = None
        if "圆顶" in kind or "穹" in kind:
            target = "圆顶光源"
        elif "同轴" in kind:
            target = f"同轴光源{color}色"
        elif "条形" in kind:
            target = f"{color}色条形光源正视图"
        elif "面光" in kind or "背光" in kind:
            target = "面光源底部背光" if "底" in label else "面光源侧部背光"
        elif "环形" in kind:
            angle = float(getattr(lt, "angle", 45) or 45)
            target = f"{color}色环形光源{90 if angle >= 70 else 45}°"
        entry = self._template_by_name(target) if target else None
        if entry is not None:
            lt.photo = entry.rel_path
            return
        hit = self.template_lib.best("light_source", label or kind)
        if hit:
            lt.photo = hit["rel_path"]

    def _attach_station_photos(self, sspec) -> None:
        """为多工位里的每台相机/光源绑知识库真实模板图（不只是第一个工位）。"""
        if not self.template_lib:
            return
        units = list(getattr(sspec, "stations", []) or [])
        if not units:
            units = [sspec]
        for unit in units:
            for cam in getattr(unit, "cameras", []) or []:
                self._attach_camera_photo(cam)
                if getattr(cam, "photo", None):
                    self.log(f"相机模板：{cam.label} -> {cam.photo}")
            for lt in getattr(unit, "lights", []) or []:
                self._attach_light_photo(lt)
                if getattr(lt, "photo", None):
                    self.log(f"光源模板：{lt.label} -> {lt.photo}")

    def _legend_style(self) -> dict:
        """读取图例规范库里的 styles.json（颜色/线型），用于绘图。"""
        p = self.cfg.knowledge_dir / "legends" / "光路图例规范.json"
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data.get("styles", {})
            except Exception:
                return {}
        return {}

    def _attach_images(self, spec: DiagramSpec, plan: TaskPlan) -> DiagramSpec:
        """设备框架图兜底：为节点绑定图片库照片。"""
        if not self.image_lib:
            return spec
        ctx = f"{plan.detection_target} {plan.requirement_summary}"
        for node in spec.nodes:
            q = f"{node.label} {node.spec_hint} {ctx}".strip()
            hit = self.image_lib.best(node.device_type, q)
            if hit:
                node.image_rel = hit["rel_path"]
                node.image_meta = {"name": hit.get("name", ""), "description": hit.get("description", ""),
                                   "params": hit.get("params", {}), "score": hit.get("score", 0)}
            else:
                node.image_rel = None
                node.image_meta = {}
        return spec