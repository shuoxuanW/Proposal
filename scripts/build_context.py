"""
从 2D 手册提取「行业产品(2.5D 系统) + 应用案例 + 产品特性」，并与已入库型号双向关联。

产出（合并进 products.json）：
  industry 分组：相位偏折(MV-HLVS/MV-PMDA)、光度立体(MV-PSA) 2.5D 系统型号
  context  分组：应用案例（应用场景/识别难点/检测效果 → 关联型号清单）
  并给每个 2.5D 型号回填「应用场景」字段
"""
from __future__ import annotations
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TXT = ROOT / "_tmp_2d.txt"       # 需先由 dump 生成
OUT = ROOT / "data" / "catalog" / "products.json"


def main():
    lines = open(TXT, encoding="utf-8").read().splitlines()

    # ---- 1) 行业产品型号 ----
    industry = []
    seen = set()
    for ln in lines:
        ln = ln.strip()
        m = re.search(r"(MV-HLVS-[\w-]+)", ln)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            e = {"model": m.group(1), "类型": "相位偏折2.5D系统(线阵)"}
            f = re.search(r"(\d+)\s*mm", ln)
            if f: e["光源长度mm"] = int(f.group(1))
            f = re.search(r"(白光|红外)", ln)
            if f: e["光源波长"] = f.group(1)
            industry.append(e); continue
        m = re.search(r"(MV-PMDA-[\w-]+)", ln)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            e = {"model": m.group(1), "类型": "相位偏折2.5D系统(面阵同轴)"}
            f = re.search(r"(\d+)\s*[×x]\s*(\d+)", ln)
            if f: e["分辨率"] = "%s×%s" % (f.group(1), f.group(2))
            f = re.search(r"([\d.]+)\s*fps", ln)
            if f: e["帧率fps"] = float(f.group(1))
            f = re.search(r"(USB3.0|10GigE|GigE|CoaXPress)", ln)
            if f: e["接口"] = f.group(1)
            f = re.search(r"(\d+)\s*mm\s*[×x]\s*(\d+)\s*mm", ln)
            if f: e["发光区"] = "%s×%smm" % (f.group(1), f.group(2))
            industry.append(e); continue
        m = re.search(r"(MV-PSA-[\w-]+)", ln)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            e = {"model": m.group(1), "类型": "光度立体2.5D系统"}
            f = re.search(r"(\d+)\s*[×x]\s*(\d+)", ln)
            if f: e["分辨率"] = "%s×%s" % (f.group(1), f.group(2))
            f = re.search(r"([\d.]+)\s*fps", ln)
            if f: e["帧率fps"] = float(f.group(1))
            f = re.search(r"(USB3.0|10GigE|GigE|CoaXPress)", ln)
            if f: e["接口"] = f.group(1)
            f = re.search(r"Φ\s*(\d+)\s*mm", ln)
            if f: e["发光区直径mm"] = int(f.group(1))
            industry.append(e)

    # ---- 2) 应用案例 ----
    context = []
    series_ctx = "相位偏折2.5D系统"    # 按最近出现的章节标题切换
    for i, ln in enumerate(lines):
        if "相位偏折 2.5D" in ln or "相位偏折2.5D" in ln:
            series_ctx = "相位偏折2.5D系统"
        if "光度立体 2.5D" in ln or "光度立体2.5D" in ln:
            series_ctx = "光度立体2.5D系统"
        m = re.search(r"应用场景：(.+)", ln)
        if not m:
            continue
        scene = m.group(1).strip()
        scene = re.sub(r"[\s\u3000]+", " ", scene)
        scene = scene.strip("阵工外相面机业级头")[:100]
        # 找后续几行的 识别难点 / 检测效果
        diff = eff = ""
        for j in range(i + 1, min(i + 6, len(lines))):
            l2 = lines[j]
            dm = re.search(r"识别难点[:：](.+)", l2)
            em = re.search(r"检测效果[:：](.+)", l2)
            if dm and not diff: diff = dm.group(1).strip()[:100]
            if em and not eff: eff = em.group(1).strip()[:100]
            if diff and eff: break
        context.append({"系列": series_ctx, "应用场景": scene, "识别难点": diff, "检测效果": eff})

    # 给每个行业型号回填 应用场景（所属系列对应）
    for e in industry:
        scenes = [c["应用场景"] for c in context
                  if (e["类型"].startswith("相位偏折") and c["系列"].startswith("相位偏折"))
                  or (e["类型"].startswith("光度立体") and c["系列"].startswith("光度立体"))]
        if scenes:
            e["应用场景"] = "；".join(scenes[:3])

    d = json.load(open(OUT, encoding="utf-8"))
    d["industry"] = industry
    d["context"] = context
    json.dump(d, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("行业产品 %d 款 / 应用案例 %d 条" % (len(industry), len(context)))
    for e in industry[:4]:
        print("  ", json.dumps(e, ensure_ascii=False))
    for c in context:
        print("  [%s] %s" % (c["系列"], c["应用场景"][:36]))


if __name__ == "__main__":
    main()
