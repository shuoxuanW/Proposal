# Agent Handoff — 机器视觉方案书系统（2026-10-17）

> **文档用途**：给后续 Agent 读取的交接文档，说明“已经做完什么、还没做什么、当前状态、如何验证、哪些地方不能乱动”。  
> **重要**：第 12/13 节是最新状态；第 1-11 节保留为历史记录。当前工位图库为 37 张、回归测试 60 项、`_tmp_render` 已清理。  
> **项目根目录**：`D:\20261012`  
> **服务地址**：`http://127.0.0.1:8000/web/`  
> **生成时服务进程**：PID `39324`（重启后会变化，不要把它当作固定值）  
> **最后验证时间**：2026-10-19（描述性设备参数误报修复）

---

## 0. 先读这里

1. 这不是 git 仓库，没有 commit 历史。所有改动都是**直接改文件**，后续 Agent 需要以当前文件系统状态为准。
2. 工位图库的权威数据目录是：
   ```text
   D:\20261012\data\station_diagrams
   ```
   共 37 张 PNG + 37 个同名 JSON（4 张早期测试图已归档）。
3. **不要随意重跑全量工位图提取**。全量跑一次约 21 分钟并会产生大量外部 VLM 调用；除非明确要更新图库。
4. 修改 `data/station_diagrams` 后，**必须重启服务**，因为 `StationLibrary` 在服务启动时构建索引。
5. 当前服务用 Mock 模式只验证召回/前端展示；要验证 LLM 真正参与工位布局，必须使用 **DeepSeek**。
6. 前端静态资源版本为 `20261017e`；改完 `web/` 后按 Ctrl+F5 强制刷新。

---

## 1. 当前系统状态

| 项目 | 状态 |
|---|---|
| FastAPI 服务 | 运行中，端口 8000 |
| 前端页面 | 可访问，工位图库面板可加载 37 张图 |
| 工位图库 | 37 张，27 个真实项目（4 张早期测试图已归档） |
| sidecar JSON 损坏数 | 0 |
| 回归测试 | 71 项全部通过 |
| 最新 DeepSeek 陶瓷片生成 | 校验通过，命中工位图 0.7785 |
| 最新全量提取日志 | `output/station_build_full_20261017.log` |
| 中间渲染目录 `_tmp_render` | 已清理（原 184 MB） |

---

## 2. 当前主流程

```text
POST /generate
  └─ pipeline.generate()
       ├─ build_context()（LLM / KB / image_lib / template_lib / station_lib）
       ├─ recall_cases(requirement_text)
       │    └─ 生成 matched_cases（文本方案案例，阈值 0.72，top_k=3，按 source 去重）
       ├─ RequirementAgent.run(text, case_ref=matched_cases)
       │    ├─ 需求解析（DeepSeek 或 Mock）
       │    └─ _attach_station_layout()
       │         ├─ station_lib.search(text, top_k=1)
       │         ├─ score ≥ 0.55 → 生成 station_ref，注入布局 Prompt
       │         ├─ reason_station_layout(text, llm, case_text, station_ref)
       │         └─ plan.layout_reasoning.station_hit = {id, project, drawing_type, score}
       ├─ WritingAgent(case_ref)
       ├─ DrawingAgent
       │    ├─ station 图：多工位渲染器 + 知识库相机/光源模板图
       │    ├─ workpiece 图
       │    └─ detection 图
       ├─ VerificationAgent
       ├─ AssemblyAgent
       └─ manifest + matched_cases + exports

POST /chat
  └─ advisor.advise()（选型对话；目前不使用工位图库）
```

---

## 3. 已经完成的事情

### 3.1 文本案例召回接入 PPT 生成

**状态：完成**

- `pipeline.generate()` 在需求解析之前先调用 `recall_cases`。
- 命中案例同时用于：
  - 需求解析 / 工位布局（`case_ref`）
  - 正文撰写（`WritingAgent.case_ref`）
  - 前端参考来源展示（`matched_cases`）
- `manifest.json` 与 `/generate` 返回值均包含 `matched_cases`。
- 同一份方案多个文本块按 `source` 去重，只保留最高分。

**关键文件：**

- `src/mv_proposal/pipeline.py`
- `src/mv_proposal/selection.py`
- `src/mv_proposal/agents/writing.py`

---

### 3.2 LLM 选择修复

**状态：完成**

- `/generate` 复用服务端 ctx 时，之前会忽略请求里的 `llm=mock`，继续使用 DeepSeek。
- 现在显式指定 `mock` / `deepseek` 时会替换轻量 LLM 客户端，复用知识库，不再错误调用外部模型。

**关键文件：**

- `src/mv_proposal/pipeline.py`

---

### 3.3 多工位光路图重构

**状态：完成**

新增 `StationUnit`，每个工位独立拥有：

