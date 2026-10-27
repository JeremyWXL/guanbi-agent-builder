# 迭代路线图（ROADMAP）

> 本文档是跨 session 的接力棒：记录当前状态、下一步计划与必须守住的设计原则。
> 历史变更看 [CHANGELOG.md](CHANGELOG.md)；评审原文（对照 GitHub 20+ 个 data agent 项目的分析）见 v2.5 当次会话结论，要点已融入本文。
> 最近更新：2026-10-23（v4.12.1 修复 v4.10–v4.12 一致性/健壮性问题：预算不能绕过 R-01、骨架多数据集别名与多行公式、cardReuse 命令校验、audit 确认门跑 --check；前序 v4.12.0 卡片级复用 / v4.11.0 分析思路写作指引 / v4.10.0 看板就绪诊断）

## 当前状态快照

- **版本**：v4.12.1（v4.12.1 修复 v4.10–v4.12 一致性/健壮性：预算不能绕过 R-01、骨架多数据集别名/多行公式/残留清理、cardReuse 命令校验、audit 确认门跑 --check；v4.12.0 新增洞察Agent 看板重建的卡片级复用；前序 v4.11.0 分析思路写作指引 / v4.10.0 看板就绪诊断 / v4.9.3 P2 积压清零 / v4.9.2 回归 P1 修复 / v4.9.1 文档与测试基建 / v4.9.0 全局参数 DYNAMIC_PARAMS 全链路 / v4.8.x 指标中心轻量集成 / v4.7.x 交付工程化 / v4.6.0 问题反馈通道 / v4.5.0 范围守卫 / v4.4.0 增量学习通道 / v4.3.0 快速模式），独立测试 Agent 在 `tests/agent-tester/`（v1.9.3；L0 脚本矩阵 32 检查点 / L1 八步 E2E + L1-lite 五步 + L1-incr 五步 + L1-audit 四步 / L2 交付答题评分），基线 `tests/baselines/` 双写 .md+.json（最新归档 v4.12.1：full/lite/incr/audit 全矩阵回归，L2 100/A 零红线），`diff_baselines.py` 一键版本对比，发布走 `~/.agents/skills/publishing-skills/`
- **架构**：SKILL.md（八步向导 + 快速/增量双通道 + 洞察Agent 诊断四步 + 全程红线 20 条）+ references/scripts（31 个脚本 + 30 个测试文件 545 例单测）+ references/templates（11 个模板）+ references/insight-agent-readiness.md（v4.10 规则/评分/五模式）+ references/insight-agent-thinking-guide.md（v4.11 分析思路写作）+ references/insight-agent-card-reuse.md（v4.12 卡片级复用/重建）+ references/cognitive-foundation.md + sql-guide.md + dashboard-knowledge-rationale.md（v4.1–v4.3 设计推演）+ metric-center-integration.md（v4.8 方案全文）；CI 在 .github/workflows/ci.yml（py_compile + 单测 + frontmatter lint + 十处版本一致性）
- **脚本现状**：`list_pages.py`（看板扫描+BI 链接）/ `check_pages.py`（适检三档 + agent-ready 评分，governed 指标中心映射随 page-check.json 落盘）/ `selection_page.py`（第 1 步核对页）/ `parse_page.py`（raw JSON 主解析+文本回退+哨兵+公式收割+结构指纹+filtered/dsUsage 取数分级+dynamicParams 参数收割）/ `learn_dataset.py`（数据集直学，_meta.dsFormulas 与 cards-raw 同构）/ `check_formulas.py`（口径字典 + `--seed-metrics`，PARAM_DEPENDENT 最高优先分类；回退链 cards-merged→cards-raw→datasets-raw→cards.json）/ `check_metrics.py` / `check_dims.py`（双闸门 + 双种子）/ `fill_dim_values.py`（维度枚举机械回填，`--full` 全量）/ `sample_cards.py`（截断+列画像+`--scope` 白名单+`--only-cdIds`/`--prune-keys` 定向刷新）/ `validate_cards.py` / `run_sql.py`（只读强制 + dsId 白名单 + `--check-scope`）/ `run_metric.py`（指标中心直查，governedRef 白名单）/ `preflight.py`（前置检查+断点检测，--json 纯 JSON）/ `wizard_state.py`（状态机 + full/lite/incr/audit 四模式 + confirm 产物门，含 audit 第 2/3/4 步）/ `attribute.py`（归因引擎）/ `eval_examples.py`（回归评测 + `--suggest/--record/--confirm` 验收回填）/ `memory.py`（记忆系统 7 子命令）/ `workbench.py`（校验工作台+体检+多 agent 总览，单文件是交付硬约束勿拆）/ `make_link.py`（筛选直达链接）/ `merge_cards.py`（增量合并 + cardHash diff）/ `scope.py` + `scope_audit.py`（范围守卫白名单 + 事后审计）/ `feedback.py`（问题反馈 GitHub/SkillHub 双通道）/ `audit_insight_pages.py`（洞察Agent 看板机械体检：六维评分 + 跨页重叠/共享维度/口径冲突/层级 + `--seed-advice`）/ `insight_audit_report.py`（建议校验 + Markdown/HTML 报告，`--draft/--check`）/ `extract_card_skeletons.py`（按 cdId 从 cards-raw 抽 createCard 骨架 + 核对清单）/ `build_package.py` + `render_agent_skill.py` + `check_package.py`（交付机械组装 + 模板渲染 + 三层体检总闸门）
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

