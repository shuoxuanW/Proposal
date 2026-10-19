"""
批量提取方案书 PPTX 里的「工位/光路示意图」。

流程：PowerPoint 渲染每页为 PNG → VLM 判断是否工位图 → 是则提取结构 JSON
→ 存 data/station_diagrams/<项目>_<页>.png/.json。

用法：
  python -X utf8 scripts/build_station_library.py <pptx路径> [--max-slides N] [--out data/station_diagrams]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mv_proposal.config import Config
from src.mv_proposal.vision import VLMClient, VLM_AGENT_PROMPT

CLASSIFY_PROMPT = (
    "这是机器视觉方案书的一页。请判断这一页是不是「工位/光路布局示意图」"
    "（画了相机、镜头、光源、被测物、平台等设备的相对位置，以及光路/照明连线的原理图）。"
    "只回答一个字：是 或 否。"
)


def render_slides(ppt: Path, out_dir: Path, max_slides: int | None) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = ("if ($n -gt {m}) {{ $n = {m} }}\n".format(m=max_slides)) if max_slides else ""
    ps = (
        "$ErrorActionPreference='Stop'\n"
        "$ppt = New-Object -ComObject PowerPoint.Application\n"
        "$pres = $ppt.Presentations.Open('{p}', $true, $false, $false)\n".format(p=ppt)
        + "$n = $pres.Slides.Count\n"
        + cap
        + "for ($i=1; $i -le $n; $i++) {\n"
        + "  $pres.Slides.Item($i).Export('{o}\\slide' + $i + '.png', 'PNG', 1600, 1200)\n".format(o=out_dir)
        + "}\n"
        + "$pres.Close()\n$ppt.Quit()\n"
        + "[System.Runtime.Interopservices.Marshal]::ReleaseComObject($ppt) | Out-Null\n"
    )
    ps_file = out_dir / "_render.ps1"
    ps_file.write_text(ps, encoding="utf-8-sig")   # UTF-8 BOM，避免中文路径乱码
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps_file)],
        capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print("渲染失败:", r.stderr[-500:])
        return 0
    return len(list(out_dir.glob("slide*.png")))

def _process(ppt: Path, vlm, out: Path, max_slides: int | None,
             retry: int = 0, clean_temp: bool = False, force: bool = False):
    if ppt.name.startswith("~$"):
        print(f"[跳过] {ppt.name} 是 Office 临时锁文件")
        return
    proj = re.sub(r"[\\/:*?\"<>|]", "_", ppt.stem[:40])
    if not force and ((out / (proj + "_slide1.png")).exists()
                      or any((out / f).name.startswith(proj + "_") for f in out.glob("*.png"))):
        print(f"[跳过] {ppt.name} 已提取过")
        return
    tmp = ROOT / "_tmp_render" / proj
    n = 0
    for attempt in range(retry + 1):
        n = render_slides(ppt, tmp, max_slides)
        if n:
            break
        if attempt < retry:
            print(f"[重试 {attempt + 1}/{retry}] {ppt.name}")
    print(f"[{ppt.name}] 渲染 {n} 页")
    import base64
    from openai import OpenAI
    client = OpenAI(api_key=vlm._client.api_key, base_url=vlm._client.base_url)
    kept = 0
    for png in sorted(tmp.glob("slide*.png")):
        b64 = base64.b64encode(png.read_bytes()).decode()
        r = client.chat.completions.create(
            model=vlm.model, messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
                {"type": "text", "text": CLASSIFY_PROMPT}]}])
        verdict = (r.choices[0].message.content or "").strip()
        if "是" not in verdict:
            continue
        data = vlm.read_image(png, VLM_AGENT_PROMPT)
        name = f"{proj}_{png.stem}"
        (out / f"{name}.png").write_bytes(png.read_bytes())
        (out / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        kept += 1
        print(f"  ✓ {name} → {data.get("drawing_type")} | 部件 {len(data.get("component_list", []))} 个")
    print(f"[{ppt.name}] 提取 {kept} 张工位图")
    if clean_temp:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ppt", nargs="?")
    ap.add_argument("--max-slides", type=int, default=None)
    ap.add_argument("--out", default=str(ROOT / "data" / "station_diagrams"))
    ap.add_argument("--dir", default=None, help="批量：遍历目录下所有 pptx（按文件名去重）")
    ap.add_argument("--skip-existing", action="store_true", help="跳过已提取过的同名 pptx")
    ap.add_argument("--retry", type=int, default=0, help="渲染失败重试次数")
    ap.add_argument("--clean-temp", action="store_true", help="每个项目处理完后删除临时渲染目录")
    ap.add_argument("--force", action="store_true", help="已提取过的项目也重新提取")
    args = ap.parse_args()

    cfg = Config.load()
    vlm = VLMClient(cfg.vlm_base_url, cfg.vlm_api_key, cfg.vlm_model)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.dir:
        ppt_list = sorted((p for p in Path(args.dir).rglob("*.pptx")
                           if not p.name.startswith("~$")), key=lambda p: p.name)
        seen, unique = set(), []
        for p in ppt_list:
            if p.name not in seen:
                seen.add(p.name); unique.append(p)
        print(f"发现 {len(ppt_list)} 个 pptx，去重后 {len(unique)} 个")
        for p in unique:
            _process(p, vlm, out, args.max_slides, retry=args.retry, clean_temp=args.clean_temp, force=args.force)
        return

    if not args.ppt:
        print("需要提供 pptx 路径或 --dir 目录")
        sys.exit(1)
    _process(Path(args.ppt), vlm, out, args.max_slides, retry=args.retry, clean_temp=args.clean_temp, force=args.force)

if __name__ == "__main__":
    main()