- 工件（形状 / 名称 / 尺寸）
- 相机（位置 / 朝向 / 镜头 / 分辨率）
- 光源（位置 / 类型 / 角度）
- 工作距离 WD
- 视场 FOV
- 精度

渲染器支持：

- 工位1/工位2 配置相同时自动合并
- 独立面板、标题、检测项、精度、视场、WD
- 成像光轴、FOV 光锥、照明光线、基准平台、遮光罩轮廓、图例
- 侧视相机方向正确朝向工件
- 相机和光源优先使用知识库模板图片
- 中文词组、型号、单位不被错误截断

**关键文件：**

- `src/mv_proposal/models.py`
- `src/mv_proposal/station.py`
- `src/mv_proposal/diagram.py`
- `src/mv_proposal/agents/drawing.py`
- `src/mv_proposal/agents/requirement.py`

---

### 3.4 历史工位图库全量提取

**状态：完成**

| 项目 | 数量 |
|---|---:|
| 扫描 pptx | 48 |
| 文件名去重后 | 47 |
| Office `~$` 临时锁文件 | 2（已跳过） |
| 真实唯一方案书 | 45 |
| 已提取过、跳过 | 3 |
| 本次实际处理 | 42 |
| 本次新提取 | 32 |
| 工位图库总量 | 41 |
| 真实项目 | 27 |
| 早期测试图 | 4（slide5/6/7/11） |
| sidecar JSON 损坏 | 0 |
| 部件总数 | 194（平均 4.7/张，最多 8） |

**全量命令：**

```powershell
D:\minconda\minconda\python.exe -X utf8 scripts\build_station_library.py `
  --dir "C:\Users\Admin\Desktop\方案书\方案书" --skip-existing
```

**关键文件：**

- `scripts/build_station_library.py`
- `data/station_diagrams/`

---

### 3.5 工位图检索元数据增强

**状态：完成**

`StationLibrary._scan()` 现在会把以下内容拼入检索文本：

- 文件名（含项目名、日期、图号）
- 去掉 `_slideN` 的项目名
- `drawing_type`
- `view_type`
- 每个部件的名称 + 位置
- 完整 `note`（不再只截取前 80 字）

检索结果额外返回：

- `project`
- `drawing_type`
- `score`

**关键文件：**

- `src/mv_proposal/station_library.py`

---

### 3.6 历史工位图作为布局参考

**状态：完成**

- 在 `RequirementAgent._attach_station_layout()` 中先检索工位图。
- **Top1 ≥ 0.55** 时，把 sidecar JSON 的部件/连线/备注拼成 `station_ref`，注入布局 LLM Prompt。
- 未命中时纯 LLM 推理。
- `plan.layout_reasoning.station_hit` 记录：
  - `id`
  - `project`
  - `drawing_type`
  - `score`
- `/generate` 返回时补充 `image_url`，前端可显示历史图缩略图。

**关键文件：**

- `src/mv_proposal/agents/requirement.py`
- `src/mv_proposal/station.py`
- `src/mv_proposal/server.py`

---

### 3.7 前端补全

**状态：完成**

新增/完善：

1. 顶部知识库状态：
   ```text
   工位图 41（27 项目）
   ```
2. 左侧「3. 参考来源」：
   - 历史方案文本卡片
   - 历史工位图卡片（缩略图 + 项目 + 图类型 + 相似度）
   - 布局生成方式卡片
3. 「📚 历史工位图库」面板：
   - 37 张缩略图
   - 关键词检索
   - 显示全部
   - 点击查看原图
4. 生成按钮加载态、错误提示、HTML 转义。
5. 前端版本号：`20261017e`。

**关键文件：**

- `web/index.html`
- `web/app.js`
- `web/style.css`
- `src/mv_proposal/server.py`

---

### 3.8 接口补全

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/kb/stats` | 增加 `stations`、`station_projects` |
| GET | `/station-library/list` | 列出全部工位图 |
| POST | `/station-library/search` | 关键词检索工位图 |
| GET | `/station-lib/<id>.png` | 直接访问工位图原图 |
| POST | `/generate` | `layout_reasoning.station_hit.image_url` |

---

## 4. 还没完成 / 待办事项

> 以下内容是后续 Agent 最需要关注的部分。

### P0 — 影响核心效果

#### TODO-1：电池螺丝没有专用工位图

**现状：**

- 全量提取时，`20260318-铨讯电池螺丝有无检测方案书.pptx` **没有提取到工位图**。
- 电池螺丝需求目前只能命中相近的「电池外壳缺陷检测」工位图（约 0.75）。
- 文本案例仍能正确命中「电池螺丝有无检测视觉方案」（约 0.88）。

**影响：**

- 电池螺丝工位图会参考电池外壳图，布局细节可能不够贴合。

**建议：**

- 找到一份带「电池螺丝工位/打光示意图」的方案书重新提取；
- 或手工制作一张电池螺丝工位图，放入 `data/station_diagrams/`，配套 sidecar JSON。

---

#### TODO-2：检索精度仍需 reranker / 业务过滤

