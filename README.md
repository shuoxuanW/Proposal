# 机器视觉解决方案书自动生成系统

多智能体协同 + 图片库知识库：输入项目需求，自动完成「需求解析 → 方案撰写 → 框架图生成 →
图文校验 → 汇总导出」全流程，生成带设备框架图的机器视觉解决方案书，并支持 Word/PDF 导出、
图文双向联动与人工修改素材回流。

## 系统架构

```
用户需求
   │
   ▼
┌──────────────────────────────────────────────────────────┐
│ 1 需求解析 Agent   需求 -> 任务大纲 + 设备选型 + 框架图规格   │
│ 2 方案撰写 Agent   生成正文，标记 [[FIG:]] / [[DEV:]] 锚点   │
│ 3 框架图生成 Agent 从图片库检索设备图片 -> 渲染框架图         │
│ 4 校验审核 Agent   图文一致性 / 锚点解析 / 图片完整性校验      │
│ 5 汇总输出 Agent   组装方案书 + 导出 + 生成图文联动注册表      │
└──────────────────────────────────────────────────────────┘
   │                              ▲
   ▼                              │ 人工修改素材回流
 知识库（文本 + 图片库） ◄──────────┘
```

- 图片库：设备实物图/示意图以「目录名 = 设备类型 + sidecar JSON 元数据」组织，建立向量索引，
  按设备类型 + 项目上下文检索。
- 框架图：纯 matplotlib 渲染（无 graphviz 依赖），节点框内嵌入检索到的设备图片，连线表示
  光路/数据链路，导出 PNG + SVG。
- 图文双向联动：正文锚点 `<->` 框架图 `<->` 设备节点 `<->` 图片素材 的双向映射写入 `linkage.json`。
- 素材回流：人工修改后的图片/正文可重新入库，形成「用 → 改 → 回 → 再用」闭环。

## 目录结构

```
├── config.yaml              # 全局配置（LLM/知识库/设备类型/导出格式）
├── main.py                  # 入口：python main.py <command>
├── src/mv_proposal/
│   ├── agents/              # 5 个 Agent
│   ├── diagram.py           # 框架图渲染
│   ├── document.py          # Markdown/HTML/Word/PDF 导出
│   ├── image_library.py     # 图片库知识库（扫描/索引/检索/入库）
│   ├── knowledge.py         # 文本知识库（向量检索/回流）
│   ├── linkage.py           # 图文联动注册表
│   └── pipeline.py          # 多智能体编排
├── data/
│   ├── image_library/       # 图片库（真实图片放这里）
│   ├── knowledge/           # 文本知识库素材
│   └── samples/             # 示例需求
├── scripts/build_sample_library.py  # 生成示例占位图片库
└── output/                  # 生成产物
```

## 快速开始

```powershell
# 1. 安装依赖
pip install -r requirements.txt

# 2. 生成示例占位图片库（接入真实图片后可跳过）
python -X utf8 scripts/build_sample_library.py

# 3. 配置 LLM（DeepSeek）
#    把 API Key 写入 .env（已内置）：DEEPSEEK_API_KEY=sk-xxx
#    其它 OpenAI 兼容服务（Qwen/OpenAI）改 config.yaml 的 llm 段即可

# 4. 离线跑通（不调用模型，纯本地逻辑）
python -X utf8 main.py demo --llm mock

# 5. 用 DeepSeek 真实生成
python -X utf8 main.py demo --llm deepseek

# 6. 指定自己的需求文件
python -X utf8 main.py generate 我的需求.md --llm deepseek
```

生成产物位于 `output/<时间戳>-<项目名>/`：

```
├── proposal.md / .html / .docx / .pdf   # 四种格式方案书
├── proposal.json                          # 结构化方案数据
├── linkage.json                           # 图文联动注册表
├── manifest.json                          # 汇总清单
└── figures/
    ├── framework-1.png / .svg             # 框架图（图片已嵌入节点）
    └── framework-1.positions.json         # 节点归一化坐标（联动定位）
```

## 从 PPT 导入图片库（推荐）

如果设备图片都在 PPT 里，直接用导入器批量抽取，无需手工整理：

```powershell
# 先把 PPT 放到 data/source/ 下（或任意路径），然后：
python -X utf8 main.py import-ppt data/source/我的图片库.pptx --dry-run   # 先预览
python -X utf8 main.py import-ppt data/source/我的图片库.pptx             # 正式导入并重建索引
```

导入器会：
1. 解包 `.pptx`，抽取 `ppt/media/` 中的图片（跳过 EMF/WMF 矢量图与过小图标/Logo，自动去重）；
2. 读取每页幻灯片的**文字**，按「标题(权重3) > 文件名(权重2) > 正文(权重1)」打分判定设备类型；
3. 从文字中解析 `分辨率: 2448x2048` 这类**参数键值对**；
4. 生成 `data/image_library/<设备类型>/图片.png + 同名.json` 元数据，并重建向量索引。

