# CHANGELOG

> 本文件只做“按时间顺序的更新索引”。  
> 最新、最完整的交接状态请读：`AGENT_HANDOFF_20261017.md`。  
> 阶段性完成事项汇总：`完成事项总结_20261017.md`。

---

## 2026-10-19

### 相机 / 同轴光源工作距离对齐

**问题**

- 文本案例召回到了 `Pin线焊锡视觉检测方案`（相机 WD 178±5mm）；
- 工位图命中的是 `铨讯-锡焊检测方案书-20260616_slide7`（相机 WD 300±10mm、同轴光 270mm、条形光 40mm）；
- 旧逻辑让文本案例的 178±5 覆盖了工位图数据，导致 PPT 表和光路图不一致。

**修复**

- VLM 增加 `camera_working_distance` 字段，并重新读取锡焊工位图，得到 300±10mm。
- 命中工位图时，以下数据以工位图为准：
  - 相机工作距离
  - 视场 FOV
  - 像素精度
  - 相机/镜头/光源描述
- 需求文本里的产品尺寸优先于历史案例/LLM 误解析。
- 修复生产节拍“1秒/件”被截成“1”的问题。
- 光路图中的 WD 标注改为 `相机WD 300±10mm`，同轴光源标注移到右侧，避免和相机 WD 混淆。

**验证**

- PPT 验证表：
  - 相机工作距离：300±10mm
  - 光源到工件距离：40mm / 270mm
  - 光源角度：30-60°
- 光路图：
  - `相机WD 300±10mm`
  - 同轴光 270mm
  - 条形光 40mm
- 回归测试：71 项通过

---

### 光源朝向智能判断 + 倾斜方向修正

**问题**

- 光源图标倾斜方向反了，出现“往外撇”；
- Agent 没有显式判断光源该朝左、朝右还是朝下。

**修复**

- `StationLight` 增加 `direction` 字段：
  - `right`：向工件右侧出光
  - `left`：向工件左侧出光
  - `down`：垂直向下
  - `up`：从下往上（背光）
- `station.py` Prompt 增加方向规则：
  - 左侧斜射 → `right`
  - 右侧斜射 → `left`
  - 同轴/环形俯视 → `down`
  - 底部背光 → `up`
- LLM 漏填方向时，按光源 x 位置和光源类型自动推断。
- 渲染器改为按 `direction` 计算旋转角：
  - 左侧光源逆时针倾斜，朝右下方
  - 右侧光源顺时针倾斜，朝左下方
  - 同轴/环形保持垂直
- 新增校验 `LIGHT_DIRECTION`：侧光源朝向工件外侧时告警。
- VLM Prompt 增加 `direction` 提取。
- 双光源 VLM 复核：左右光源均向内倾斜并朝向工件。

**验证**

- 回归测试：71 项通过

---

### 光源角度 / 光源工作距离补全

**问题**

- 光路图只显示光源名称，不显示光源倾角；
- 光源到工件的距离没有进入结构化知识库，也没有在图中显示。

**修复**

- `VLM_AGENT_PROMPT` 增加 `light_spec_list` 提取：
  - 光源类型
  - 角度/角度范围
  - 光源到工件距离
  - 是否可调
- 新增 `scripts/reextract_station_light_specs.py`，用新版 VLM Prompt 全量重读 37 张工位图：
  - 36 个文件、48 条光源规格
  - 批量脚本新增 `--force`，支持完整 PPTX 重扫
  - `scripts/enrich_light_specs.py` 保留为规则兜底
  - 示例：FPC `45°±15° / 30±10mm`、电池外壳 `65±5° / 70±10mm`、锡焊 `30-90° 可调`
- `StationLight` 增加：
  - `angle_label`
  - `distance`
- 布局 Prompt 增加 `angle_range` / `distance` 字段
- 渲染器显示：
  - `角度 45°±15°`
  - `距工件 30±10mm`
  - 光源图标/照片按各自角度倾斜，第二光源不再水平摆放
  - 照明光线按倾斜方向重新计算
- 命中案例光源规格缺失时，自动回填到 LLM 光路布局
- 修复“相机工作距离”被误写成“光源到物料距离”的问题

**验证**

- FPC 实测图已显示：
  ```text
  角度 45°±15°
  距工件 30±10mm
  ```
- 双光源 VLM 复核：条形光源倾斜且朝向工件，同轴光源保持垂直
- 实际锡焊双光源图 VLM 复核：两根条形光源均倾斜朝向工件，同轴光源保持垂直
- 修复 `OPTICAL_MISMATCH` 对泛化 light_type 的误报
- 回归测试：71 项通过