## v4.3（快速模式）——✅ 已完成（2026-09-26，v4.3.0）

> 来源：2026-09-26 轻量化讨论。用户明确的约束：快速模式**从看板开始**（数据集直通缺业务信息太多，不作 lite 默认路径，保留为原触发条件下的兜底）；看板粗糙时尽提醒义务，用户坚持可继续。

- **双轨道不分叉**：向导开头模式选择（快速 ≈15 分钟 / 完整 40-60 分钟）；`wizard_state.py init --mode lite` 落盘 mode 字段，断点续建按 mode 恢复行为；lite 五步地图（选数据 → 看板学习 → 口径裁决 → 场景与框架 → 验收与交付），状态机仍按八步记录
- **砍确认深度，不砍产物结构**：L1/L2 与完整版全量一致（适检+评分+双种子照常）；L3 只保留冲突逐条拍板 + ≤3 条高风险疑似问题 + 一句话归因问法，共识组默认采纳，metrics/dimensions 以种子自动成稿、双闸门 ❌ 清零不破；L4/L5 合并 5+6、7+8，交付包结构同构（含 memory/）。三条不破底线：提醒义务 / 冲突裁决 / 验收实测
- **深化通道（lite → 完整）**：无新机制——preflight/next 识别 lite 已交付即提示，回完整版第 4 步以已有档案为底稿逐条补确认 + 第 7 步扩题库；businessKnowledge.md 标注从"快速模式成稿"改为"已逐条确认"
- **顺手修正**：wizard_state.py BUILDER_VERSION 3.0.0 → 4.3.0（与 frontmatter 同步的注释已漂移两个大版本）
- **测试**：新建 test_wizard_state.py 7 例（mode 落盘/lite 下第 3 步可 skipped、第 4/7 步仍拒绝/旧档案无 mode 兼容/lite 完成提示深化）；单测 146 → 153 例；agent-tester 升 v1.5.0（L0-2 补 --mode lite、新增 L1-lite 五步 E2E 检查点表含深化通道实测）；**E2E 沙箱实测通过**（低分看板提醒义务+坚持继续、双闸门首轮 10❌ 拦截后零❌、交付包同构包内回归 3/3、深化通道 memory/ md5 未变；实抓隐藏筛选+DYNAMIC_PARAMS 双重陷阱，基线 v4.3.0 归档）