**现状：**

- 已做元数据增强，陶瓷片、螺纹牙套 Top1 正确；
- 但宽泛查询仍可能召回通用工位图（例如电池查询的 Top2/Top3 出现 FFC）。
- 当前布局注入阈值固定为 `0.55`。

**建议：**

- 增加 reranker（按产品/工艺关键词加权）；
- 或在 `station_library.search()` 中加入项目名、产品名、工艺词过滤；
- 用真实需求集做一轮阈值校准（0.50 / 0.55 / 0.60 对比）。

---

#### TODO-3：新多工位路径尚未支持“直接 sidecar 重画”

**现状：**

- 新 `station` 路径把历史工位图作为 **LLM 参考**，不是直接替换。
- 旧 `optic` 路径（`/optic`）仍保留“命中 sidecar → 直接 render_schematic”的能力。
- 两条路径的行为不完全一致。

**建议：**

- 明确策略：
  - A. 高置信命中（例如 ≥0.75）→ 直接 sidecar 重画；
  - B. 中置信（0.55~0.75）→ 仅作为 LLM 参考；
  - C. 低置信 → 纯 LLM。
- 如果采用 A，需要在 `DrawingAgent` 的 `station` 分支增加检索与直接渲染逻辑。

---

### P1 — 数据/前端体验

#### TODO-4（已完成 17:20）：清理工位图中的早期测试图

**现状：**

- `slide5.png`、`slide6.png`、`slide7.png`、`slide11.png` 是早期测试生成的文件。
- 这 4 张已归档到 `data/station_diagrams/_archive_20261017/`，不再计入图库。

**建议：**

- 确认无引用后移出 `data/station_diagrams`；
- 或给它们加 `is_test=true` 元数据并在前端过滤。

---

#### TODO-5（已完成 17:20）：清理 `_tmp_render`

**现状：**

- `_tmp_render/` 原约 184 MB（44 个项目目录，605 个逐页 PNG），已于 17:20 清理。
- 这些是批量提取的中间产物，提取完成后不再需要。

**建议：**

- 增加 `--clean-temp` 参数；
- 或在脚本结束时删除当前项目的临时目录；
- 手工清理前确认目标路径是 `D:\20261012\_tmp_render`。

---

#### TODO-6：图库检索 UI 的噪声

**现状：**

- `/station-library/search` 返回 Top 24；
- 前端会显示低分结果（例如 0.30 左右），可能造成“图库很大但很杂”的观感。

**建议：**

- 前端增加最低分过滤（例如 0.35）；
- 或后端在 search 中返回 `score >= threshold` 的结果；
- 结果卡片显示分数，便于人工判断。

---

#### TODO-7：sidecar JSON 缺少结构化业务字段

**现状：**

- sidecar JSON 目前主要是 VLM 提取的：
  - `drawing_type`
  - `view_type`
  - `component_list`
  - `connection_list`
  - `note`
- 检索文本通过文件名和 note 补足业务语义，但没有结构化字段：
  - `product_name`
  - `process_name`
  - `customer`
  - `keywords`

**建议：**

- 在提取脚本中增加业务字段；
- 或在 sidecar JSON 中补充 `meta` 段；
- 便于后续做精确过滤和 reranker。

---

### P2 — 工程化/稳定性

#### TODO-8：前端自动化 E2E 测试

**现状：**

- 已用浏览器人工/半自动验证：
  - 37 张图库
  - 搜索「陶瓷片」
  - Mock 生成结果卡片与缩略图
- 但没有把 E2E 测试写入仓库。

**建议：**

- 增加 Playwright 测试：
  - 图库加载 37 张
  - 搜索「陶瓷片」Top3
  - Mock 生成后 `#sources` 出现文本案例/工位图卡片
  - 生成按钮 loading 状态

---

#### TODO-9：工位图库版本快照

**现状：**

- 已生成快照：`data/station_diagrams_versions/station_diagrams_20261017.zip`。

**建议：**

- 定期打包为 `station_diagrams_YYYYMMDD.zip`；
- 或在 sidecar JSON 中加 `version` / `created_at`。

---

#### TODO-10：批量脚本的健壮性

**现状：**

- 已跳过 `~$` Office 临时文件；
- 但其他渲染失败只记录日志，不重试；
- 按文件名去重，可能跳过同名但内容不同的 pptx。

**建议：**

- 增加失败重试（1~2 次）；
- 去重时使用 `文件名 + 文件大小/哈希`，避免误跳过不同版本；
- 支持 `--only` / `--exclude` 参数。

---

#### TODO-11：`/optic` 与 `/generate` 行为不一致

**现状：**

- `/generate` 使用新的多工位 `station` 渲染器；
- `/optic` 仍主要走旧的 `schematic` 路径；
- 前端「仅生成光路示意图」按钮与「生成 PPT 方案书」的图可能不同。

**建议：**