常用参数：`--type camera`（强制类型）、`--min-size 200`（过滤小图）、`--prefix 品牌A_`、
`--include-orphans`（导入未被引用的图片）、`--no-reindex`。

> 也可以直接用脚本：`python -X utf8 scripts/import_ppt.py 我的图片库.pptx`

## 接入你的真实图片库

把你的设备图片按下面结构放入 `data/image_library/`，并给每张图配一个同名 `.json` 元数据：

```
data/image_library/
├── light_source/
│   ├── 红色环形光源.png
│   └── 红色环形光源.json     # {"device_type":"light_source","name":"红色环形光源",
│                            #  "description":"低角度环形照明，突出划痕与凹坑",
│                            #  "params":{"外径":"90mm"},"tags":["环形光"]}
├── camera/
│   └── 500万像素相机.png + .json
└── ...（lens / controller / ipc / output / accessory）
```

设备类型枚举见 `config.yaml` 的 `framework.device_types`。图片库会自动扫描、向量化并重建索引
（`data/image_library/_index.json`），无需手动注册。

## 素材回流（人工修改后入库）

```powershell
# 人工修改后的图片入库（复制进图片库 + 写元数据 + 重建索引）
python -X utf8 main.py feedback image 新图.png --type light_source --name "紫外环形光源" --desc "..." --params "{\"波长\":\"365nm\"}"

# 人工修改后的正文/选型要点入库
python -X utf8 main.py feedback text 修改后的要点.md --kind feedback

# 查看知识库状态
python -X utf8 main.py kb
```

也可以在代码里调用 `FeedbackManager`（`src/mv_proposal/feedback.py`）：
`ingest_image()` / `ingest_text()` / `relink()`（更新某锚点对应设备的标注并回流）。

## 配置说明（config.yaml）

| 段 | 说明 |
|---|---|
| `llm` | `provider`（deepseek/dashscope/openai/mock）、`model`、`base_url`、`api_key_env` |
| `embedding` | 默认 `bge`（本地中文 BGE 模型，真实向量、离线）；也可切 `dashscope`/`openai` API，`hash` 仅兜底 |
| `framework` | 设备类型枚举、分组（采集/处理/执行）、默认光路链路 `chain` |
| `export` | `formats`（markdown/html/docx/pdf）、框架图 `image_dpi` |

## 校验规则（校验审核 Agent）

| 代码 | 级别 | 含义 |
|---|---|---|
| FIG_MISSING | error | 正文引用了未生成的图纸 |
| DEV_UNRESOLVED | error | 正文引用了不存在的设备节点 |
| CORE_DEVICE_MISSING | error | 框架图缺少光源/镜头/相机核心设备 |
| FIG_UNREFERENCED | warning | 图纸未被正文引用 |
| DEV_UNDESCRIBED | warning | 图中设备在正文缺少说明 |
| IMAGE_MISSING | warning | 设备未检索到图片（用占位框） |

## 预留扩展

- **VLM 图文校验**：`VerificationAgent` 已留扩展点，可接入 Qwen-VL/GPT-4o 对框架图做像素级图文一致性检查。
- **CLIP 以图搜图**：`embedding.provider` 可切换为多模态向量，支持「上传设备图 → 匹配库内同款」。
- **Web UI / 图片编辑器**：`linkage.json` + 节点归一化坐标已为前端画布编辑、图文联动预留数据接口。
- **Word/PDF**：已实现可直接导出，也保留了导出抽象，可按需替换为 docxtpl/WeasyPrint 精排。

## 服务与部署（FastAPI + Docker）

一键启动 HTTP 服务：

```powershell
uvicorn src.mv_proposal.server:app --host 0.0.0.0 --port 8000
# 或容器化
docker compose up --build
```

主要接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/kb/stats` | 知识库/图片库统计（embedding 类型、向量库路径） |
| POST | `/generate` | `{text, llm?}` 生成完整方案书 |
| POST | `/kb/query` | `{query, top_k, kind?}` 文本 RAG 检索 |
| POST | `/kb/search-images` | `?query=&device_type=&top_k=` 图片库检索 |
| POST | `/optic` | `{text}` 生成光路布局示意图 |
| POST | `/feedback/image` `/feedback/text` | 素材回流 |
| GET | `/outputs` `/output/{run_id}/{filename}` | 产物列表/下载 |

Docker 说明：镜像已装中文字体（fonts-noto-cjk）；知识库/输出/模型缓存/向量库以 volume 挂载；
`.env` 注入 API Key；`config.yaml` 里的 Windows 绝对路径会被 `MV_*` 环境变量覆盖（见 docker-compose.yml）。

## 测试


```powershell
python -X utf8 -m unittest discover -s tests -v
```