## v4.4（增量学习通道）——✅ 已完成（2026-09-27，v4.4.0）

交付模板三处承诺的增量学习落地：`wizard_state.py init --mode incr`（独立状态文件 wizard-state-incr.json，不覆盖搭建档案）+ merge_cards.py（cardHash 结构指纹比对，**未变页零重学零重采样**，变更页报告具体增删/改名）+ sample_cards 定向刷新（`--only-cdIds` / `--prune-keys`）+ 五步地图 I1 增量选看板 → I2 增量学习 → I3 增量口径裁决 → I4 增量验收 → I5 交付更新。三条命门：新冲突逐条裁决禁止 AI 二选一、双闸门 ❌ 清零、验收实测（旧示例全量回归 + 新能力 ≥1 题）；memory/ 永不在覆盖范围。详见 CHANGELOG。

## v4.5（范围守卫）——✅ 已完成（2026-09-27，v4.5.0）

覆盖外看板/数据集禁止当答案：scope.py 白名单单一事实源（从 cards.json/datasets.json 派生，增量合并后自动扩容，永不手工维护）+ run_sql dsId 白名单（越界 exit 3 且不调 guancli）+ sample_cards `--scope` 越界整批拒绝 + memory log `--page/--ds` 结构化出处 + scope_audit.py 事后审计。红线 14。已知边界：agent 有 Bash 理论上能绕过一切脚本——目标是"合规路径成为唯一阻力小的路径 + 事后可审计"。详见 CHANGELOG。

## v4.6（问题反馈通道）——✅ 已完成（2026-09-28，v4.6.0）

feedback.py 双通道（GitHub issue / SkillHub 评论 ≤500 字硬校验）：用户遇 bug 经**明确同意**后一键反馈，只带环境信息（版本/搭建进度/平台/guancli 有无）绝不带业务数据；builder 与交付助手双侧接线，红线 15。上线后即立功：v4.8.3 的工作台渲染修复（issue #4）就是经此通道实机上报的。详见 CHANGELOG。

## v4.7（交付工程化）——✅ 已完成（2026-09-28/29，v4.7.0–v4.7.1）

把"靠 prompt 约束模型自觉"的剩余环节全部下沉为脚本硬控制（correct by construction）：build_package.py 机械组装（**cards.json 由 cards-raw.json 整体复制派生，禁止裁剪**——裁剪 = run_sql/make_link/sample_cards 连锁瘫痪）+ render_agent_skill.py 模板渲染（CLI 用法单一事实源是脚本源码，test_template_cli 守护）+ check_package.py 三层体检总闸门（结构/内容/功能冒烟）+ eval_examples `--record/--confirm` 验收回填（过不了取数源校验的数字进不了基准）+ wizard_state confirm 产物门（第 7/8 步验产物不看口头申报）+ fill_dim_values.py 维度枚举机械回填。v4.7.1 资产完整性哨兵：同名冲突 exit 2 / 部分失败默认拦截（`--allow-partial` 显式放行）/ `--force` 清理受控区 / 采样键加 cdId 防碰撞 / 路径越界拒绝。红线 16。详见 CHANGELOG。

## v4.8（指标中心轻量集成）——✅ 已完成（2026-09-29 起，v4.8.0–v4.8.5）

> 方案全文见 [references/metric-center-integration.md](references/metric-center-integration.md)（2026-09-29）。核心判断：指标中心是观远的语义层，metrics.json 是 agent 侧口径档案——两者对齐顺着"受治理语义层 + agent"路线走。v4.1 的权威标注率评分已埋下只读通道，本版本把它升级为口径引用。