- 明确 `/optic` 的定位（快速草图 vs 正式图）；
- 或让它复用新的多工位渲染器。

---

#### TODO-12：对话流程的 Mock 限制

**现状：**

- Mock 模式下 `advisor.advise()` 返回 `requirement=""`；
- 前端只有 `sufficient && requirement` 时才自动回填需求框。

**影响：**

- Mock 模式对话不会自动填充「输入项目需求」。

**建议：**

- Mock 模式也生成结构化 requirement 文本；
- 或在 UI 上明确提示“Mock 模式不会回填”。

---

## 5. 关键文件与职责

| 文件 | 职责 |
|---|---|
| `src/mv_proposal/pipeline.py` | 主流程、案例召回、manifest 回写 |
| `src/mv_proposal/selection.py` | 案例召回、去重、选型 |
| `src/mv_proposal/station.py` | 多工位布局推理 Prompt / JSON 解析 |
| `src/mv_proposal/station_library.py` | 工位图库扫描、索引、检索 |
| `src/mv_proposal/diagram.py` | 多工位渲染、相机/光源图标/图片、换行 |
| `src/mv_proposal/server.py` | FastAPI 接口、静态资源、工位图接口 |
| `src/mv_proposal/agents/requirement.py` | 需求解析、工位图检索与参考注入 |
| `src/mv_proposal/agents/writing.py` | 正文撰写、案例 Prompt |
| `src/mv_proposal/agents/drawing.py` | 知识库相机/光源模板绑定 |
| `src/mv_proposal/agents/assembly.py` | 方案书组装、导出 |
| `web/index.html` | 页面结构、图库面板 |
| `web/app.js` | 生成结果、参考来源、图库检索 |
| `web/style.css` | 新面板、卡片、缩略图样式 |
| `scripts/build_station_library.py` | 批量提取工位图 |
| `tests/test_pipeline.py` | 主流程回归 |
| `tests/test_selection.py` | 案例召回/选型回归 |
| `tests/test_station_layout.py` | 多工位布局回归 |

---

## 6. 数据与检索实测

### 6.1 检索校准（完整需求文本）

| 用例 | 文本案例 Top1 | 工位图 Top1 | 工位图分数 |
|---|---|---|---:|
| 陶瓷片 | 陶瓷片尺寸检测视觉方案 | 铨讯 陶瓷片尺寸检测方案 0514 RevB | 0.7785 |
| 螺纹牙套 | 金属加工件螺纹牙套视觉检测方案 | 20260515诠讯加工件螺纹有无视觉检测方案书(1) | 0.7269 |
| 电池 | 电池螺丝有无检测视觉方案 | 20260812 电池外壳缺陷检测 | 0.7516 |
| 苹果负向短文本 | 未命中 | 未命中（Top1 0.5132 < 0.55） | — |

### 6.2 关键实测产物

| 产物 | 路径 |
|---|---|
| 陶瓷片 DeepSeek 方案 | `output/20261017-152255-陶瓷片外轮廓尺寸视觉检测` |
| 大型电池 DeepSeek 方案 | `output/20261017-143310-大型电池螺丝钉有无检测` |
| 螺纹牙套多工位方案 | `output/20261017-140811-金属加工件多工位视觉检测` |
| 全量提取日志 | `output/station_build_full_20261017.log` |
| 工位图库 | `data/station_diagrams` |

---

## 7. 验证命令

### 启动服务

```powershell
cd D:\20261012
D:\minconda\minconda\python.exe -X utf8 run_server.py
```

### 健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

### 知识库统计

```powershell
Invoke-RestMethod http://127.0.0.1:8000/kb/stats
```

预期关键字段：

```json
{
  "stations": 41,
  "station_projects": 27
}
```

### 工位图检索

