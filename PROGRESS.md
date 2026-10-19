# 项目进度（跨对话锚点 · 每轮先读此文件）

> 更新时间：2026-10-16。此文件是「全局待办+进度」的唯一权威来源，对话记忆不可靠。

## 一、已完成

- 5 Agent 流水线：需求解析 → 方案撰写 → 绘图 → 校验 → 汇总（方案书/PPT/图纸/规划文档）
- MD 知识库（案例层+设备层）：方案范文 29 份、设备参数 29 份、图例 1 份（data/knowledge/）
- 入库自检工具：scripts/check_kb_consistency.py（A–J 九项 + --hitrate 命中率留一自检）
- 设备配套表：data/device_catalog.json + 配套校验 src/mv_proposal/compat.py（卡口/接口/通道/分辨率/线缆）
- 选型流程：src/mv_proposal/selection.py（案例优先召回 → 动态设备组合兜底 + 会议纪要输出格式）
- 售前顾问：src/mv_proposal/advisor.py（渐进式问诊 + 信息齐后回填需求框）+ server.py /chat 接口 + web 对话面板
- 产品目录知识库：src/mv_proposal/catalog.py（独立向量集合 catalog）

## 二、产品目录知识库规模（data/catalog/products.json）

- 2D：camera 165 / linescan 19 / infrared 12 / lens 93 / framegrabber 9 / cable 59
- 3D：sensor3d 69 / stereo 17 / perception 19 / logistics 1
- 行业产品：industry 70（2.5D 系统）/ context 10（应用案例）
- 系列：20 个（定位/适用场景 → 关联型号+参数，双向关联）
- 共 563 条（含 20 系列）

## 三、重建脚本（PDF 已固定存放在 data/catalog/）

- scripts/build_catalog.py     # 2D 手册（相机/镜头/线缆/采集卡/红外）
- scripts/build_catalog_3d.py  # 3D 手册（轮廓/结构光/立体/感知/物流）
- scripts/build_context.py     # 行业产品 + 应用案例（依赖先 dump 2D 文本）
- scripts/import_catalog.py    # 相机参数按 9 字段批量入库

## 四、待办（按优先级）

- [P0] 两库串联：选型时 案例层(MD)召回 → 设备目录兜底 + 配套校验（selection.py 已就绪，需接入 advisor/select）
- [P0] 检索质量：BM25 权重低，英文/数字型查询排序差；需带标注评测集校准阈值
- [P1] DLS/DPS/DB/DT 用 pdfplumber table 模式补准（当前部分字段因表格拆行丢失）
- [P1] 设备目录补海康官方资料（线缆/采集卡/接口/卡口）
- [P0·原PLAN] 模板拼图渲染 / 多轮对话需求收集 / 模板抄袭残留校验

## 五、铁律（不可违背，详见 PLAN.md）

1 模型不调图 2 严禁套固定模板 3 去硬编码 4 PPT第4页产品图留白
5 禁复制模板原文/残留旧案例 6 能力自检+备选模型清单 7 智能体自己推理