- **定位**：轻量集成，不是指标建设项目。只做三件事——已发布同口径指标**直接引用**（metrics.json 加 governedRef，取数走新脚本 run_metric.py 平台直查，排在三层取数路径之前）；缺失的原子指标**顺手创建**（≤10 条走 guanmetric，创建权限不预检、以首次写入实机结果为准）；无权限/未开通的用户**一次性推荐 + 帮助文档链接**后不再打扰
- **三态探针**：可用（A）/ 未开通或无权限（B）/ 临时失败（C），初判复用 check_pages 的 governed 结果，结论落盘防断点续建重复打扰
- **防变重边界**：指标体系建设、批量迁移归并、复合/派生批量梳理一律路由专项 skill（guandata-metric-migration，持续迭代中）；红线拟加第 17 条（指标中心三条）
- **开放问题**：未开通/无权限的错误形态需实机确认；guanmetric 预检放 preflight 还是首用时提示（倾向后者）；口径一致性核对宁标待确认不硬判
- **后续小版本**（v4.8.1–v4.8.5，均已完成）：v4.8.0 回归修复（旧包冒烟版本降级 / 直通模式模板渲染条件块 / fill_dim_values `--full` 全量枚举回填）；v4.8.2 行数上限纪律（红线 18：先提醒缩小范围或聚合、明细分批须告知成本、截断禁止当全量）；v4.8.3 工作台 cards 数组形态渲染修复（issue #4，feedback 通道首个实机上报）；v4.8.4 数据出身行升级（回答必须带数据范围与口径随数声明）；v4.8.5 首次开场白（欢迎 + 为什么搭建 + 会发生什么三要素）

## v4.9（全局参数 DYNAMIC_PARAMS 全链路）——✅ 已完成（2026-10-19，v4.9.0）

观远看板大量用全局参数做动态筛选与指标切换，此前零感知——参数化公式被 SQL 内联必报错或静默算错，agent 取数只能拿参数默认值。本版本全链路支持：parse_page/learn_dataset 收割 `dynamicParams`（dpId/名称/类型/默认值，跨层去重）带入 cards.json；check_formulas 新增 PARAM_DEPENDENT 最高优先分类（含参公式禁止 SQL 内联，走 `card preview --dynamic-param` 传参取数）；红线 10 与 sql-guide 同步；交付模板加参数化卡片取数纪律（只传声明过的参数/回显不等于生效/空结果先怀疑默认参数范围）与出身行参数声明。实机验证：mxbc 页面识别参数化卡 22/34、v370 沙箱 3 个参数化指标正确归类。详见 CHANGELOG。

## v4.10（洞察Agent 看板就绪诊断）——✅ 已完成（2026-10-22，v4.10.0）

用户拿 1–N 张现有看板问"适不适合观远洞察Agent、该怎么整合/改造"时，之前没有入口。本版本新增 audit 通道（与八步向导并列），把官方硬要求与项目方法论变成可执行诊断：

- **规则**：R-01…R-06（≤10 页 / 每页联动筛选器 / 8.1+ 与环境 / 业务范围 / 口径固化 / 上下文可控）+ R-07…R-16（一页一问题 / 指标前置 / 时间范围 / 卡名可理解 / 下钻筛选承接 / 分层 / 跨页共享维度 / 批量分治 / 禁止项 / 真实数据验证）；五模式决策树；页级+组合级六维评分；案例脱敏
- **脚本**：`audit_insight_pages.py` 读 cards-raw/page-check/formulas/采样索引，输出 insight-audit.json 与 seed 建议；P0/阻断收敛（展示分封顶 64，>10 页/无可用页封顶 49）；层级混页单独识别；`insight_audit_report.py` 校验建议引用（pgId/finding/阻断 P0 覆盖/联动筛选器 cdId）并渲染 Markdown/HTML
- **交互**：audit 四步（选看板与场景 → 学习与体检 → 整合建议 → 报告），独立 `wizard-state-audit.json`；四步禁止 skipped；第 2/3/4 步产物门；preflight 检测断点
- **边界**：只读诊断，不改看板、不建洞察Agent；不覆盖 ChatBI/DecideX/仪表板洞察；报告里的配置衔接只是草案，实际配置仍在 BI 管理端
- **验证**：真实夹具 2 页 / 62 张数据卡跑通（8 条发现 / 3 P0 / 64 分需改造 / 建议校验通过 / 报告生成）；单测 389 → 468 全绿
- **后续**：复检 diff（与上次 insight-audit.json 对比）、看板 Schema YAML 导出、把诊断结论自动转成洞察Agent 默认思路/业务知识草稿，列入待办

