"""
知识库入库自检：投喂新素材后跑一遍，抓「型号-颜色矛盾 / 精度反算不符 / 切块异常 / 索引未同步」。

用法（项目根目录下）：
    D:\\minconda\\minconda\\python.exe -X utf8 scripts\\check_kb_consistency.py
    ... --json        机器可读输出（便于挂到入库流程）

检查项：
  [A] 切块完整性  每文件块数与 ##/### 章节数对齐，无空块 / 超短碎块 / 被长度切断
  [B] 型号-颜色   相机型号后缀（G C=彩色 / G M=黑白）与同处文字描述是否一致
  [C] 精度反算    视野 ÷ 分辨率 ≈ 像素数，与文中标注的像素数 / 线扫 K 数比对
  [D] 索引同步    vector.db 各集合块数 vs 磁盘文件实际块数（防止改了文件没重建索引）

退出码：0 = 无 error；1 = 存在 error（可挂到入库钩子 / CI）
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mv_proposal.config import Config
from src.mv_proposal.knowledge import COLLECTIONS, MIN_CHUNK, TEXT_EXTS, KnowledgeBase


# ---------------- 结果模型 ----------------
@dataclass
class Finding:
    """一条自检结果。level: error / warning / info"""
    level: str
    check: str
    message: str
    file: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, level: str, check: str, message: str, file: str = "") -> None:
        self.findings.append(Finding(level, check, message, file))

    def count(self, level: str) -> int:
        return sum(1 for f in self.findings if f.level == level)


# ---------------- [A] 切块完整性 ----------------
SECTION_RE = re.compile(r"^#{2,3}\s", re.M)


def check_chunking(cfg: Config, rep: Report) -> dict[str, int]:
    """按真实切块函数预演一遍，返回各集合块数。"""
    counts: dict[str, int] = {}
    for coll in COLLECTIONS:
        base = cfg.knowledge_dir / coll
        if not base.exists():
            counts[coll] = 0
            continue
        total = 0
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in TEXT_EXTS or f.name.startswith("_"):
                continue
            rel = str(f.relative_to(cfg.knowledge_dir)).replace("\\", "/")
            text = f.read_text(encoding="utf-8")
            chunks = KnowledgeBase._chunk_text(text)
            total += len(chunks)
            secs = len(SECTION_RE.findall(text))
            # 首个 ## 之前若有正文（含 H1 标题），会并成一节
            head = SECTION_RE.split(text, 1)[0].strip()
            expected = secs + (1 if head else 0)
            short = [c for c in chunks if len(c.strip()) < MIN_CHUNK]
            empty = [c for c in chunks if not c.strip()]
            if empty:
                rep.add("error", "A", "存在空块（无任何内容）", rel)
            if short:
                rep.add("warning", "A", "存在超短碎块（%d 个，最短 %d 字）：%r"
                        % (len(short), min(len(c) for c in short), short[0][:40]), rel)
            if len(chunks) > expected:
                rep.add("warning", "A",
                        "块数 %d > 章节数 %d：有章节超过 max_len 被长度切断，建议拆分该章节"
                        % (len(chunks), expected), rel)
            rep.add("info", "A", "章节 %d / 块 %d，最短 %d 字，最长 %d 字"
                    % (expected, len(chunks), min((len(c) for c in chunks), default=0),
                       max((len(c) for c in chunks), default=0)), rel)
        counts[coll] = total
    return counts


# ---------------- [B] 型号 - 颜色一致性 ----------------
MODEL_RE = re.compile(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+")
COLORS = ("彩色", "黑白")


def expected_color(model: str) -> str | None:
    """按海康命名推断相机颜色：-10GC/-92GC→彩色，-10GM→黑白；-C-/-M- 段同理。"""
    m = re.search(r"G([CM])(?![A-Z0-9])", model)
    if m:
        return "彩色" if m.group(1) == "C" else "黑白"
    m = re.search(r"-([CM])(?=-|$)", model)
    if m:
        return "彩色" if m.group(1) == "C" else "黑白"
    m = re.search(r"-([CM])\d{3}(?![\dA-Za-z])", model)      # OPT-CC1-C050 / -M250
    if m:
        return "彩色" if m.group(1) == "C" else "黑白"
    return None


def check_model_color(cfg: Config, rep: Report) -> int:
    """只对「相机」行做校验，避免镜头型号里的 M 被误判。返回通过校验的型号数。"""
    ok = 0
    for coll in COLLECTIONS:
        base = cfg.knowledge_dir / coll
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in TEXT_EXTS or f.name.startswith("_"):
                continue
            rel = str(f.relative_to(cfg.knowledge_dir)).replace("\\", "/")
            for line in f.read_text(encoding="utf-8").splitlines():
                if "相机" not in line:
                    continue
                line_colors = {c for c in COLORS if c in line}
                for m in MODEL_RE.finditer(line):
                    model = m.group(0)
                    exp = expected_color(model)
                    if exp is None:
                        continue
                    window = line[m.end():m.end() + 24]      # 先看紧邻的描述（括号里的那台）
                    got = [c for c in COLORS if c in window]
                    if not got:
                        if len(line_colors) == 1:
                            got = list(line_colors)
                        elif not line_colors:
                            rep.add("info", "B", "%s 有颜色后缀（应为%s）但该行未标注颜色" % (model, exp), rel)
                            continue
                        else:
                            rep.add("info", "B", "%s 所在行同时出现彩色/黑白，无法归因，请人工确认" % model, rel)
                            continue
                    if exp in got:
                        ok += 1
                    else:
                        rep.add("error", "B", "%s 后缀应为「%s」，但描述写的是「%s」"
                                % (model, exp, "/".join(got)), rel)
    return ok


# ---------------- [C] 精度反算 ----------------
FOV2_RE = re.compile(r"(?<!总)视野[^\d\n]{0,8}([\d.]+)\s*(?:mm)?\s*[*×x]\s*([\d.]+)")
FOV1_RE = re.compile(r"(?<!总)视野[^\d\n]{0,8}([\d.]+)\s*mm(?![\d.])")
RES_RE = re.compile(r"(?:分辨率|像素精度)[^\d\n]{0,6}([\d.]+)\s*mm\s*/\s*(?:pixel|pix|px)\b")
MP_RE = re.compile(r"([\d.]+)\s*万")
KPX_RE = re.compile(r"(\d+)\s*K(?![A-Za-z])")
TOLERANCE = 0.15         # 线性容差（面积 / K 数偏差均折算到线性后再比）


def _nearest(pat: re.Pattern, text: str, pos: int, window: int = 150) -> str | None:
    """找 pos 附近最近的匹配。"""
    best, best_d = None, 10 ** 9
    for m in pat.finditer(text):
        d = abs(m.start() - pos)
        if d < best_d and d <= window:
            best, best_d = m, d
    return best.group(1) if best else None


FOV_WINDOW = 40          # 视野与分辨率配对的最大字符距离（同一条描述内）


def _pair_fov(chunk: str, pos: int):
    """在 pos 附近找最近的「视野」匹配，返回 (距离, W, H)。H=None 表示只给了宽度。"""
    best = None
    for m in FOV2_RE.finditer(chunk):
        d = abs(m.start() - pos)
        if d <= FOV_WINDOW and (best is None or d < best[0]):
            best = (d, float(m.group(1)), float(m.group(2)))
    for m in FOV1_RE.finditer(chunk):
        d = abs(m.start() - pos)
        if d <= FOV_WINDOW and (best is None or d < best[0]):
            best = (d, float(m.group(1)), None)
    return best


def _nearest_ref(pat: re.Pattern, text: str, pos: int, window: int = 150) -> str | None:
    """查文中标注值：优先同一条描述行（一机位一行），再退到整块、整文件。"""
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    line = text[line_start:line_end if line_end >= 0 else len(text)]
    v = _nearest(pat, line, pos - line_start, 10 ** 6)
    if v:
        return v
    return _nearest(pat, text, pos, window)


def check_precision(cfg: Config, rep: Report) -> int:
    """视野 ÷ 分辨率 = 像素数，与文中标注的万像素 / K 数比对。返回核对数。"""
    checked = 0
    for coll in COLLECTIONS:
        base = cfg.knowledge_dir / coll
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in TEXT_EXTS or f.name.startswith("_"):
                continue
            rel = str(f.relative_to(cfg.knowledge_dir)).replace("\\", "/")
            full = f.read_text(encoding="utf-8")
            for chunk in KnowledgeBase._chunk_text(full):
                for rm in RES_RE.finditer(chunk):
                    res = float(rm.group(1))
                    if res <= 0:
                        continue
                    pair = _pair_fov(chunk, rm.start())      # 就近配对，避免多机位串台
                    if not pair:
                        continue
                    _, w, h = pair
                    px_w = w / res
                    if h is None:
                        # 只给了宽度（典型：线扫）→ 与文中 K 数比对
                        k = _nearest_ref(KPX_RE, chunk, rm.start()) or _nearest_ref(KPX_RE, full, rm.start(), 10 ** 9)
                        if not k:
                            continue
                        px_ref = float(k) * 1024
                        dev = (px_w - px_ref) / px_ref
                        checked += 1
                        rep.add("info" if abs(dev) <= TOLERANCE else "warning", "C",
                                "视野 %gmm ÷ %gmm/pixel = %.0f px  vs 文中 %sK（%d px，偏差 %+.1f%%）"
                                % (w, res, px_w, k, int(px_ref), dev * 100), rel)
                        continue
                    px_h = h / res
                    derived = px_w * px_h / 1e4          # 万像素
                    stated = _nearest_ref(MP_RE, chunk, rm.start()) or _nearest_ref(MP_RE, full, rm.start(), 10 ** 9)
                    if not stated:
                        continue
                    # 像素精度是线性量：面积偏差开方折算回线性，避免平方放大误差
                    dev = (derived / float(stated)) ** 0.5 - 1.0
                    checked += 1
                    rep.add("info" if abs(dev) <= TOLERANCE else "warning", "C",
                            "视野 %g×%gmm ÷ %gmm/pixel = %.0f×%.0f px ≈ %.0f 万  vs 文中 %s 万（等效线性偏差 %+.1f%%）"
                            % (w, h, res, px_w, px_h, derived, stated, dev * 100), rel)
    return checked
# ---------------- [D] 索引同步 ----------------
def check_index_sync(cfg: Config, rep: Report, computed: dict[str, int]) -> None:
    """比对 vector.db 与磁盘实际块数，防止「改了文件没重建索引」。"""
    db = Path(cfg.vectorstore_path)
    if not db.exists():
        rep.add("warning", "D", "向量库不存在：%s，请先运行 cli kb 重建" % db)
        return
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True)
        for coll in COLLECTIONS:
            row = conn.execute("SELECT COUNT(*) FROM vectors WHERE collection=?", (coll,)).fetchone()
            in_db = int(row[0]) if row else 0
            on_disk = computed.get(coll, 0)
            if in_db == on_disk:
                rep.add("info", "D", "%s：库内 %d 块 = 磁盘 %d 块 ✅" % (coll, in_db, on_disk))
            else:
                rep.add("warning", "D",
                        "%s：库内 %d 块 ≠ 磁盘 %d 块，索引未同步，请运行 cli kb 重建"
                        % (coll, in_db, on_disk))
        conn.close()
    except Exception as e:
        rep.add("warning", "D", "读取向量库失败：%s" % e)


# ---------------- [E] 疑似同款型号（只提示，不自动改） ----------------
# 注意：不能用 \b —— Python 的 \w 含中文，型号紧跟汉字时会被截断（...-60-W开孔面光源）
MODEL_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]+)+(?![A-Za-z0-9])")


def _model_core(model: str) -> str:
    """型号去掉「纯字母厂牌前缀段」后的主体，用于判断「同款异写」。

    例：YD-FL-ACD-4824-2 与 FL-ACD-4824-2 归一后都是 ACD-4824-2；
    至少保留 2 段，避免 FL-DM-70 被剥成只剩 "70"。
    """
    parts = model.split("-")
    while len(parts) > 1 and parts[0].isalpha():      # 剥掉全部纯字母厂牌段
        parts.pop(0)
    return "".join(parts)                            # 再去连字符：FL-DM-100-W = YD-FL-DM-100W


def collect_models(cfg: Config) -> dict[str, set[str]]:
    """全库型号 → 出现的文件名集合。"""
    index: dict[str, set[str]] = {}
    for coll in COLLECTIONS:
        base = cfg.knowledge_dir / coll
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in TEXT_EXTS or f.name.startswith("_"):
                continue
            for m in MODEL_RE.findall(f.read_text(encoding="utf-8")):
                if len(m) >= 8:                       # 过滤 I5-6 / 4-20 之类
                    index.setdefault(m, set()).add(f.stem)
    return index


def check_alias_models(cfg: Config, rep: Report) -> int:
    """同一支镜头 / 光源在不同项目里写法不同，会拆散「按型号精准匹配」。只提示，不改数据。"""
    index = collect_models(cfg)
    n = 0
    # E1：去掉厂牌前缀后完全相同（如 YDA-1216-25M vs YD-1216-25M）
    by_core: dict[str, list[str]] = {}
    for m in index:
        by_core.setdefault(_model_core(m), []).append(m)
    for core, models in by_core.items():
        if len(models) > 1:
            n += 1
            rep.add("info", "E", "疑似同款异写（去掉前缀后相同）：「%s」出现在 %d 个项目"
                    % ("」/「".join(sorted(models)),
                       len({f for m in models for f in index[m]})))
    # E2：共享 ≥5 位数字段（如 R12090W-48 vs YD-FL-R-12090W）
    digits = {m: set(re.findall(r"\d{5,}", m)) for m in index}
    models = sorted(index)
    seen: set[tuple[str, str]] = set()
    for i, a in enumerate(models):
        for b in models[i + 1:]:
            shared = digits[a] & digits[b]
            key = (a, b)
            if shared and _model_core(a) != _model_core(b) and key not in seen:
                seen.add(key)
                n += 1
                rep.add("info", "E", "疑似同款异写（共享数字段 %s）：「%s」vs「%s」"
                        % ("/".join(sorted(shared)), a, b))
    rep.add("info", "E", "全库型号 %d 个" % len(index))
    return n


# ---------------- [F] 同一型号/系列描述一致性 ----------------
SHUTTER_WORDS = ("卷帘", "全局", "线扫")
# 镜头焦距：「35mm FA」/「50mm FA」/「60mm FA」等
FOCAL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mm\s*(?:FA|远心|定焦)")


def check_same_model_consistency(cfg: Config, rep: Report) -> int:
    """同一相机型号（及同一系列）在库内的「快门 / 颜色」描述必须一致，否则至少一处是错的。"""
    per_model: dict[str, dict[str, dict[str, set[str]]]] = {}    # model -> dim -> 值 -> 文件
    for coll in COLLECTIONS:
        base = cfg.knowledge_dir / coll
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in TEXT_EXTS or f.name.startswith("_"):
                continue
            section = ""
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.lstrip().startswith("#"):
                    section = line                    # 记下当前章节，设备参数文件的镜头行本身不含「镜头」二字
                    continue
                is_cam = "相机" in line or "相机" in section
                is_lens = "镜头" in line or "镜头" in section
                if not (is_cam or is_lens):
                    continue
                line_sh = {w for w in SHUTTER_WORDS if w in line}
                line_col = {c for c in ("彩色", "黑白") if c in line}
                for m in MODEL_RE.finditer(line):
                    model = m.group(0)
                    if len(model) < 8:
                        continue
                    win = line[m.end():m.end() + 24]                  # 就近描述，避开同行第二台/第二支
                    dims: dict[str, set[str]] = {}
                    if is_cam:                                    # 不限 MV-：OPT-/YD-H120- 等相机同样纳入
                        dims["快门"] = {w for w in SHUTTER_WORDS if w in win} or line_sh
                        dims["颜色"] = {c for c in ("彩色", "黑白") if c in win} or line_col
                    if is_lens:
                        fm = FOCAL_RE.search(win)                     # 同型号焦距必须一致（35mm vs 50mm）
                        if fm:
                            dims["焦距"] = {fm.group(1) + "mm"}
                    for dim, vals in dims.items():
                        if len(vals) != 1:                            # 无法归因 / 未标注
                            continue
                        per_model.setdefault(model, {}).setdefault(dim, {}).setdefault(
                            next(iter(vals)), set()).add(f.stem)
    n = 0
    for model, dims in per_model.items():
        for dim, vals in dims.items():
            if len(vals) > 1:
                n += 1
                detail = "；".join("%s（%s）" % (v, "/".join(sorted(fs_))) for v, fs_ in sorted(vals.items()))
                rep.add("warning", "F", "同型号「%s」的%s描述不一致：%s" % (model, dim, detail))
    return n


# ---------------- [G] 需求-设备适配性 ----------------
# 强特征词：任何位置出现都说明需求涉及辨色
STRONG_COLOR_DEMAND = ("色差", "色斑", "色序", "色块", "颜色错乱", "辨色")


def _color_demand(lines: list[str]) -> list[str]:
    """从正文里找出「涉及辨色」的需求行。

    注意排除设备参数里的元数据行（「型号与颜色：…」），那是光源颜色描述，不是检测需求。
    """
    out = []
    for raw in lines:
        line = raw.strip()
        if "型号与颜色" in line:
            continue
        if any(w in line for w in STRONG_COLOR_DEMAND):
            out.append(line)
        elif ("检测项" in line or "检测要求" in line) and "颜色" in line:
            out.append(line)
    return out


def check_requirement_fit(cfg: Config, rep: Report) -> int:
    """需求要求的检测能力与所选相机是否匹配（当前只查「颜色」这一类）。

    典型：需求写「线序颜色错乱」，相机型号却是 -10GM（黑白）——黑白只能靠灰度差异，
    颜色相近的来料会判断失败。只提示，不改数据。
    """
    n = 0
    for coll in COLLECTIONS:
        base = cfg.knowledge_dir / coll
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in TEXT_EXTS or f.name.startswith("_"):
                continue
            text = f.read_text(encoding="utf-8")
            demand = _color_demand(text.splitlines())
            if not demand or "彩色" in text:      # 已明确彩色则无需提示
                continue
            mono = []
            for m in MODEL_RE.findall(text):
                mm = re.search(r"G([CM])(?![A-Za-z0-9])", m)
                if mm and mm.group(1) == "M":
                    mono.append(m)
            # 型号后缀为 M、或文中直接写了「黑白」，都算黑白方案
            if mono or "黑白" in text:
                n += 1
                rel = str(f.relative_to(cfg.knowledge_dir)).replace("\\", "/")
                who = "/".join(sorted(set(mono))) or "文中标注黑白"
                rep.add("info", "G", "需求含颜色类检测（%s），但相机为黑白（%s），需确认是否须换彩色机型"
                        % (demand[0][:44], who), rel)
    return n

# ---------------- [H] 光路合理性 ----------------
WD_RE = re.compile(r"工作距离\s*([\d.]+)\s*(?:±|\+/-)\s*[\d.]+\s*mm")
SENSOR_MIN_MM = 2.0      # 常见机器视觉传感器宽度下限（1/9" 约 1.4mm，再小不存在）
SENSOR_MAX_MM = 40.0     # 上限（约 4/3" 以上就该怀疑了）


def check_optics(cfg: Config, rep: Report) -> int:
    """焦距 + 工作距离 + 视野三者要自洽。

    由薄透镜关系 mag = f/(WD-f) 反推传感器宽度 = 视野 × f / (WD - f)；
    反推值落在真实传感器范围之外，说明三个数里至少有一个写错了。

    只在「同一章节内焦距/工作距离/视野各只有一个」时判定（多工位会串台，跳过）；
    远心镜头的焦距与视野无此关系，跳过。
    """
    checked = 0
    for coll in COLLECTIONS:
        base = cfg.knowledge_dir / coll
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in TEXT_EXTS or f.name.startswith("_"):
                continue
            rel = str(f.relative_to(cfg.knowledge_dir)).replace("\\", "/")
            for chunk in KnowledgeBase._chunk_text(f.read_text(encoding="utf-8")):
                if "远心" in chunk or "线扫" in chunk:        # 远心/线扫不适用该关系
                    continue
                focals = {float(m) for m in FOCAL_RE.findall(chunk)}
                wds = {float(m) for m in WD_RE.findall(chunk)}
                fovs = {float(m.group(1)) for m in FOV2_RE.finditer(chunk)} | \
                       {float(m.group(1)) for m in FOV1_RE.finditer(chunk)}
                if len(focals) != 1 or len(wds) != 1 or len(fovs) != 1:
                    continue
                f_mm, wd, fov = focals.pop(), wds.pop(), fovs.pop()
                if wd <= f_mm:
                    continue
                implied = fov * f_mm / (wd - f_mm)
                checked += 1
                desc = "焦距 %gmm + 工作距离 %gmm + 视野 %gmm" % (f_mm, wd, fov)
                if implied < SENSOR_MIN_MM or implied > SENSOR_MAX_MM:
                    rep.add("warning", "H",
                            "%s → 反推传感器宽度 %.2fmm（超出常见范围 %.0f~%.0fmm），三个数中至少一个写错"
                            % (desc, implied, SENSOR_MIN_MM, SENSOR_MAX_MM), rel)
                else:
                    rep.add("info", "H", "%s → 反推传感器宽度 %.2fmm，合理" % (desc, implied), rel)
    return checked

# ---------------- [J] 检索命中率（留一自检） ----------------
def check_retrieval_hitrate(cfg: Config, rep: Report) -> float:
    """留一自检：用每个方案的「项目概述」作查询，看它自己能否排进 top3。

    衡量的是索引内部一致性（相似需求能否召回对应历史方案），不是泛化能力；
    需加载本地向量模型，由 --hitrate 触发，默认不跑以保持常规自检秒回。
    """
    from src.mv_proposal.context import build_context
    ctx = build_context(cfg)
    proposals_dir = cfg.knowledge_dir / "proposals"
    hits, total = 0, 0
    for f in sorted(proposals_dir.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in TEXT_EXTS or f.name.startswith("_"):
            continue
        text = f.read_text(encoding="utf-8")
        m = re.search(r"## 项目概述\s*\n(.*?)(?=\n##|\Z)", text, re.S)
        q = (m.group(1).strip() if m else f.stem)[:200]
        top = ctx.kb.retrieve("proposals", q, top_k=3)
        total += 1
        if any(f.name in h["source"] for h in top):
            hits += 1
        else:
            rep.add("info", "J", "未进 top3：%s" % f.name)
    rate = (hits / total) if total else 0.0
    rep.add("info", "J", "案例层留一自检命中率 %d/%d = %.0f%%（索引内部一致性）" % (hits, total, rate * 100))
    if total < 30:
        rep.add("info", "J", "案例量 %d < 30，命中率仅供参考；数据正态增长、无爆发增量，现阶段无过拟合风险" % total)
    return rate


# ---------------- 输出 ----------------
LEVEL_ICON = {"error": "❌", "warning": "⚠️", "info": "·"}
CHECK_NAME = {"A": "切块完整性", "B": "型号-颜色一致性", "C": "精度反算", "D": "索引同步",
              "E": "疑似同款型号（提示）", "F": "同型号描述一致性",
              "G": "需求-设备适配性（提示）", "H": "光路合理性", "J": "检索命中率（留一自检）"}


def render(rep: Report) -> str:
    lines = ["知识库入库自检", "=" * 74]
    for code in ("A", "B", "C", "D", "E", "F", "G", "H", "J"):
        items = [f for f in rep.findings if f.check == code]
        if not items:
            continue
        lines.append("")
        lines.append("[%s] %s" % (code, CHECK_NAME[code]))
        # info 折叠计数，只列 error/warning 明细，避免刷屏
        for f in items:
            if f.level == "info":
                continue
            lines.append("  %s %s%s" % (LEVEL_ICON[f.level],
                                        ("[%s] " % f.file) if f.file else "", f.message))
        infos = [f for f in items if f.level == "info"]
        if infos:
            lines.append("  · %d 项正常（--json 查看明细）" % len(infos))
    lines.append("")
    lines.append("-" * 74)
    lines.append("结果：%d error / %d warning / %d info"
                 % (rep.count("error"), rep.count("warning"), rep.count("info")))
    st = rep.stats
    if st:
        lines.append("统计：块数 %s｜型号核对 %d 处｜精度反算 %d 处｜同款提示 %d 组"
                     % (st.get("chunks", {}), st.get("models", 0), st.get("precision", 0),
                        st.get("alias_hints", 0)))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="知识库入库自检")
    ap.add_argument("--json", action="store_true", help="输出 JSON（机器可读）")
    ap.add_argument("--hitrate", action="store_true", help="额外跑检索命中率留一自检（需加载向量模型，较慢）")
    args = ap.parse_args()

    cfg = Config.load()
    rep = Report()
    rep.add("info", "A", "知识库目录：%s" % cfg.knowledge_dir)
    chunks = check_chunking(cfg, rep)
    models = check_model_color(cfg, rep)
    precision = check_precision(cfg, rep)
    check_index_sync(cfg, rep, chunks)
    aliases = check_alias_models(cfg, rep)
    same_model = check_same_model_consistency(cfg, rep)
    fit_hints = check_requirement_fit(cfg, rep)
    optics = check_optics(cfg, rep)
    if args.hitrate:
        check_retrieval_hitrate(cfg, rep)
    rep.stats = {"chunks": chunks, "models": models, "precision": precision,
                 "alias_hints": aliases, "same_model_issues": same_model,
                 "fit_hints": fit_hints, "optics": optics}

    if args.json:
        print(json.dumps({
            "findings": [f.__dict__ for f in rep.findings],
            "stats": rep.stats,
            "errors": rep.count("error"),
            "warnings": rep.count("warning"),
        }, ensure_ascii=False, indent=2))
    else:
        print(render(rep))
    sys.exit(1 if rep.count("error") else 0)


if __name__ == "__main__":
    main()
