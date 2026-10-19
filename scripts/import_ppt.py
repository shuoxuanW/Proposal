"""从 PPTX 批量导入图片到图片库。

原理：.pptx 是 zip 包，图片位于 ppt/media/，幻灯片文字位于 ppt/slides/slideN.xml。
脚本按「幻灯片文字 + 文件名」自动判定设备类型，生成 sidecar 元数据，写入图片库。

用法：
  python -X utf8 scripts/import_ppt.py 我的图片库.pptx
  python -X utf8 scripts/import_ppt.py 我的图片库.pptx --dry-run          # 只预览不写入
  python -X utf8 scripts/import_ppt.py 我的图片库.pptx --type camera      # 强制设备类型
  python -X utf8 scripts/import_ppt.py 我的图片库.pptx --min-size 200     # 过滤小图标/Logo
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RASTER_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}

# 按“更具体优先”排序的判定规则（先匹配到的类型生效）
DEVICE_RULES: list[tuple[list[str], str]] = [
    # 打光/应用示意图（最优先，避免被"相机/光源"等词误判）
    (["项目名称", "相关参数", "被测物", "打光方案", "光路", "安装示意", "示意", "可调", "产品"], "application"),
    # 相机：品牌型号前缀 + 快门/接口特征
    (["OPT-CC", "MV-CS", "MV-CE", "MV-CA", "MV-CH", "MV-CL", "万全局", "万卷帘", "万全",
      "全局快门", "卷帘快门", "全局", "卷帘", "快门", "千兆网口", "万兆网", "网口",
      "相机", "ccd", "cmos", "面阵", "线阵", "工业摄像"], "camera"),
    # 镜头
    (["镜头", "远心", "焦距", "lens", "像素级"], "lens"),
    # 工控机/工控柜
    (["工控机", "工控柜", "工控", "视觉主机", "工业电脑", "ipc"], "ipc"),
    # 执行输出
    (["显示器", "plc", "机器人", "机械手", "剔除", "分拣", "报警"], "output"),
    # 光源控制器等附件（在通用"光源"之前）
    (["光源控制器", "频闪", "光源驱动"], "accessory"),
    # 光源
    (["光源", "条形光", "环形光", "面光源", "背光", "点光源", "无影光", "同轴光", "穹顶光", "照明", "打光"], "light_source"),
    # 其余附件
    (["编码器", "传感器", "支架", "滤镜", "偏振"], "accessory"),
]

DEVICE_LABELS = {
    "light_source": "光源", "lens": "镜头", "camera": "工业相机",
    "controller": "控制器/采集卡", "ipc": "工控机/视觉主机",
    "output": "执行输出", "accessory": "附件", "application": "打光/应用示意图",
}

INVALID = re.compile(r'[\\/:*?"<>|\r\n\t]+')
TEXT_RE = re.compile(r"<a:t>(.*?)</a:t>", re.S)
RELS_TARGET_RE = re.compile(r'Target="([^"]+)"')
PARAM_RE = re.compile(r"([A-Za-z\u4e00-\u9fff]{2,10})\s*[:：]\s*([0-9A-Za-z\.\-\*x×\u4e00-\u9fff%/\"″]{1,20})")


def slide_number(name: str) -> int:
    m = re.search(r"slide(\d+)\.xml$", name)
    return int(m.group(1)) if m else 0


def read_text_parts(xml: str) -> list[str]:
    parts = [html.unescape(t).strip() for t in TEXT_RE.findall(xml)]
    return [p for p in parts if p]


def classify(text: str, filename: str, force: str | None, title: str = "", doc: str = "") -> str:
    """按标题(权重3)/文件名(权重2)/文档名(权重2)/正文(权重1)加权打分，取最高分；同分按规则顺序。"""
    if force:
        return force
    t = (title or "").lower()
    fn = filename.lower()
    doc = (doc or "").lower()
    body = (text or "").lower()
    best_dtype, best_score = "accessory", 0
    for kws, dtype in DEVICE_RULES:
        score = 0
        for kw in kws:
            k = kw.lower()
            if k in t:
                score += 3
            if k in fn:
                score += 2
            if k in doc:
                score += 2
            if k in body:
                score += 1
        if score > best_score:
            best_score, best_dtype = score, dtype
    return best_dtype


def pick_name(text: str, parts: list[str], filename: str, dtype: str) -> str:
    kws = [kw for kws, dt in DEVICE_RULES if dt == dtype for kw in kws]

    # 把正文按分隔符切成更细的 token（如“点光源 / 高亮点光源”）
    tokens: list[str] = []
    for p in parts:
        for seg in re.split(r"[/,，;；、\s]+", p):
            seg = seg.strip()
            if seg:
                tokens.append(seg)

    def has_alnum(p: str) -> bool:
        # 只认 ASCII 字母/数字，避免中文 isalpha() 干扰
        return any(("a" <= c.lower() <= "z") or c.isdigit() for c in p)

    def is_good(p: str) -> bool:
        has_kw = any(k.lower() in p.lower() for k in kws)
        return (has_alnum(p) or has_kw) and 2 <= len(p) <= 24

    # 1) 标题 token（数字/字母/设备关键词才算有效，排除公司名等纯中文）
    if tokens and is_good(tokens[0]):
        return INVALID.sub("", tokens[0])[:24]
    # 2) 含设备关键词的短 token
    for p in tokens:
        if len(p) <= 24 and any(k.lower() in p.lower() for k in kws):
            return INVALID.sub("", p)[:24]
    # 3) 含数字/字母的首个短 token
    for p in tokens:
        if is_good(p):
            return INVALID.sub("", p)[:24]
    # 4) 文件名兜底
    stem = INVALID.sub("", Path(filename).stem)[:24]
    return stem or DEVICE_LABELS.get(dtype, dtype)


def extract_params(text: str) -> dict:
    out: dict = {}
    for k, v in PARAM_RE.findall(text):
        if k in ("http", "https"):
            continue
        if k not in out:
            out[k] = v
        if len(out) >= 8:
            break
    return out


def sanitize(name: str) -> str:
    s = INVALID.sub("", name).strip().strip(".")
    return s or "image"


def build_slide_map(zf: zipfile.ZipFile) -> list[tuple[int, list[str], list[str]]]:
    """返回 [(slide_no, text_parts, media_names), ...]。"""
    slides = sorted(
        [n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)],
        key=slide_number,
    )
    result = []
    for s in slides:
        no = slide_number(s)
        text_parts = read_text_parts(zf.read(s).decode("utf-8", "ignore"))
        rels = f"ppt/slides/_rels/slide{no}.xml.rels"
        media: list[str] = []
        if rels in zf.namelist():
            for target in RELS_TARGET_RE.findall(zf.read(rels).decode("utf-8", "ignore")):
                if "media/" in target:
                    name = "ppt/media/" + target.split("media/", 1)[1]
                    if name not in media:
                        media.append(name)
        result.append((no, text_parts, media))
    return result


def import_pptx(pptx: Path, out_root: Path, force_type: str | None, min_size: int,
                dry_run: bool, include_orphans: bool, prefix: str, reindex: bool) -> dict:
    if not pptx.exists():
        raise FileNotFoundError(pptx)

    stats = {"slides": 0, "media": 0, "imported": 0, "skipped_small": 0,
             "skipped_vector": 0, "skipped_dup": 0, "by_type": {}}
    written: list[dict] = []
    seen_hashes: set[str] = set()

    with zipfile.ZipFile(pptx) as zf:
        slide_map = build_slide_map(zf)
        stats["slides"] = len(slide_map)

        referenced: set[str] = set()
        for no, parts, media in slide_map:
            text = " ".join(parts)
            for m in media:
                referenced.add(m)
                ext = Path(m).suffix.lower()
                if ext not in RASTER_EXT:
                    stats["skipped_vector"] += 1
                    continue
                data = zf.read(m)
                try:
                    from PIL import Image
                    img = Image.open(io.BytesIO(data))
                    w, h = img.size
                except Exception:
                    stats["skipped_vector"] += 1
                    continue
                if min(w, h) < min_size:
                    stats["skipped_small"] += 1
                    continue
                digest = hashlib.md5(data).hexdigest()
                if digest in seen_hashes:
                    stats["skipped_dup"] += 1
                    continue
                seen_hashes.add(digest)

                dtype = classify(text, Path(m).name, force_type, parts[0] if parts else "", pptx.name)
                name = sanitize((prefix + pick_name(text, parts, Path(m).name, dtype)))
                if dtype == "application":
                    name = f"slide{no}_{name}"
                params = extract_params(text)
                desc = re.sub(r"\s+", " ", text).strip()[:300]

                target_dir = out_root / dtype
                target_img = target_dir / f"{name}{ext}"
                i = 2
                while target_img.exists() and (dry_run or target_img.read_bytes() != data):
                    target_img = target_dir / f"{name}_{i}{ext}"
                    i += 1

                stats["imported"] += 1
                stats["by_type"][dtype] = stats["by_type"].get(dtype, 0) + 1
                rec = {"slide": no, "device_type": dtype, "name": name,
                       "file": str(target_img.relative_to(out_root)).replace("\\", "/"),
                       "params": params, "source_media": m}
                written.append(rec)

                if not dry_run:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target_img.write_bytes(data)
                    meta = {
                        "device_type": dtype,
                        "name": name,
                        "brand": "",
                        "description": desc,
                        "params": params,
                        "tags": [DEVICE_LABELS.get(dtype, dtype)],
                        "source": f"{pptx.name}#slide{no}",
                    }
                    (target_img.with_suffix(".json")).write_text(
                        __import__("json").dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        if include_orphans:
            for m in zf.namelist():
                if m in referenced or not m.startswith("ppt/media/"):
                    continue
                ext = Path(m).suffix.lower()
                if ext not in RASTER_EXT:
                    continue
                data = zf.read(m)
                digest = hashlib.md5(data).hexdigest()
                if digest in seen_hashes:
                    continue
                try:
                    from PIL import Image
                    if min(Image.open(io.BytesIO(data)).size) < min_size:
                        continue
                except Exception:
                    continue
                seen_hashes.add(digest)
                dtype = classify("", Path(m).name, force_type, "")
                name = sanitize(prefix + Path(m).stem)
                stats["imported"] += 1
                stats["by_type"][dtype] = stats["by_type"].get(dtype, 0) + 1
                written.append({"slide": 0, "device_type": dtype, "name": name,
                                "file": f"{dtype}/{name}{ext}", "params": {}, "source_media": m})
                if not dry_run:
                    d = out_root / dtype
                    d.mkdir(parents=True, exist_ok=True)
                    (d / f"{name}{ext}").write_bytes(data)
                    (d / f"{name}.json").write_text(
                        __import__("json").dumps(
                            {"device_type": dtype, "name": name, "description": "", "params": {}, "tags": []},
                            ensure_ascii=False, indent=2), encoding="utf-8")

    if reindex and not dry_run and stats["imported"] > 0:
        try:
            from src.mv_proposal.config import Config
            from src.mv_proposal.context import build_context
            cfg = Config.load()
            ctx = build_context(cfg)
            ctx.image_lib.rebuild()
            stats["library_total"] = ctx.image_lib.count()
        except Exception as e:
            stats["reindex_error"] = str(e)

    return {"stats": stats, "items": written}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="从 PPTX 导入图片到图片库")
    ap.add_argument("pptx", help="PPTX 文件路径")
    ap.add_argument("--out", default=str(ROOT / "data" / "image_library"), help="图片库根目录")
    ap.add_argument("--type", dest="force_type", default=None, help="强制设备类型")
    ap.add_argument("--min-size", type=int, default=120, help="最小边长(像素)，过滤图标/Logo")
    ap.add_argument("--dry-run", action="store_true", help="只预览不写入")
    ap.add_argument("--include-orphans", action="store_true", help="同时导入未被幻灯片引用的图片")
    ap.add_argument("--prefix", default="", help="文件名前缀")
    ap.add_argument("--no-reindex", action="store_true", help="导入后不重建索引")
    args = ap.parse_args(argv)

    out_root = Path(args.out)
    res = import_pptx(Path(args.pptx), out_root, args.force_type, args.min_size,
                      args.dry_run, args.include_orphans, args.prefix, not args.no_reindex)
    s = res["stats"]
    print(f"幻灯片 {s['slides']} 页 | 导入 {s['imported']} 张"
          f"（跳过：小图 {s['skipped_small']} / 矢量图 {s['skipped_vector']} / 重复 {s['skipped_dup']}）")
    if s["by_type"]:
        print("按类型：" + "，".join(f"{DEVICE_LABELS.get(k, k)} {v} 张" for k, v in s["by_type"].items()))
    print("-" * 60)
    for it in res["items"]:
        p = f" 参数{it['params']}" if it["params"] else ""
        print(f"  [slide{it['slide']:>2}] {it['device_type']:<12} {it['file']}{p}")
    if args.dry_run:
        print("\n（dry-run：未写入任何文件）")
    elif s.get("library_total") is not None:
        print(f"\n图片库索引已重建，当前共 {s['library_total']} 张。")
    if s.get("reindex_error"):
        print(f"\n重建索引失败：{s['reindex_error']}")


if __name__ == "__main__":
    main()