## v4.11（洞察Agent 分析思路写作指引）——✅ 已完成（2026-10-23，v4.11.0）

v4.10 只给了一个 4 步骨架，不能指导用户为已搭建的洞察Agent 写清「每一步看哪张看板、核心分析什么、带什么结论和筛选参数进下一步」。本版本把分析思路补成完整写作方法：

- **核心循环**：用户目标 → 选看板 → 明确本步核心问题 → 选筛选参数 → 读取/比较/归因 → 形成结论 → 带着结论和筛选条件进入下一步（或终止）；下一步只带结论 + 筛选条件 + 待验证假设，不带全量明细
- **两种类型**：探索型（发散提问、动态规划、路径原则 + 看板路由 + 下钻/回退 + 终止条件 + 弹性边界）vs 报告型（固定 Step 1…N + 交付框架 + ≥3 个用户提问示例）；混合型 = 默认探索 + 报告型专家
- **单步契约**：goal / dashboards / coreQuestions / filters / output / nextIf / stopIf，每步必须写清“进入下一步”和“终止”
- **指引与模板**：`references/insight-agent-thinking-guide.md` + `references/templates/insight-thinking.md`（两套可复制模板）
- **schema 扩展**：`configHandoff` 新增 `agentType` / `stepPlan` / `exploratoryRules` / `reportFramework` / `questionExamples`；校验按类型收敛（报告型 2 步 + 3 章 + 3 个提问示例；探索型 2 条路径原则；混合型两者都要）
- **报告第 7 节**：逐步展示看板/核心问题/筛选/输出/进入/终止，附报告框架与提问示例
- **A3**：先判断 Agent 类型，再按指引写；不确定时直接问用户“自由提问探索，还是固定场景出报告”
- **验证**：`test_insight_audit_report` 28 → 35 例；全量 468 → 475 全绿
- **后续**：把分析思路草稿自动转成洞察Agent 配置的导入格式（若平台提供 API）、用真实问题回归路径合理性

## v4.12（洞察Agent 看板重建：卡片级复用）——✅ 已完成（2026-10-23，v4.12.0）

诊断建议拆分/合并/新建页后，原看板里符合洞察Agent 要求、用户看惯的卡片需要保留。整页 `page save-as` 会把冗余卡片/数据一起带过去；guanvis 0.1.50 又没有单卡 `card save-as`。本版本补卡片级复用：

- **能力边界**：checkout 的 `card_*.js` 是 `attachCard`，依赖源工程 base/manifest，不能搬到 `guanvis init` 新工程；主路径改为 `checkout` 读源卡 → `init` 目标工程 → `createCard()` 重建 → `genid` → `preview/publish`
- **抽取器**：`extract_card_skeletons.py` 按 `--cdIds` 从 cards-raw 抽选中卡，输出 `card-reuse.json` + `card-skeletons/*.js` + 核对清单；计算字段/未识别聚合以 TODO 标注，不伪造
- **报告**：新增 `cardReuse`（method 仅 `rebuild`/`keep`，拒绝整页另存），有拆分/合并/新建页时必填；第 6 节展示复用表与命令（checkout → extract → init → genid → preview → publish --dry-run → publish）
- **A3**：新增“卡片复用与迁移”步骤，要求先抽骨架再重建；诊断只读，发布必须用户确认
- **验证**：新增 extractor 7 例；报告 35 → 39 例；全量 475 → 486 全绿
- **后续**：扩展更多图表类型的 JSON→createCard 自动翻译；按目标页批量生成 page.js 布局；发布后源卡/新卡数值自动对账