```powershell
$body = @{ query = "陶瓷片尺寸检测"; top_k = 3 } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/station-library/search `
  -Method Post -ContentType "application/json; charset=utf-8" `
  -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

### 回归测试

```powershell
D:\minconda\minconda\python.exe -X utf8 -m unittest discover -s tests
```

预期：

```text
Ran 71 tests
OK
```

---

## 8. 不要破坏的东西（Gotchas）

1. `pipeline.generate()` 中 **案例召回必须在需求解析之前**；否则工位布局拿不到 `case_ref`。
2. `manifest.json` 由 `AssemblyAgent` 先写盘；`matched_cases` 是之后补写的。改动顺序时务必保证最终 `manifest.json` 仍包含 `matched_cases`。
3. `station_hit` 的阈值是 **0.55**，修改前先做检索回归，避免误命中或全部不命中。
4. `StationLibrary` 在服务启动时构建索引；新增/删除工位图后必须重启服务。
5. `/station-lib` 静态目录依赖 `data/station_diagrams` 存在；如果移动目录，必须同步改 `server.py` 的 mount。
6. 知识库模板图片路径是相对于 `data/image_templates` 的；不要在 `cam.photo` 中存绝对路径。
7. Mock 模式不会真正调用布局推理；不要用 Mock 结果判断工位图是否被 LLM 使用。
8. 前端静态资源版本号在 `web/index.html`；修改 JS/CSS 后 bump 版本并 Ctrl+F5。
9. 批量脚本按文件名去重；同名不同内容的 pptx 会被跳过，这是已知限制。
10. `.env` 中包含 DeepSeek / DashScope API key，不要写入文档或提交到外部服务。

---

## 9. 推荐后续顺序

1. **补电池螺丝专用工位图**（P0，直接影响电池用例效果）。
2. **加 reranker / 业务关键词过滤**（P0，提升宽泛查询准确率）。
3. **明确“直接 sidecar 重画 vs LLM 参考”策略**（P0，统一 `/generate` 与 `/optic` 行为）。
4. 早期测试图和 `_tmp_render` 已清理（P1 已完成）。
5. 给 sidecar JSON 增加结构化业务字段（P1）。
6. 增加 Playwright E2E 测试（P2）。
7. 做图库版本快照（P2）。

---

## 10. 快速测试用例

| 用例 | 输入要点 | 预期 |
|---|---|---|
| 陶瓷片 | 5.6±0.1mm，远心+背光，±0.01mm | 文本案例 ~0.90；工位图 RevB ~0.78 |
| 螺纹牙套 | 156×94mm，4处牙套孔+2处小孔毛边，三工位 | 文本案例 ~0.91；工位图 ~0.73 |
| 大型电池 | MAX 560×460×120mm，顶/底/四侧螺丝 | 文本案例 ~0.88；工位图 ~0.75（电池外壳） |
| 苹果负向 | `苹果表面碰伤、虫眼、裂口分级，5个/秒` | 文本/工位图均未命中，纯 LLM |

---

## 11. 相关文档

- 已完成事项汇总：`D:\20261012\完成事项总结_20261017.md`
- 项目原有进度：`D:\20261012\PROGRESS.md`
- 项目计划：`D:\20261012\PLAN.md`

---

*最后更新：2026-10-17*

---

## 12. 2026-10-17 17:00 更新：动态 PPT + 参数校验已上线

> 这一节是最新状态，优先阅读。前面章节保留为历史记录。

### 12.1 本次完成（P0）

#### A. 动态 PPT：模板不再写死

新增模块：

```text
src/mv_proposal/ppt/
  __init__.py
  profile.py      # 读取 visual_proposal_profile.yaml
  planner.py      # 根据内容规划附录页
  appendix.py     # 按模板风格渲染附录页
