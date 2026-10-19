"""命令行入口：python -m src.mv_proposal.cli <command> ..."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_cfg():
    from .config import Config
    return Config.load()


def cmd_generate(args) -> None:
    from .pipeline import generate
    text = Path(args.input).read_text(encoding="utf-8")
    generate(text, llm_provider=args.llm, out_dir=Path(args.out) if args.out else None)


def cmd_demo(args) -> None:
    from .pipeline import generate
    cfg = _load_cfg()
    sample = cfg.samples_dir / "requirement_example.md"
    if not sample.exists():
        print(f"示例需求不存在：{sample}")
        sys.exit(1)
    generate(sample.read_text(encoding="utf-8"), llm_provider=args.llm,
             out_dir=Path(args.out) if args.out else None)


def cmd_feedback(args) -> None:
    from .feedback import FeedbackManager
    fm = FeedbackManager()
    if args.sub == "image":
        meta = {
            "device_type": args.type,
            "name": args.name or Path(args.image).stem,
            "description": args.desc or "",
            "params": json.loads(args.params) if args.params else {},
            "tags": args.tags.split(",") if args.tags else [],
        }
        r = fm.ingest_image(args.image, meta)
        print(f"图片已入库：{r['rel_path']}（{r['device_type']}）")
    elif args.sub == "text":
        text = Path(args.text).read_text(encoding="utf-8")
        r = fm.ingest_text(text, source=Path(args.text).name, collection=args.collection)
        print(f"文本已入库：{r['source']}（集合 {r['collection']}）")


def cmd_select(args) -> None:
    """选型：案例优先召回，无匹配则动态设备组合（含硬件强制配套校验）。"""
    from .config import Config
    from .context import build_context
    from .selection import format_selection, run_selection

    cfg = Config.load()
    ctx = build_context(cfg, args.llm)
    src = Path(args.input)
    text = src.read_text(encoding="utf-8") if src.is_file() else args.input
    kwargs = {} if args.threshold is None else {"threshold": args.threshold}
    res = run_selection(ctx, text, **kwargs)
    print(format_selection(res))


def cmd_catalog(args) -> None:
    """查询产品目录知识库（海康标准产品手册，独立集合 catalog）。"""
    from .catalog import CatalogKB
    from .config import Config
    from .embedding import EmbeddingClient
    from .vectorstore import VectorStore

    cfg = Config.load()
    embedder = EmbeddingClient(provider=cfg.embedding_provider, dim=cfg.embedding_dim,
                               cache_dir=str(cfg.model_cache_dir), base_url=cfg.embedding_base_url,
                               api_key=cfg.embedding_api_key, model=cfg.embedding_model)
    store = VectorStore(cfg.vectorstore_path)
    kb = CatalogKB(cfg.project_root / "data" / "catalog" / "products.json", embedder, store)
    print(f"产品目录知识库：{kb.count()} 款（" + "，".join(f"{k}={v}" for k, v in kb.by_type().items()) + "）")
    if not args.query:
        return
    for h in kb.search(args.query, top_k=args.top_k, device_type=args.type):
        f = h["fields"]
        if h["device_type"] == "series":
            print(f"  {h['score']:.3f} [系列] {f.get('系列')} | 适用场景：{f.get('适用场景')}")
            print(f"      关联型号：{'、'.join(f.get('关联型号', [])[:6])} …")
            continue
        line = f"  {h['score']:.3f} [{h['type_label']}] {h['model']}"
        if h["device_type"] == "camera":
            line += f" | {f.get('分辨率')} | {f.get('快门')} | {f.get('接口')} | {f.get('颜色')} | {f.get('帧率fps')}fps"
        elif h["device_type"] == "lens":
            extra = []
            if f.get("光圈范围"): extra.append("光圈" + f["光圈范围"])
            if f.get("畸变") is not None: extra.append("畸变" + str(f["畸变"]))
            if f.get("视场角D°") is not None: extra.append("视场角D%g°" % f["视场角D°"])
            if f.get("滤镜螺纹"): extra.append("滤镜" + f["滤镜螺纹"])
            line += f" | {f.get('焦距mm')}mm | {f.get('卡口')} | {f.get('标称MP')}MP | " + "，".join(extra)
        elif h["device_type"] == "infrared":
            line += f" | {f.get('波段')} | {f.get('类型2')} | {f.get('分辨率')} | {f.get('帧率')}fps"
        elif h["device_type"] == "framegrabber":
            line += f" | {f.get('总线接口')} | {f.get('网口数')}口 | {f.get('带宽')}"
        elif h["device_type"] == "cable":
            line += f" | {f.get('接口')} | {f.get('类别')} | 长度{f.get('长度')}"
        elif h["device_type"] == "industry":
            extra = [str(f[k]) for k in ("光源长度mm", "光源波长", "分辨率", "帧率fps", "接口", "发光区直径mm") if f.get(k)]
            if f.get("应用场景"): extra.append("适用：" + f["应用场景"][:30])
            line += f" | {f.get('类型')} | " + "，".join(extra)
        elif h["device_type"] == "context":
            line += f" | 应用案例 | {f.get('应用场景')} | 关联：{'、'.join(f.get('关联型号', [])[:4])} …"
        elif h["device_type"] in ("sensor3d", "stereo", "perception", "logistics"):
            if f.get("类型") in ("3D激光轮廓传感器", "双目单线3D轮廓传感器"):
                if f.get("近视场mm") is not None:
                    extra = []
                    if f.get("测量范围MRmm") is not None: extra.append("MR%gmm" % f["测量范围MRmm"])
                    if f.get("检测精度"): extra.append(f["检测精度"])
                    if f.get("检测速度m/s"): extra.append(f["检测速度m/s"] + "m/s")
                    if f.get("扫描帧率fps"): extra.append(f["扫描帧率fps"] + "fps")
                    line += f" | {f.get('类型')} | " + "，".join(extra)
                else:
                    extra = []
                    if f.get("Z轴测量范围mm") is not None: extra.append("Z范围%gmm" % f["Z轴测量范围mm"])
                    if f.get("Z轴重复精度µm"): extra.append("重复精度%sµm" % f["Z轴重复精度µm"])
                    if f.get("激光波长nm"): extra.append("%dnm" % f["激光波长nm"])
                    if f.get("扫描帧率"): extra.append(f["扫描帧率"])
                    line += f" | {f.get('类型')} | " + "，".join(extra)
            else:
                extra = []
                for k in ("图像分辨率", "分辨率", "视场角", "工作范围m", "工作范围近mm", "波长nm", "接口", "IP防护", "套包", "光源类型"):
                    if f.get(k): extra.append(str(f[k]))
                line += f" | {f.get('类型')} | " + "，".join(extra)
        else:
            line += f" | {f.get('分辨率')} | {f.get('行频kHz')}kHz | {f.get('接口')}"
        print(line)


def cmd_vlm(args) -> None:
    """VLM 读图：解析知识库图片/示意图，输出结构化布局 JSON。"""
    import json
    from .config import Config
    from .vision import VLMClient, parse_image

    cfg = Config.load()
    vlm = VLMClient(cfg.vlm_base_url, cfg.vlm_api_key, cfg.vlm_model)
    print(f"VLM: {cfg.vlm_provider} / {cfg.vlm_model}")
    data = parse_image(args.image, vlm)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_image2svg(args) -> None:
    """完整链路：VLM 读图 → 结构化 JSON → 渲染 SVG/PNG。"""
    import json
    from pathlib import Path
    from .config import Config
    from .vision import VLMClient, image_to_schematic

    cfg = Config.load()
    vlm = VLMClient(cfg.vlm_base_url, cfg.vlm_api_key, cfg.vlm_model)
    out = Path(args.out) if args.out else cfg.output_dir / "vlm_svg"
    out.mkdir(parents=True, exist_ok=True)
    data, png, svg = image_to_schematic(vlm, args.image, out)
    print("== VLM 读图 JSON ==")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("== 输出 ==")
    print("  " + str(out / png))
    print("  " + str(out / svg))


def cmd_station(args) -> None:
    """检索历史工位示意图 → 用 sidecar JSON 渲染干净 SVG（不二次读图）。"""
    from pathlib import Path
    from . import schematic
    from .config import Config
    from .embedding import EmbeddingClient
    from .station_library import StationLibrary
    from .vectorstore import VectorStore

    cfg = Config.load()
    em = EmbeddingClient(provider=cfg.embedding_provider, dim=cfg.embedding_dim,
                         cache_dir=str(cfg.model_cache_dir), base_url=cfg.embedding_base_url,
                         api_key=cfg.embedding_api_key, model=cfg.embedding_model)
    st = VectorStore(cfg.vectorstore_path)
    lib = StationLibrary(cfg.project_root / "data" / "station_diagrams", em, st)
    print(f"工位示意图库：{lib.count()} 张")
    hits = lib.search(args.query, top_k=args.top_k)
    out = Path(args.out) if args.out else cfg.output_dir / "station_svg"
    out.mkdir(parents=True, exist_ok=True)
    for i, h in enumerate(hits, 1):
        data = h["data"]
        png, svg = schematic.render_schematic(data, out, name=f"station_{i}")
        print(f"[{h['score']:.3f}] {h['id']} → {data.get('drawing_type')}")
        print(f"   来源图: {h['png']}")
        print(f"   输出: {out / svg}  /  {out / png}")


def cmd_kb(args) -> None:
    cfg = _load_cfg()
    from .context import build_context
    ctx = build_context(cfg)
    print(f"图片库：{ctx.image_lib.count()} 张")
    for t in ctx.image_lib.list_types():
        n = sum(1 for e in ctx.image_lib.entries if e.device_type == t)
        print(f"  - {t}: {n}")
    print(f"Embedding: {ctx.embedder.provider} | 向量库: {cfg.vectorstore_path}")
    print(f"文本知识库：{ctx.kb.count()} 块（" + "，".join(f"{k}={v}" for k, v in ctx.kb.collection_counts().items()) + "）")
    for coll, chunks in ctx.kb.chunks.items():
        for c in chunks:
            print(f"  - [{coll}] {c.source}")


def cmd_optic(args) -> None:
    """从文字化描述生成光路布局示意图。"""
    from . import diagram
    from .config import Config
    from .optic import extract_optic_layout

    cfg = Config.load()
    src = Path(args.input)
    text = src.read_text(encoding="utf-8") if src.is_file() else args.input
    spec = extract_optic_layout(text)
    out = Path(args.out) if args.out else cfg.output_dir / "optic_demo"
    out.mkdir(parents=True, exist_ok=True)
    from . import schematic
    data = schematic.build_optic_json(spec)
    png, svg = schematic.render_schematic(data, out, name="optic_layout")
    print("光路布局示意图已生成：")
    print(f"  相机: {spec.camera_label}（{spec.camera_note or '默认安装'}）")
    print(f"  镜头: {spec.lens_label} | 检测物: {spec.object_label}")
    print(f"  光源: {spec.light_color}{spec.light_label}（{int(spec.tilt_min)}°~{int(spec.tilt_max)}°，示意 {int(spec.tilt_shown)}°）")
    print(f"  尺寸: 镜头→检测物 {spec.lens_to_object} | 光源底部→平台 {spec.light_height}")
    print(f"  输出: {out / png}")
    print(f"        {out / svg}")


def cmd_import_ppt(args) -> None:
    import importlib.util

    from .config import Config
    cfg = Config.load()
    script = cfg.project_root / "scripts" / "import_ppt.py"
    spec = importlib.util.spec_from_file_location("_import_ppt", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    argv = [str(args.pptx), "--out", str(Path(args.out) if args.out else cfg.image_library_dir)]
    if args.force_type:
        argv += ["--type", args.force_type]
    argv += ["--min-size", str(args.min_size)]
    if args.dry_run:
        argv.append("--dry-run")
    if args.include_orphans:
        argv.append("--include-orphans")
    if args.prefix:
        argv += ["--prefix", args.prefix]
    if args.no_reindex:
        argv.append("--no-reindex")
    mod.main(argv)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="mv_proposal", description="机器视觉解决方案书自动生成系统")
    sub = p.add_subparsers(dest="command")

    g = sub.add_parser("generate", help="根据需求文件生成方案书")
    g.add_argument("input", help="需求文本文件路径")
    g.add_argument("--llm", default=None, help="deepseek|dashscope|openai|mock（默认取 config）")
    g.add_argument("--out", default=None, help="输出目录（默认 output/<时间戳>-<项目>）")
    g.set_defaults(func=cmd_generate)

    d = sub.add_parser("demo", help="用内置示例需求跑通全流程")
    d.add_argument("--llm", default=None)
    d.add_argument("--out", default=None)
    d.set_defaults(func=cmd_demo)

    f = sub.add_parser("feedback", help="人工修改素材回流")
    fsub = f.add_subparsers(dest="sub")
    fi = fsub.add_parser("image", help="图片入库")
    fi.add_argument("image")
    fi.add_argument("--type", default="accessory", help="设备类型")
    fi.add_argument("--name", default=None)
    fi.add_argument("--desc", default=None)
    fi.add_argument("--params", default=None, help='JSON，如 {"分辨率":"2448x2048"}')
    fi.add_argument("--tags", default=None, help="逗号分隔")
    ft = fsub.add_parser("text", help="文本素材入库")
    ft.add_argument("text")
    ft.add_argument("--collection", default="proposals", choices=["proposals", "legends", "devices"])
    f.set_defaults(func=cmd_feedback)

    sta = sub.add_parser("station", help="检索历史工位示意图→渲染SVG")
    sta.add_argument("query", help="需求查询词，如：环形光源照明 检测物")
    sta.add_argument("--top-k", type=int, default=2)
    sta.add_argument("--out", default=None, help="输出目录")
    sta.set_defaults(func=cmd_station)

    vl = sub.add_parser("vlm", help="VLM 读图：解析图片→结构化布局JSON")
    vl.add_argument("image", help="图片路径")
    vl.set_defaults(func=cmd_vlm)

    i2s = sub.add_parser("image2svg", help="完整链路：VLM读图→JSON→SVG/PNG")
    i2s.add_argument("image", help="图片路径")
    i2s.add_argument("--out", default=None, help="输出目录")
    i2s.set_defaults(func=cmd_image2svg)

    cat = sub.add_parser("catalog", help="查询产品目录知识库（海康标准产品手册）")
    cat.add_argument("query", nargs="?", default=None)
    cat.add_argument("--top-k", type=int, default=5)
    cat.add_argument("--type", dest="type", default=None,
                      choices=["camera", "linescan", "infrared", "lens", "framegrabber", "cable",
                               "sensor3d", "stereo", "perception", "logistics"])
    cat.set_defaults(func=cmd_catalog)

    sel = sub.add_parser("select", help="选型：案例优先召回，无匹配则动态设备组合")
    sel.add_argument("input", help="需求文本或文件路径")
    sel.add_argument("--llm", default=None, help="deepseek|mock（默认取 config）")
    sel.add_argument("--threshold", type=float, default=None, help="案例召回分数阈值（默认取 selection.CASE_THRESHOLD）")
    sel.set_defaults(func=cmd_select)

    k = sub.add_parser("kb", help="查看知识库/图片库状态")
    k.set_defaults(func=cmd_kb)

    op = sub.add_parser("optic", help="根据文字化描述生成光路布局示意图")
    op.add_argument("input", help="描述文本，或描述文件路径")
    op.add_argument("--out", default=None, help="输出目录")
    op.set_defaults(func=cmd_optic)

    ip = sub.add_parser("import-ppt", help="从 PPTX 批量导入图片到图片库")
    ip.add_argument("pptx", help="PPTX 文件路径")
    ip.add_argument("--out", default=None, help="图片库根目录（默认 config 中路径）")
    ip.add_argument("--type", dest="force_type", default=None, help="强制设备类型")
    ip.add_argument("--min-size", type=int, default=120, help="最小边长(像素)")
    ip.add_argument("--dry-run", action="store_true", help="只预览不写入")
    ip.add_argument("--include-orphans", action="store_true")
    ip.add_argument("--prefix", default="")
    ip.add_argument("--no-reindex", action="store_true")
    ip.set_defaults(func=cmd_import_ppt)

    args = p.parse_args(argv)
    if not getattr(args, "command", None):
        p.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    main()