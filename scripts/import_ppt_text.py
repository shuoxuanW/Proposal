"""
从 PPT 提取文字 → 存成 Markdown → 填入知识库集合。

用法：
  python -X utf8 scripts/import_ppt_text.py 我的方案书.pptx --collection proposals
  python -X utf8 scripts/import_ppt_text.py 设备参数.pptx --collection devices
  python -X utf8 scripts/import_ppt_text.py 图例规范.pptx --collection legends

--collection 决定放进哪个知识库集合（proposals=方案范文 / devices=设备参数 / legends=图例规范）。
"""
from __future__ import annotations

import argparse
import html
import re
import zipfile
from pathlib import Path

TEXT_RE = re.compile(r"<a:t>(.*?)</a:t>", re.S)

ROOT = Path("D:/20261012")


def slide_number(name: str) -> int:
    m = re.search(r"slide(\d+)\.xml$", name)
    return int(m.group(1)) if m else 0


def extract_slides(zf: zipfile.ZipFile) -> list[tuple[int, list[str]]]:
    """返回 [(页码, [文字行...]), ...]，按段落提取。"""
    slides = sorted([n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)],
                    key=slide_number)
    result = []
    for s in slides:
        no = slide_number(s)
        xml = zf.read(s).decode("utf-8", "ignore")
        paras = re.findall(r"<a:p>.*?</a:p>", xml, re.S)
        lines = []
        for p in paras:
            texts = [html.unescape(t) for t in TEXT_RE.findall(p)]
            line = "".join(texts).strip()
            if line:
                lines.append(line)
        result.append((no, lines))
    return result


def to_markdown(slides: list[tuple[int, list[str]]]) -> str:
    parts = []
    for no, lines in slides:
        if not lines:
            continue
        parts.append(f"## 第 {no} 页")
        parts.extend(lines)
        parts.append("")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="从 PPT 提取文字填入知识库")
    ap.add_argument("pptx", help="PPTX 文件路径")
    ap.add_argument("--collection", default="proposals",
                    choices=["proposals", "devices", "legends"], help="目标知识库集合")
    ap.add_argument("--out", default=None, help="输出目录（默认 data/knowledge/<collection>）")
    args = ap.parse_args(argv)

    out_dir = Path(args.out) if args.out else ROOT / "data" / "knowledge" / args.collection
    out_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(args.pptx) as zf:
        slides = extract_slides(zf)
    md = to_markdown(slides)
    out = out_dir / (Path(args.pptx).stem + ".md")
    out.write_text(md, encoding="utf-8")
    print(f"已提取 {len(slides)} 页文字 -> {out}")
    print(f"下次生成时系统会自动索引该集合（或重启 Web 服务）。")


if __name__ == "__main__":
    main()