## v4.12.1（回归修复：一致性/健壮性收口）——✅ 已完成（2026-10-23，v4.12.1）

v4.10–v4.12 三个版本的 review 发现 5 个 P1 + 一批一致性欠账，本版本全部收口：

- **R-01 不可绕过**：`--max-pages` 只允许 ≤10（更严格的自定预算），超过即 exit 2；报告用 `officialMaxPages` 标注官方上限，预算覆盖值单独显示（此前 11 页 + `--max-pages 12` 会得 85 分/可直接配置，报告还写"官方上限 12 张"）
- **骨架抽取**：多数据集选卡按 `dsId` 生成 `DS1…DSn` 别名并在清单给出 `init --alias` 命令；多行公式/卡名压成单行（此前会截断注释生成语法错误的 JS）；重跑清空旧 `card_*.js`；重复 `--cdIds` 去重；地图类无度量补 colorBy TODO
- **cardReuse 校验**：`cardReuse` 改为条件必填（无拆分/合并/新建页时不必出现）；`commands` 命中 `page save-as` 即 exit 2，非 dry-run 的 `publish` 给告警；报告命令块注明发布需用户确认
- **audit 确认门**：`confirm --state audit --step 3` 实际运行 `insight_audit_report.py --check`；第 4 步拒绝早于建议文件的旧报告
- **R-02 候选收敛**：只有隐藏筛选器时页面展示分封顶 79（小改后配置），不再出现"81 分/可直接配置"与 R-02 未满足并存
- **文档与死代码**：SKILL 报告章节/红线 19/交付树、ROADMAP 红线数、模板标注、`merge_cards` 过期版本常量、未使用导入等
- **复审加固**：增量合并改用语义内容指纹并拦截改名覆盖，保留 dynamicParams/inPool、清理失效 dsFormulas；采样失败不再沿用旧文件，定向采样保留索引；普通别名与未知公式恢复保守口径；多数据集骨架字段显式归属；audit 硬规则与状态门全量复核；SQL 只读解析、交付固定备份中断恢复、工作台控制文件保护、单卡取数白名单与 fail-closed 范围策略
- **验证**：单测 486 → 502 → 545 全绿；full/lite/incr/audit L1 全通过，独立 L2 100/A 零红线，基线 tests/baselines/v4.12.1.* 已归档；真实 guanvis preview/diff/publish --dry-run 通过，未正式 publish。agent-tester 升 v1.9.3 同步检查点

## 看板角色迁移——规划中（原"v4.4"规划；版本号 v4.4.0 已被增量学习通道占用，本项递延，实施时另取版本号）

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
- 靠 prompt 约束模型自觉的环节（手工转写/组装/回填）正是低配模型最容易偷工减料的地方：v4.7 实机 review 发现 cards.json 被"精简"重构导致三功能连锁瘫痪——一切结构性产物要么脚本生成、要么脚本验收（correct by construction），LLM 只产出需要判断力的语义内容
- 参数化公式（含 `[DYNAMIC_PARAMS.xxx]`）不是普通公式：SQL 引擎没有参数上下文，内联必报错或静默算错（参数名撞物理列名时）——PARAM_DEPENDENT 分类最高优先，走 card preview 传参取数（v4.9 实机验证）
- 洞察Agent 的看板要求不是"人能看就行"：每张看板必须有可被选中的联动筛选器（R-02），数据范围最多 10 页（R-01），单页 40 卡会上下文爆掉（R-06）；P0 不能被其他页高分平均掉（展示分封顶 64）；一张大页同时含总览/定位/明细不等于"三层齐全"，而是"层级混页"（v4.10 实机夹具校准）
