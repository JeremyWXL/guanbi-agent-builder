# 迭代路线图（ROADMAP）

> 本文档是跨 session 的接力棒：记录当前状态、下一步计划与必须守住的设计原则。
> 历史变更看 [CHANGELOG.md](CHANGELOG.md)；评审原文（对照 GitHub 20+ 个 data agent 项目的分析）见 v2.5 当次会话结论，要点已融入本文。
> 最近更新：2026-09-26（v4.2.0）

## 当前状态快照

- **版本**：v4.2.0（卡片取数加速层：parse_page 收割 filtered/dsUsage 分级——数据集级可二次计算、卡片级只作应答缓存；eval_examples 缓存占比统计；sql-guide 取数路径三层；workbench 体检加环境指标。前序：v4.1.1 数据集冷启动 / v4.1.0 看板质量前置闸），独立测试 Agent 在 `tests/agent-tester/`（L0 脚本矩阵 / L1 八步 E2E / L2 交付答题评分，基线 `tests/baselines/` 双写 .md+.json，`diff_baselines.py` 一键版本对比），发布走 `~/.agents/skills/publishing-skills/`
- **架构**：SKILL.md（八步向导 + 全程红线）+ references/scripts（17 个脚本 + 11 个测试文件 146 例单测）+ references/templates（8 个模板）+ references/cognitive-foundation.md + sql-guide.md（含取数路径三层）+ dashboard-knowledge-rationale.md（v4.1–v4.3 设计推演）；CI 在 .github/workflows/ci.yml
- **脚本现状**：`list_pages.py` / `check_pages.py`（适检三档 + agent-ready 评分：口径冲突/权威标注/复用率/粒度覆盖，`--skip-governed` 跳过指标中心）/ `parse_page.py`（raw JSON 主解析+文本回退+哨兵+公式收割+结构指纹+filtered/dsUsage 取数分级）/ `learn_dataset.py`（数据集直学：字段/计算字段/列画像 → datasets-raw.json，_meta.dsFormulas 与 cards-raw 同构）/ `check_formulas.py`（口径字典 + `--seed-metrics` 种子；cards-raw 缺失回退 datasets-raw）/ `check_metrics.py`（口径档案校验闸门）/ `check_dims.py`（维度档案校验闸门 + `--seed-dims` 种子，同样回退 datasets-raw）/ `sample_cards.py`（截断+列画像）/ `validate_cards.py` / `run_sql.py`（只读强制）/ `preflight.py`（前置检查+断点检测，--json 纯 JSON）/ `wizard_state.py`（断点状态机）/ `attribute.py`（归因引擎）/ `eval_examples.py`（回归评测 + 取数路径缓存占比统计）/ `memory.py`（记忆系统：init/log/recall/correct/status/distilled/clear，recall 纠错自动标 ⚠️）/ `workbench.py`（保存回调已抽离为 make_save_file，含 memory/profile.md 特例白名单；核心路径有单测覆盖；整体仍单文件——交付模型约束，勿拆多文件）
- **发布方式**：见 `~/.agents/skills/publishing-skills/`（git push 不通时 `scripts/gh_api_push.py` 精确重放；SkillHub 用 `scripts/stage_skill.py` 构建 staging 后 publish，LICENSE/.gitignore 不入包）

## 设计原则（迭代时不得破坏）

1. **对话对象是不懂技术的业务用户**：禁用术语，每步只问必须决定的事，技术动作静默执行
2. **确认点不可跳过**：第 1、3（若补充）、4、5、7 步必须等用户明确确认；口径确认（第 4 步）是质量命门
3. **每步落盘**：产物立即写工作目录，会话中断可续建
4. **数据红线**：合计不闭环/单位存疑的卡片必须修复或标记禁用；SQL 直查必须走 run_sql.py；SQL 与看板口径差异必须声明
5. **诊断链方法论是核心差异化资产**：归因必须量化、动态下钻、建议绑定对象（开源世界无同类产品，保持领先）
6. **skill 规范**：frontmatter description 只写触发场景（瘦）；版本史只记 CHANGELOG；why-over-MUST
7. **看板是 agent 的持续参照物，不是一次性语料**：挖掘前先过质量闸（v4.1），挖掘后看板降级为漂移检测基准 + 呈现模板库（v4.3），挖掘时语义与结构性元数据都要留，只抽口径等于扔掉一半知识

## v3.0（质量护城河）——✅ 已完成（2026-09-25，v3.0.0）

四项全部落地：examples.json 示例库（模板 + 第 5/7/8 步接线，对齐 Vanna 语料三分法的"示例对"）、eval_examples.py 回归评测（数据层自动核验 + 结论层人工确认状态位）、attribute.py 归因引擎（加法拆解 + 2~4 因子 Shapley 乘法拆解，精确闭环）、wizard_state.py 断点状态机 + preflight 断点检测（第 4/7 命门步禁止 skipped）。详见 CHANGELOG。

