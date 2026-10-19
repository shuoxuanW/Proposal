# 多智能体协同方案书 & PPT 自动生成系统 · 技术文档

> 版本：v1.3 ｜ 更新时间：2026-10-16

## 一、系统概述

面向工业视觉检测项目，接收客户需求，基于私有知识库，自动生成项目方案书、PPT、2D 工位架构图/光路示意图、项目持续规划文档。

| 项 | 内容 |
|---|---|
| 核心能力 | 多智能体协同 + 私有知识库检索增强生成 |
| 技术栈 | DeepSeek(LLM) + BGE(Embedding) + SQLite(向量库) + FastAPI(服务) |

## 二、已完成事项

### 2.1 智能体（Agents）

| 能力 | 说明 | 代码文件 |
|---|---|---|
| 多智能体编排 | 5 个 Agent 流水线：需求解析 → 方案撰写 → 绘图 → 校验 → 汇总 | `src/mv_proposal/pipeline.py` |
| 5 个 Agent | 需求解析 / 方案撰写 / 绘图 / 校验 / 汇总 | `src/mv_proposal/agents/` |
| 结构化传递 | Agent 间通过 Pydantic 模型传递数据 | `src/mv_proposal/models.py` |
| 需求理解 | DeepSeek 一次输出完整结构化 JSON（去硬编码） | `agents/requirement.py` |
| 布局推理 | 模型输出坐标式布局 JSON（相机数量/位置/朝向、光源布置） | `src/mv_proposal/station.py` |
| 方案撰写 | 检索知识库范文/参数，生成 8 章正文 | `agents/writing.py` |
| 绘图 | 模型坐标 + 模板/照片 → 渲染图纸 | `agents/drawing.py` |
| 校验 | 参数一致性、图文匹配、锚点解析 | `agents/verification.py` |
| 汇总输出 | 组装 + 导出 + 联动注册表 | `agents/assembly.py` |
| 图文锚点 | 正文 [[FIG:xx]] ↔ 图纸 ↔ 设备照片 | `src/mv_proposal/anchors.py` + `linkage.py` |
| 能力自检 | 推理失败时输出标注 + 备选模型清单 | `src/mv_proposal/station.py` |
| LLM 接入 | DeepSeek（OpenAI 兼容）+ mock 离线兜底 | `src/mv_proposal/llm.py` |
| 光路参数解析 | 从需求文本提取光路/机位/尺寸 | `src/mv_proposal/optic.py` |
| 设备类型分类 | 按关键词判定设备类型 | `src/mv_proposal/device_classify.py` |

### 2.2 知识库与向量检索（Embedding）

| 能力 | 说明 | 代码文件 |
|---|---|---|
| 文本知识库 | 方案范文 / 图例规范 / 设备参数 3 集合，自动切块 + 向量化 | `src/mv_proposal/knowledge.py` |
| 切块策略 | 按 `##`/`###` 切分，孤立标题行并入下一节，节内碎块归并；块数与章节数一一对应，无空块 / 碎块 | `src/mv_proposal/knowledge.py` |
| 图片库 | 设备示意图，按类型 + 颜色检索 | `src/mv_proposal/image_library.py` |
| 模板库 | 素材预处理：透明底 + 标准尺寸 + 视角/角度元数据 | `scripts/preprocess_templates.py` |
| Embedding | 本地 BGE 中文模型（512 维，离线可用） | `src/mv_proposal/embedding.py` |
| 向量库 | SQLite 持久化，多集合、元数据过滤 | `src/mv_proposal/vectorstore.py` |
| 检索策略 | BGE 向量 + BM25 混合检索（RRF 融合） | `src/mv_proposal/vectorstore.py` |
| 组件装配 | 组装 LLM / Embedding / 向量库 / 知识库 | `src/mv_proposal/context.py` |
| 入库自检 | 投喂后九项校验：切块完整性 / 型号-颜色 / 精度反算 / 索引同步 / 疑似同款型号 / 同型号描述一致性 / 需求-设备适配性 / 光路合理性 / 检索命中率（--hitrate 留一自检） | `scripts/check_kb_consistency.py` |
| 配置加载 | config.yaml + .env + 环境变量 | `src/mv_proposal/config.py` |

### 2.3 交付能力

| 能力 | 说明 | 代码文件 |
|---|---|---|
| 图纸生成 | 工位架构图 / 产品示意图 / 检测俯视图 | `src/mv_proposal/diagram.py` |
| 选型建议 | 模型生成相机/镜头/光源/工控机/控制器建议 | `src/mv_proposal/recommend.py` |
| 方案书导出 | md / html / docx / pdf 四格式 | `src/mv_proposal/document.py` |
| PPT 生成 | 9 页模板填充 + 第4页留白 + 模板残留清理 | `src/mv_proposal/ppt_export.py` |
| 规划文档 | 「已完成 / 待实施」双模块，版本化更新 | `src/mv_proposal/planning.py` |
| 素材回流 | 人工修改图文重新入库 | `src/mv_proposal/feedback.py` |
| 服务化 | FastAPI + Web 前端 + Docker | `src/mv_proposal/server.py` + `web/` |
| 选型流程 | 案例优先召回 → 动态设备组合兜底 + 会议纪要输出格式 | `src/mv_proposal/selection.py` |
| 配套校验 | 相机/镜头/光源/控制器/工控机工程强制配套关系校验 | `src/mv_proposal/compat.py` |
| 入口 | 命令行 / 一键启动服务 | `main.py` + `run_server.py` |

## 三、后续规划

| 优先级 | 事项 |
|---|---|
| P0 | 模板拼图渲染（模型坐标 + 检索模板 + 拼装） |
| P0 | 多轮对话式需求收集 |
| P0 | 模板抄袭残留校验 |
| P1 | 素材精准匹配（型号 > 工位结构 > 光路参数 > 类型） |
| P1 | 图纸评估说明（位置/朝向/命中/图注） |
| P1 | 布局推理 few-shot 增强 |
| P1 | Embedding 升级（bge-large + rerank） |
| P1 | 知识库元数据补全 |
| P2 | 检索效果量化评估 |
| P2 | 自建模型训练（Qwen / GLM 微调） |

## 四、关键技术难点

### 4.1 智能体（Agents）

1. 多 Agent 间状态如何编排与传递，如何保证参数、图注、锚点的一致性？
2. 如何让 LLM 稳定自主推理「相机数量 / 位置 / 朝向、光源布置」，并可靠输出坐标 JSON？
3. 多轮对话如何完成需求收集，槽位填充与缺失字段追问如何设计？
4. 如何保证写作不复制模板原文、不残留旧案例文字，校验机制如何建立？

### 4.2 知识库与向量检索（Embedding）

1. 多模态知识库（文本 + 图片 + 元数据）如何建立与对齐？
2. Embedding 模型如何选型？BGE 是否满足需求，设备示意图「以图搜图」是否需要 CLIP？
3. 白底、视角不一的设备示意图，如何预处理为可拼接模板？
4. 检索精度如何保证？向量 + BM25 + rerank + 元数据过滤的组合如何确定？
5. 知识库持续扩充下，索引如何增量更新、版本化与效果评估？

### 4.3 自动拼图

1. 智能体如何自动将知识库图片拼接为框架图，整体架构如何设计？
2. 模板匹配如何做到「型号 / 视角 / 角度 / 参数」对齐？
3. 图注如何适配当前项目而不沿用旧文案，图文一致性如何保证？