```

新增模板画像：

```text
data/templates/visual_proposal_profile.yaml
```

`ppt_export.py` 已改为：

- 基础页：封面 / 目录 / 版本审阅 / 客户需求 / 检测说明 / 打光示意图 / 相机2 / Thanks
- 动态页：设备选型建议 + 附录
- 基础页的页序、形状名、颜色、字体从 YAML 读取，不再完全写死在代码里
- 附录页由 `SlidePlanner` 决定，不再受模板 8 页限制

#### B. 动态章节：8 章 → 12 章

`RequirementAgent._build_chapters()` 现在生成：

```text
ch1  项目概述
ch2  需求分析
ch3  总体方案设计
ch4  系统组成与光路布局
ch5  设备选型说明
ch6  系统软件与算法
ch7  安装调试与验收
ch8  服务与售后
ch9  检测效果与缺陷样张
ch10 验证数据与验收指标
ch11 风险与注意事项
ch12 设备参数汇总（有设备时）
```

WritingAgent 已补充 ch9~ch12 的 Mock 模板；LLM 模式仍按章节标题生成。

#### C. PPT 页面：8 页 → 13 页

最新陶瓷片 DeepSeek 产物：

```text
1  封面
2  目录
3  版本审阅
4  客户需求
5  检测说明
6  设备选型建议
7  打光示意图-相机1
8  检测说明-相机2
9  检测效果与缺陷样张
10 验证数据与验收指标
11 风险与注意事项
12 设备参数汇总
13 Thanks
```

检测效果页正文限制为 480 字，避免 15pt 字体溢出；验证数据/设备参数使用表格，风险页使用项目符号。

#### D. 参数覆盖率与设备/光路约束

新增：

```text
src/mv_proposal/constraints.py
```

能力：

- 从命中案例中提取：
  - 产品尺寸 / 材质
  - 检测目标 / 精度 / 节拍 / 视场 / 工作距离
  - 相机数量/型号、镜头、光源、控制器、工控机、工位数
- 把约束写入 `TaskPlan.case_constraints`
- WritingAgent 的 LLM Prompt 增加“必须覆盖的关键参数”
- VerificationAgent 新增：
  - `PARAM_MISSING`
  - `PARAM_COVERAGE`
  - `DEVICE_MISMATCH`
  - `OPTICAL_MISMATCH`
  - `SECTION_MISSING`

#### E. 核心设备自动补齐

`RequirementAgent._ensure_core_devices()`：

- 有相机时自动补镜头/光源
- 有镜头或光源时自动补相机
- 避免设备计划缺少核心三件套

### 12.2 最新验证结果

#### Mock 全流程

```text
章节：12
PPT：13 页
参数覆盖率：12/12 = 100%
校验：通过
```

#### DeepSeek 陶瓷片全流程

```text
run_id: 20261017-170220-陶瓷片外轮廓尺寸视觉检测
PPT：13 页
校验：通过
唯一问题：PARAM_COVERAGE info，11/11 = 100%
命中工位图：铨讯 陶瓷片尺寸检测方案 0514 RevB（0.776）
```

产物：

```text
D:\20261012\output\20261017-170220-陶瓷片外轮廓尺寸视觉检测\proposal.pptx
```

#### 回归测试

```text
Ran 71 tests
OK
```

### 12.3 本次新增/修改的关键文件

| 文件 | 变化 |
|---|---|
| `src/mv_proposal/ppt/profile.py` | 模板画像加载 |
| `src/mv_proposal/ppt/planner.py` | 附录页规划 |
| `src/mv_proposal/ppt/appendix.py` | 附录页渲染 |
| `data/templates/visual_proposal_profile.yaml` | 模板页序/形状/样式配置 |
| `src/mv_proposal/constraints.py` | 案例约束提取与覆盖率校验 |
| `src/mv_proposal/ppt_export.py` | 改为 profile + 动态附录 |
| `src/mv_proposal/agents/requirement.py` | 12 章大纲、核心设备补齐、case_constraints |
| `src/mv_proposal/agents/writing.py` | ch9~ch12 模板、约束 Prompt |
| `src/mv_proposal/agents/verification.py` | 参数/设备/光路/章节校验 |
| `src/mv_proposal/agents/assembly.py` | 向 PPT 导出传递 chapters/report |
| `tests/test_dynamic_ppt.py` | 动态 PPT + 约束回归测试 |
| `tests/test_pipeline.py` | 增加 12 章/13 页断言 |

### 12.4 最新未完成事项

以下仍然没有完成：

1. **电池螺丝专用工位图**：库中仍缺，电池螺丝会参考电池外壳图。
2. **检索 reranker / 业务关键词加权**：宽泛查询仍有噪声。
3. **新 station 路径的“直接 sidecar 重画”**：当前历史工位图只作为 LLM 参考，未做高置信直接替换。
4. **早期测试图清理**：`slide5/6/7/11.png` 仍在图库中。
5. **`_tmp_render` 清理**：已完成（原 184 MB）。
6. **前端 E2E 自动化测试**：目前是人工/半自动验证。
7. **多模板 profile 管理**：目前只有一套 `visual_proposal_profile.yaml`。
8. **工位图库版本快照**：尚未做。
9. **`/optic` 与 `/generate` 行为统一**：`/optic` 仍主要走旧 schematic 路径。
10. **Mock 对话自动回填**：Mock 模式仍不会生成 `requirement` 文本。

### 12.5 最新注意事项

1. `ppt_export.export_ppt()` 新增参数：
   ```python
   export_ppt(plan, artifacts, template, out_dir, chapters=chapters, report=report)
   ```
   `AssemblyAgent` 已同步传入；直接调用时也应传入，否则附录页内容会退化。

2. 模板页序/形状名变更时，先改：
   ```text
   data/templates/visual_proposal_profile.yaml
   ```
   不要直接改 `ppt_export.py` 里的索引。

3. `plan.case_constraints` 必须在 WritingAgent 之前设置；当前由 `RequirementAgent._attach_station_layout()` 完成。

4. `PARAM_COVERAGE` 是 info，不会阻断；`PARAM_MISSING` / `DEVICE_MISMATCH` / `OPTICAL_MISMATCH` 是 warning，不会阻断但会出现在校验结果中。

5. 动态章节和附录页会增加生成时间；DeepSeek 陶瓷片全流程约 86 秒。

### 12.6 推荐下一步

1. 用豆包重新跑一次 Prompt 2，**记得把新需求文本一起给豆包**，确认 `new_requirement_compliance` 不再是 null。
2. 对比新 13 页 PPT 与原 12 页 PPT 的结构/完整度分数。
3. 补电池螺丝专用工位图。
4. 做检索 reranker。
5. 测试图和 `_tmp_render` 已清理。
6. 增加 Playwright E2E。
7. 维护多套模板 profile。

---

*本节更新时间：2026-10-17 17:00*

---

## 13. 2026-10-17 17:20 更新：P1/P2 已完成项

### 13.1 数据治理（P1）

#### 工位图库清理

- 早期测试图 `slide5/6/7/11` 已移动到：
  ```text
  data/station_diagrams/_archive_20261017/
  ```
- 当前工位图库：
  ```text
  37 张 PNG + 37 个 JSON
  27 个真实项目
  ```
- `_tmp_render/`（184.2 MB）已清理，当前不存在。

#### 工位图库版本快照

已生成：

```text
data/station_diagrams_versions/station_diagrams_20261017.zip
data/station_diagrams_versions/VERSION_20261017.json
```

快照包含：

- 37 张 PNG
- 37 个 JSON
- VERSION.json

#### sidecar 元数据增强

新增脚本：

```text
scripts/enrich_station_metadata.py
```

每个 sidecar JSON 增加：

```json
"meta": {
  "schema_version": 1,
  "project": "项目名",
  "drawing_type": "图类型",
  "keywords": ["结构化关键词"],
  "source_file": "xxx.png"
}
```

`StationLibrary._scan()` 已把 `meta.project` 和 `meta.keywords` 纳入检索文本。

### 13.2 前端与交互（P1）

- 图库检索增加最低分过滤：
  - 低于 `0.35` 的结果不再展示
  - 界面提示：`检索结果按相似度排序，低于 0.35 已隐藏。`
- 前端版本号更新为 `20261017e`。
- Mock 顾问模式现在会在信息齐全时生成 `requirement` 文本，前端可自动回填。
- 已验证：Mock 对话完整需求返回 `sufficient=true` 且 `requirement` 非空。

### 13.3 运维/调试（P1/P2）

新增：

```text
GET /debug/status
```

返回：

- LLM provider/model
- 工位图数量/项目数
- 工位图库 mtime
- PPT 模板/profile 路径
- `_tmp_render` 是否存在
- 文本知识库集合数量

### 13.4 批量脚本增强（P1）

`scripts/build_station_library.py` 新增：

```powershell
--retry N       # 渲染失败重试次数
--clean-temp    # 每个项目处理完删除临时渲染目录
```

仍然保留 `--skip-existing`。

### 13.5 多模板支持（P2）

配置新增：

```yaml
paths:
  ppt_profile: data/templates/visual_proposal_profile.yaml