## v3.3（交互体验主线）——第一批完成（v3.3.0）

> 来源：2026-09-25 交互体验评审。三层界面（搭建向导/交付助手/工作台）的共识：功能骨架已扎实，差距在"省不省事、迷不迷路"。

- ~~P0 文档同步~~ —— ✅ v3.3.0：agent-SKILL.md 体检段更新为结构指纹版，口径来源接入 metrics.json/check_metrics.py
- ~~P1.1 口径纠错对话闭环~~ —— ✅ v3.3.0：复述确认 → 双写回 metrics.json + businessKnowledge.md → check_metrics.py 校验 → "已记住"
- ~~P1.2 首次对话自我介绍~~、~~P1.3 数据出身行~~、~~P1.4 模糊问题选项式消歧~~、~~P1.5 超范围给出路~~ —— ✅ v3.3.1：agent-SKILL.md 新增「对话体验规范」一节，insightThinking.md 场景一同步
- ~~P2.6 口径确认异议驱动~~ —— ✅ v3.3.0：共识条目分组默认采纳，冲突/存疑项置顶拍板（红线不破）
- ~~P2.7 每步进度播报~~ —— ✅ v3.3.0："第 N 步/共 8 步 · 干什么 · 还要多久"，断点续建同样播报
- ~~P1.6 看板筛选直达链接~~ —— ✅ v3.6.0：实机验证通过（`?cdId=值`，数据层生效，取数 payload 确认 sourceCdId）。筛选器"线上 ID"=cdId 可由 `page get --raw` 直读（与编辑 UI 复制一致）；之前三次失败的根因是拿了不在筛选栏的同名筛选器 ID。规则落地：候选只认 `meta.filterLayout` 成员且 `asFilter.targetCdIds` 非空；FIRST_PICK 默认值筛选器的页面降级告警。parse_page.py 同步收割筛选交互字段（inFilterBar/linkedCardCount/defaultValueType/multiSelect/selectorType）
- ~~P3 工作台指标档案表格视图~~ —— ✅ v3.5.0：业务口径页新增指标档案区块（人话标签 + 表单化编辑 + rejected 折叠展示），端到端验证通过
- ~~P1.7 维度档案与取值消歧~~ —— ✅ v3.7.0：dimensions.json 机器可读维度档案（name/synonyms/values/valueAliases/similarTo）+ check_dims.py 闸门（维度间及与指标的同义词撞车 ❌、值跨维度重叠/相似值 ⚠️）+ `--seed-dims` 种子（卡片行维度/筛选器字段 + 采样列画像枚举值合并）；agent-SKILL.md 新增「维度与取值消歧」三级协议（synonyms 定维度 → values/valueAliases 定取值 → 多命中/查无值选项式消歧）与维度纠正双写回闭环
- ~~P1.8 候选看板带链接~~ —— ✅ v3.7.2：list_pages.py 输出 `url`（BI 地址 + /page/id，取不到地址时省略），SKILL.md 第 1 步候选与已选回显渲染可点击链接，"点名字打开看一眼再勾选"——把选错看板的返工拦在源头
- ~~P3.1 工作台维度档案表格视图~~ —— ✅ v3.8.0（P1.7 遗留项收口）：业务口径页维度档案区块（来源/易混 warn 标签/上卷层级/叫法/成员值预览/值别名 chips + 表单化编辑），概览统计行与多 agent 总览卡片加维度计数
- ~~P2.1 第 1 步确认点核对页~~ —— ✅ v3.8.0：selection_page.py 读取 page-check.json 渲染 selection.html（已选清单 + 适检三档 + 业务范围，看板名带 BI 链接），确认动作仍在对话完成（红线不破），页面只是核对辅助

## v3.x（治理与升级）——✅ 主线全部完成（v3.1.0–v3.2.1）

- ~~资产体检升级~~、~~builderVersion 升级通道~~ —— ✅ v3.1.0：结构指纹双信号 + 具体增删报告 + `--fresh-days` 复核阈值 + `_meta.builderVersion` 升级提示（总览页徽章）
- ~~businessKnowledge 结构化~~ —— ✅ v3.2.0：metrics.json 机器可读口径档案（OSI 对齐）+ check_metrics.py 校验闸门 + `--seed-metrics` 种子生成
- ~~workbench.py 工程化~~ —— ✅ v3.2.1：保持单文件交付形态（约束），保存回调抽离 make_save_file + test_workbench.py 10 例最小单测 + GitHub Actions CI（含版本号一致性检查）