---

### 修复描述性设备参数误报

**问题**

校验结果出现误报：

```text
PARAM_MISSING：相机型号未覆盖：CST 工业相机，竖直安装
PARAM_MISSING：镜头未覆盖：配套镜头，垂直向下
PARAM_MISSING：控制器未覆盖：用于输出剔除信号
```

这些是设备描述，不是真实型号。

**修复**

- `src/mv_proposal/constraints.py` 增加 `_modelish()`：
  - 只接受包含字母+数字+分隔符的型号字符串
  - 过滤“CST 工业相机，竖直安装”“配套镜头，垂直向下”“用于输出剔除信号”等描述
- 案例约束提取不再把这些描述当成相机型号/镜头/控制器。
- 新增回归测试：`test_descriptive_device_hints_are_not_models`。
- 回归测试：61 项通过。

**需要做的操作**

重启服务并重新生成方案，旧产物中的校验结果不会自动更新。

---

## 2026-10-17

### 17:20 — P1/P2 治理与工程化

**数据治理**

- 早期测试图 `slide5/6/7/11` 归档到 `data/station_diagrams/_archive_20261017/`
- 工位图库：41 张 → 37 张（27 个真实项目）
- `_tmp_render/` 清理（原约 184 MB）
- 生成工位图库快照：
  - `data/station_diagrams_versions/station_diagrams_20261017.zip`
  - `data/station_diagrams_versions/VERSION_20261017.json`

**检索与元数据**

- 新增 `scripts/enrich_station_metadata.py`
- sidecar JSON 增加 `meta.project / meta.keywords / meta.drawing_type / meta.source_file`
- `StationLibrary` 检索文本纳入结构化关键词
- 前端图库检索增加 `≥0.35` 过滤与提示

**交互与接口**

- Mock 顾问模式信息齐全时生成 `requirement`，可自动回填
- 新增 `GET /debug/status`
- 新增 `tests/test_server_endpoints.py`

**工程化**

- `build_station_library.py` 增加 `--retry`、`--clean-temp`
- 配置新增 `paths.ppt_profile`，支持多模板 profile
- 回归测试：60 项通过

---

### 17:00 — 动态 PPT + 参数校验（P0）

**动态 PPT**

- 新增 `src/mv_proposal/ppt/`：
  - `profile.py`
  - `planner.py`
  - `appendix.py`
- 新增 `data/templates/visual_proposal_profile.yaml`
- 基础页页序/形状名/样式从 YAML 读取
- 动态附录页：检测效果、验证数据、风险、设备参数
- PPT：8 页 → 13 页

**动态章节**

- 8 章 → 12 章
- 新增：
  - 检测效果与缺陷样张
  - 验证数据与验收指标
  - 风险与注意事项
  - 设备参数汇总

**参数校验**

- 新增 `src/mv_proposal/constraints.py`
- `TaskPlan.case_constraints`
- 新增校验：
  - `PARAM_MISSING`
  - `PARAM_COVERAGE`
  - `DEVICE_MISMATCH`
  - `OPTICAL_MISMATCH`
  - `SECTION_MISSING`
- 核心设备自动补齐（相机/镜头/光源）
- DeepSeek 陶瓷片实测：13 页、参数覆盖率 11/11=100%

**测试**

- 新增 `tests/test_dynamic_ppt.py`
- 回归测试：54 项通过

---

### 16:00 — 工位图库全量提取与检索

- 扫描 48 个 pptx，按文件名去重 47 个
- 本次新提取 32 张工位图
- 工位图库达到 41 张（后续清理测试图为 37 张）
- 覆盖 27 个真实项目
- 提取部件 194 个，sidecar JSON 0 损坏
- 修复批量脚本对 `~$` Office 临时文件的处理
- 工位图检索元数据增强（项目名、完整 note、部件位置）

---

### 13:30 — 案例召回与前端展示

- 案例召回接入 PPT 生成主流程
- 命中案例注入需求解析、工位布局、正文撰写
- `manifest.json` / `/generate` 返回 `matched_cases`
- 同一方案多块召回去重
- 修复 `/generate` 忽略 `llm=mock` 的问题
- 前端显示“基于历史案例”
- 前端显示“参考历史工位图”
- 新增历史工位图库浏览/检索面板

---

### 更早（2026-10-12 ~ 10-16）

- 原有项目进度见：`PROGRESS.md`
- 原有计划见：`PLAN.md`

---

*最后更新：2026-10-17*