```

`Config` 新增 `ppt_profile` 字段；`AssemblyAgent` 已把 profile 路径传给 PPT 导出器。

今后换模板只需要：

1. 新建一份 `xxx_profile.yaml`；
2. 修改 `config.yaml` 的 `paths.ppt_profile`；
3. 不需要改 `ppt_export.py`。

### 13.6 回归测试

```text
Ran 71 tests
OK
```

新增测试：

- `tests/test_dynamic_ppt.py`
- `tests/test_server_endpoints.py`
- `tests/test_advisor.py` 增加 Mock requirement 测试

### 13.7 仍然未完成

1. 电池螺丝专用工位图（仍缺）。
2. 检索 reranker / 业务关键词加权。
3. 新 station 路径的“高置信直接 sidecar 重画”。
4. 多模板的第二套示例 profile。
5. Playwright 浏览器级 E2E（目前用 CUA/接口验证）。
6. `/optic` 与 `/generate` 行为统一。
7. 工位图库增量更新的自动化流程（当前需手动跑脚本+重启）。

---

*本节更新时间：2026-10-17 17:20*

---

## 14. 2026-10-19 更新：描述性设备参数误报修复

### 问题

校验出现误报：

- `相机型号：CST 工业相机，竖直安装`
- `镜头：配套镜头，垂直向下`
- `控制器：用于输出剔除信号`

这些是设备描述，不是型号。

### 修复

`src/mv_proposal/constraints.py` 新增 `_modelish()`：

- 只保留包含“字母 + 数字 + 分隔符”的型号字符串；
- 过滤描述性短语；
- 相机型号、镜头、控制器、工控机均先经过 `_modelish()` 校验。

### 验证

- 新增 `test_descriptive_device_hints_are_not_models`
- 回归测试：61 项通过
- 服务已重启

### 注意

旧产物中的校验结果不会自动更新；需要重新生成方案。

---

*本节更新时间：2026-10-19*

---

## 15. 2026-10-19 更新：光源角度 / 光源工作距离补全

### 问题

- 光路图只标注光源名称；
- 光源倾角未显示；
- 光源到工件距离没有进入结构化 sidecar JSON。

### 修复

1. `VLM_AGENT_PROMPT` 新增 `light_spec_list`：
   ```json
   {
     "name": "光源1",
     "type": "条形",
     "angle": "45°±15°",
     "distance_to_object": "30±10mm",
     "adjustable": false,
     "position": "..."
   }
   ```
2. 新增 `scripts/reextract_station_light_specs.py`：
   - 用新版 VLM Prompt 全量重读已有 37 张工位图；
   - 36 个 sidecar 文件、48 条光源规格；
   - 批量脚本新增 `--force`，可对已提取项目重新做完整 PPTX 扫描；
   - `scripts/enrich_light_specs.py` 保留为规则兜底。
3. `StationLight` 新增：
   - `angle_label`
   - `distance`
4. `station.py` 布局解析支持：
   - `angle_range`
   - `distance`
5. `diagram.py` 渲染：
   - `角度 45°±15°`
   - `距工件 30±10mm`
   - 每个光源按自己的角度旋转图标/照片；
   - 第二光源不再固定水平；
   - 照明光线按倾斜方向重新计算。
6. `RequirementAgent`：
   - 命中工位图时把 `light_spec_list` 写入布局参考；
   - LLM 漏写角度/距离时，用命中案例规格兜底。
7. 修复相机工作距离与光源距离混淆：
   - 优先提取“相机工作距离”；
   - PPT 验证表拆分为“相机工作距离 / 光源到工件距离 / 光源角度”。

### 验证

双光源实测复核：条形光源倾斜并朝向工件，同轴光源保持垂直。

FPC 实测光路图已显示：

```text
角度 45°±15°
距工件 30±10mm
```

工位图库快照：

```text
data/station_diagrams_versions/station_diagrams_20261019.zip
```

回归测试：

```text
Ran 71 tests
OK
```

### 仍未完成

- 仍有 1 个 sidecar 没有可识别的光源规格；
- 部分历史图没有明确标注光源角度/距离，只能保持为空；
- 复杂多光源图的角度归属仍需人工复核；
- 批量脚本已增加 `--force`，可对已提取项目重新做完整 PPTX 扫描。
- 后续可在 VLM 提取后增加人工确认步骤。

---

*本节更新时间：2026-10-19*

---

## 16. 2026-10-19 更新：光源朝向智能判断

### 问题

光源倾斜方向反了，出现“往外撇”；Agent 也没有显式判断每个光源的出光方向。

### 修复

1. `StationLight` 增加 `direction`：
   - `right` / `left` / `down` / `up`
2. `station.py` Prompt 规则：
   - 左侧斜射 → `right`
   - 右侧斜射 → `left`
   - 同轴/环形俯视 → `down`
   - 底部背光 → `up`
3. LLM 漏填时自动推断：
   - 光源在工件左侧 → `right`
   - 光源在工件右侧 → `left`
   - 同轴/环形/圆顶/面光 → `down`
   - 背光且在工件下方 → `up`
4. 渲染器按 `direction` 计算旋转：
   - 左侧光源逆时针倾斜 → 朝右下方
   - 右侧光源顺时针倾斜 → 朝左下方
   - 同轴/环形保持垂直
5. 新增校验：
   - `LIGHT_DIRECTION`：侧光源朝向工件外侧时告警
6. VLM Prompt 增加 `direction` 提取。

### 验证

- 双光源 VLM 复核：
  ```json
  {
    "left_light_points_inward": true,
    "right_light_points_inward": true,
    "both_face_workpiece": true,
    "labels_visible": true
  }
  ```
- 回归测试：71 项通过

### 注意

- `direction` 必须朝工件；渲染器仍会在缺失时按 x 位置兜底。
- 旧产物不会自动更新，需要重新生成。

---

*本节更新时间：2026-10-19*

---

## 17. 2026-10-19 更新：相机 / 同轴光源工作距离对齐

### 问题

文本案例 `Pin线焊锡视觉检测方案` 的相机 WD 是 178±5mm，而工位图命中
`铨讯-锡焊检测方案书-20260616_slide7` 的实际数据是：

- 相机 WD：300±10mm
- 同轴光距离：270mm
- 条形光距离：40mm
- 条形光角度：30-60°

旧逻辑用文本案例覆盖了工位图数据，导致 PPT 表和光路图不一致。

### 修复

1. `VLM_AGENT_PROMPT` 增加 `camera_working_distance`：
   - 只取相机到被测物/平台的标注；
   - 不把光源距离当相机 WD。
2. 重新提取锡焊工位图：
   - `data/station_diagrams/铨讯-锡焊检测方案书-20260616_slide7.json`
   - `camera_working_distance = 300±10mm`
3. 命中工位图时，工位图数据优先覆盖：
   - 相机工作距离
   - FOV
   - 像素精度
   - 相机/镜头/光源描述
4. 当前需求里的产品尺寸优先于历史案例/LLM 误解析。
5. 修复节拍 `1秒/件` 被截成 `1` 的问题。
6. 光路图 WD 标注改为 `相机WD 300±10mm`，中心同轴光源标注移到右侧，避免混淆。

### 验证

最新锡焊生成结果：

```text
相机工作距离：300±10mm
同轴光源距离：270mm
条形光源距离：40mm
条形光源角度：30-60°
```

回归测试：

```text
Ran 71 tests
OK
```

### 注意

- 目前只有锡焊工位图补了 `camera_working_distance`；
- 其它历史图如也需要相机 WD，建议用新版 Prompt 重新跑一遍：
  ```powershell
  D:\minconda\minconda\python.exe -X utf8 scripts\reextract_station_light_specs.py
  ```

---

*本节更新时间：2026-10-19*