## v4.0（记忆系统）——✅ 已完成（2026-09-25，v4.0.0）

交付包分两个区：`references/` + SKILL.md + workbench.html 为升级可覆盖区，新增 **`memory/` 用户资产区**（profile.md 画像 / qa-log.jsonl 流水 / corrections.json 纠错台账 / _meta.json schema+蒸馏计数）——升级通道只替换脚本、重生成工作台、更新 builderVersion，memory/ 永不覆盖（SKILL.md 第 8 步升级通道 + 交付助手维护节双写明示）。`memory.py` 七个子命令（init 幂等/log 兜底初始化/recall 相似检索+纠错后旧问答自动标 ⚠️/correct/status 蒸馏阈值 20/distilled/clear 先备份再清空）；交付助手模板新增「记忆系统」节（写入/读取/蒸馏/边界四纪律，纠错双闭环各加台账步，执行流程第 0 步接入 recall）；工作台新增「记忆」页（画像可编辑走 make_save_file 特例白名单、流水与台账 append-only 禁写、概览加记忆计数）。与 examples.json 的边界钉死：qa-log 是私人流水非回归基准，验收过的回答才"提拔"进示例库。test_memory.py 17 例 + workbench 侧 5 例，单测 82 → 103 例；agent-tester v1.2.0（L0-18 + L1 第 8 步 memory 完整性）。详见 CHANGELOG。

## v3.9（工程质量补齐）——✅ 已完成（2026-09-25，v3.9.0）

"算错就是事故"的脚本全部入回归：attribute.py（18 例：数值解析/加法闭环与方向约定/Shapley 闭环·对称·零起步）、eval_examples.py（17 例：货币符号/容差/退出码/交付包回退）、make_link.py（12 例：候选规则/FIRST_PICK 保守告警/链接生成与拒绝路径）、preflight.py（5 例）；preflight `--json` 修复为纯 JSON 输出（坑清单挂账项清零）；基线双写 .md+.json + `diff_baselines.py` 一键版本对比（agent-tester v1.1.0）。单测 24 → 82 例，CI discover 自动收编。workbench.py 模板外置项评估后放弃：单文件是交付硬约束，外置会给已交付包引入"模板缺失即打不开"的新故障面，收益只是观感。详见 CHANGELOG。

## v4.1（看板质量前置闸）——✅ 全部完成（P0+P1 于 v4.1.0，P2 于 v4.1.1）

> 来源：2026-09-26 迭代方向讨论（推演原文见 [references/dashboard-knowledge-rationale.md](references/dashboard-knowledge-rationale.md) 第一节）。核心判断：质量差的看板不是"差一点的知识源"，而是**信噪比为负**的知识源——会把错误口径显性化进 agent，比冷启动更难修。因此口径治理是挖掘流水线的**前置工序**，不是可选项。

- ~~P0 看板 agent-ready 评分~~ —— ✅ v4.1.0：口径一致性 40 + 权威标注率 25（metric by-dataset 查指标中心，--skip-governed 可省，查不到权重重分摊）+ 数据集复用率 20 + 粒度覆盖度 15；≥75 高 / 45–74 中 / <45 低；第 1 步适检报告与 selection.html 核对页同步展示。实机首跑抓出演示看板有毒口径（硬编码常量当"同比"、rand() 凑"客户数"）
- ~~P1 口径冲突分级~~ —— ✅ v4.1.0：🔴 红线（口径混乱，有毒，必须先治理，有冲突评分封顶「中」）与 🔷 边界（覆盖不足，只压上限，只做能力边界标注）分开输出与处置
- ~~P2 数据集冷启动路径~~ —— ✅ v4.1.1：`learn_dataset.py`（ds get 字段/计算字段 + preview 列画像 → datasets-raw.json，_meta.dsFormulas 与 cards-raw 同构）+ check_formulas/check_dims 自动回退；第 1 步直通分支（知情同意前置）；交付模板「数据探索型」变体——能力边界写进自我介绍（能答"数据里有什么"，答不了"业务上该看什么"）

## v4.2（卡片取数加速层）——✅ 已完成（2026-09-26，v4.2.0）

> 来源：同上讨论（推演原文第三节）。卡片对 agent 的价值定位：**物化视图 + 权限边界 + 应答缓存**，不是分析逻辑本身。它能吃掉日常查询负载的大部分取数成本，但对能力上限无贡献。

- ~~P0 数据集级 / 卡片级分离~~ —— ✅ v4.2.0：parse_page.py 收割每卡 `filtered` 标记 + 每页 `dsUsage` 分级；**数据集级**（未筛选）开放二次计算，**卡片级**（带筛选）只作应答缓存、禁止二次加工（粒度陷阱）；纪律进交付模板取数流程与数据红线
- ~~P1 高频问题应答缓存~~ —— ✅ v4.2.0：eval_examples.py 报告新增取数路径统计（卡片缓存/SQL 直查条数与缓存占比，--json 输出 fetchMix）
- ~~P2 取数路径分层写进 sql-guide~~ —— ✅ v4.2.0：卡片缓存 → 数据集级 → 明细层三层选择规则与降级条件 + 粒度陷阱红线
- ~~P2 agent-ready 环境指标~~ —— ✅ v4.2.0：workbench --check 体检报告新增「取数加速层」（数据集复用率 + 数据集级/卡片级张数，纯本地计算；旧档案分级降级提示）；粒度覆盖度依赖 dsInfos 全量字段清单、学习时点才有，体检不重复计算（以 page-check.json 的 v4.1 评分为准）

## v4.3（看板角色迁移）——规划中

> 来源：同上讨论（推演原文第二节）。知识抽象出来后看板不消失，角色迁移为：agent 的**训练语料 + 漂移检测基准 + 呈现模板库**。失去价值的只是"看板作为人与数据唯一界面"这一定位。

- **P0 口径漂移检测**：结构指纹（v3.1.0）只管"结构变了没有"，扩展到"口径漂了没有"——agent 回答与看板读数定期对账（复用 --fresh-days 复核阈值），把看板当**回归测试集**用，漂移即告警进纠错闭环
- **P1 呈现模板库**：挖掘时不止抽语义（口径/路径），还要保留**结构性元数据**——图表类型、布局、联动关系（parse_page.py 已部分收割），作为 agent 生成图表产出时的选型模板，写进交付包的产出侧资产
- **P2 分析路径显性化**：从卡片联动/下钻配置中抽取"先看总量→再看结构→下钻异常"的分析路径，补 examples.json 目前只有问答对、没有多轮路径的缺口

## v5.0（跨 agent 组合）——远期设想

多 agent 总览页已有，往前一步是组合问答：
- 路由层：读各成员 agent 的 learningResult/metrics.json 做问题分发（"这个问 BU agent，那个问集团 agent"），总览页升级为组合入口
- 开放问题（设计时再解）：成员 agent 上下文隔离（各用自己的口径档案取数）、跨 agent 口径冲突仲裁（同名指标两边公式不同时必须声明差异，沿用"禁止 AI 自行二选一"原则）、组合报告的对象绑定

## 生态侧（随时可做）

- ~~CI~~ —— ✅ 已随 v3.2.1 上线（py_compile + 单测 + frontmatter lint + 版本一致性）
- **英文版 README**："BI dashboard → 受治理对话式 agent 搭建向导"在英文社区无同类，是发声点
- **agentskills #436**：跟进"上游来源声明"提案，本项目的 `_meta` 体检机制是超前实现，可作案例
- **趋势锚点**：Vanna 已归档、纯 RAG text-to-SQL 路线正被"受治理语义层+agent"（WrenAI/SuperSonic/Cube）取代——本项目的"口径确认产物作为查询唯一入口"定位踩在新路线上，继续强化，勿退回自由 SQL

## 已踩过的坑（迭代时避开）

- 文本正则解析 CLI 输出是最大脆弱源：v2.4 文本路径 51 卡静默丢 28（位置标记白名单过窄 + 空命名卡片）；一切解析优先走 `--raw` JSON，文本只做回退
- `_meta` 键曾导致 sample_cards.py KeyError：遍历 cards-raw.json 必须跳过 `_` 前缀键
- LLM 自由 SQL 无硬约束是事故温床：任何新取数能力都要脚本层强制（参照 run_sql.py）
- 大卡片全量采样会撑爆上下文：sample_cards.py 的 200 行截断 + profile 是底线，勿回退
- eval_examples.py 的 fetch.file 相对 examples.json 所在目录解析，与 sample_cards.py 的扁平命名 `card-data/<看板名>__<卡片名>.json` 对齐；examples.json 在工作目录根缺失时自动回退 `references/examples.json`（交付包形态），交付包内回归直接 `python3 references/eval_examples.py .`（包根目录），run_sql.py 定位优先 `<工作目录>/references/scripts/`、回退同目录
- parse_page.py 必须单次调用传入全部 pageId（逐张循环会覆盖 cards-raw.json 静默丢看板，v3.7.0 沙箱实测踩中，SKILL.md 已改为明示）
- SQL 直查探查结论会过期：数据集学习时可用不代表验收时可用（演示域文件型数据集实测中途失效）；第 7 步必须先探活再测，失效降级卡片间交叉验证，交付能力标注以第 7 步实测为准
