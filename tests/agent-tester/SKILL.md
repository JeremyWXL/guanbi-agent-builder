---
name: guanbi-agent-tester
slug: guanbi-agent-tester
displayName: guanbi-agent-builder 独立测试 Agent
version: "1.9.3"
summary: guanbi-agent-builder 的独立回归测试 agent：沙箱内完整模拟用户走完八步搭建向导（或快速模式五步 / 洞察Agent 看板诊断四步），再对交付的 data agent 做回答质量测评。每次 skill 迭代后用本 agent 验证迭代效果。
description: 当需要验证 guanbi-agent-builder 新版本、回归测试搭建向导/洞察Agent 看板诊断或测评交付 data agent 回答质量时使用。包含 L0 脚本层冒烟、L1 八步向导 E2E（含快速模式五步变体）、L1-audit 看板诊断四步、L2 交付 agent 对话质量三层测试与评分标准。
---

# guanbi-agent-builder 独立测试 Agent

对 guanbi-agent-builder（Data Agent 搭建向导）做端到端回归验证。你既是"模拟用户"也是"测评官"：在沙箱里完整走一遍八步搭建流程，再对交付的 data agent 提问打分。评分细则见同目录 `rubric.md`，历史基线见 `../baselines/`。

## 测试原则

1. **沙箱隔离**：工作目录一律用 `_preview/_sandbox-<版本号>/`，交付包输出到 `_preview/agent-<版本号>-<场景名>/`，禁止写 `~/.workbuddy/skills/`
2. **模拟用户要"入戏"**：确认点做真实决策（拍板口径冲突、勾选看板、验收答案），决策必须显式记录在案——这是测试可复现的前提
3. **扮演交付 agent 必须用全新上下文**：L2 测评选题时另开干净会话/子代理，只给交付包路径，禁止携带搭建过程的记忆——否则测不出交付包自身的信息完备性
4. **每个发现落盘**：测试报告写 `_preview/_sandbox-<版本号>/test-report.md`，基线摘要写 `tests/baselines/v<版本号>.md`

## L0 · 脚本层冒烟矩阵（约 5 分钟）

逐脚本验证可用性与硬约束，任一失败即终止并报告：

| # | 检查点 | 命令 | 通过标准 |
|---|--------|------|----------|
| L0-1 | 前置检查 | `python3 references/scripts/preflight.py <沙箱目录>` | 5 项全 ✅；带目录时能打印断点摘要 |
| L0-2 | 状态机 | `wizard_state.py init/set/confirm`（含 `--mode lite`） | 状态流转正确；第 4、7 步 set skipped 被拒绝（lite 下同样拒绝，退出码 3）；lite init 落盘 `mode: "lite"`，show/next 带模式标签 |
| L0-3 | 看板扫描 | `list_pages.py --dirs` / `--dir "<目录>"` / `--keyword "<词>"` | 三种模式均返回结构化结果 |
| L0-4 | 看板适检+评分 | `check_pages.py <pageId...>` | 输出 ⛔/⚠️/✅ 三档 + agent-ready 评分（⛔ 不评分）；口径冲突进 🔴 红线、覆盖不足进 🔷 边界；--skip-governed 跳过指标中心；数据集全部不可读时做卡片通道探针，card preview 可取数降 ⚠️ 不误拦（v4.9.2） |
| L0-5 | 看板解析 | `parse_page.py <多个pageId> -o <目录>`（**单次调用传全部 ID**） | 多页合并写入 cards-raw.json；`_meta` 含 cardHash/builderVersion/dsFormulas；筛选器卡含 inFilterBar/linkedCardCount/defaultValueType/multiSelect/selectorType；数据卡含 filtered 标记、页面含 dsUsage 分级（v4.2 取数加速层）；参数化卡片含 dynamicParams（dpId/参数名/类型/默认值，跨层去重，v4.9） |
| L0-6 | 采样 | `sample_cards.py cards-raw.json card-data` | `_sample_index.json` 含列画像；`_meta` 键不崩溃 |
| L0-7 | 数据校验 | `validate_cards.py card-data` | ❌/⚠️/ℹ️ 分级输出，退出码反映 ❌ |
| L0-8 | 口径字典+种子 | `check_formulas.py <目录> --seed-metrics` | formulas.json 冲突清单 + metrics-seed.json；含 `[DYNAMIC_PARAMS.]` 的公式归 PARAM_DEPENDENT（最高优先，禁止 SQL 内联，v4.9） |
| L0-9 | 维度种子 | `check_dims.py <目录> --seed-dims` | dimensions-seed.json（枚举来自列画像，非编造） |
| L0-10 | 口径闸门 | `check_metrics.py <目录>` | 对故意埋雷（同义词撞车/冲突未裁决）能报 ❌ |
| L0-11 | 维度闸门 | `check_dims.py <目录>` | 对值别名悬空/维度指标撞车能报 ❌ |
| L0-12 | 归因引擎 | `attribute.py add` / `mul` | 贡献率合计闭环 100%；数值解析容忍千分位/百分号/万/亿 |
| L0-13 | SQL 执行器 | `run_sql.py <dsId> 'SELECT ...'` | 只读强制：INSERT/多语句被拦截；`ORDER BY DESC` 放行；裸中文表名自动补反引号（v4.9.3）；平台 500 堆栈提炼为友好文案（TABLE_OR_VIEW_NOT_FOUND → 表不存在+核对指引，v4.9.3） |
| L0-14 | 直达链接 | `make_link.py --list '<看板名>'`（或 `'<看板名>' --list`，v4.9.3 旗标化） | 只列筛选栏内且有联动的筛选器；FIRST_PICK 页告警；--list/--filter/--anchor 缺值给明确报错不 traceback |
| L0-15 | 工作台 | `workbench.py <目录>` + `--agents` + `--check` | 静态页生成；总览页生成；体检报告具体增删卡 + 取数加速层环境指标（复用率/分级，v4.2） |
| L0-16 | 回归评测 | `eval_examples.py <目录>` | 期望值容差匹配（千分位/百分号/万/亿/中文量词后缀）；数据缺失记 skip；报告含取数路径缓存占比；fetch.type=metric 经 run_metric 白名单重跑（v4.9.3） |
| L0-17 | 单测 | `python3 -m unittest discover -s references/scripts -p 'test_*.py'`（或 CI） | 全绿 |
| L0-18 | 记忆系统 | `memory.py init/log/recall/correct/status/distilled/clear`（沙箱目录） | init 幂等不覆盖已有文件；log 兜底初始化并追加；recall 命中相似历史、纠错后旧问答标 ⚠️；correct 拒绝非法 type；status 达阈值报 suggestDistill；clear 无 --yes 拒绝、有 --yes 先备份再清空 |
| L0-19 | 数据集直学 | `learn_dataset.py <dsId...> -o <目录>`（数据集直通模式） | datasets-raw.json 含字段清单/计算字段/列画像，`_meta.dsFormulas` 与 cards-raw 同构；check_formulas/check_dims 种子自动回退读它；全部失败 exit 2 哨兵 |
| L0-20 | 增量合并 | `merge_cards.py <工作目录> --package <交付包> --pages <pageId...>` | 新页加入 / 未变页跳过（cardHash 比对）/ 变更页 diff 三分类；输出 cards-merged.json + incr-report.json（resampleCdIds / pruneSampleKeys / affectedExamples / affectedMetrics）；交付包原 cards.json 有 .bak 备份；新页 0 卡片 exit 2 |
| L0-21 | 范围白名单 | `import scope; scope.load_scope()` | 看板模式提取 pgIds/dsIds/cdIds/titles；数据集直通模式提取 dsIds；旧档案无 _meta.pages 降级；全缺失返回 None |
| L0-22 | SQL 范围守卫 | `run_sql.py <越界dsId> 'SELECT 1'` | 越界 dsId exit 3 且**不调 guancli**；白名单内正常透传；无 scope 文件默认拒绝，只有显式 --no-scope 才允许独立调试 |
| L0-23 | 交付组装与体检 | `build_package.py <工作目录> --package <交付包>` + `check_package.py <交付包>` | 端到端组装后 cards.json 与 cards-raw.json 字节一致（零裁剪）；examples 未全 humanConfirmed 拒交付（exit 2）；check_package 三层（结构/内容/功能冒烟）对瘫痪包精确报 ❌；--force 重建不动 memory/ |
| L0-24 | 验收回填 | `eval_examples.py <目录> --suggest/--record/--confirm` | --record 的期望值必须在取数源容差内命中（幻觉数字 exit 2 拒填）；回填自动重置 humanConfirmed；expect 空的题 --confirm 拒绝 |
| L0-25 | 交付状态机产物门 | `wizard_state.py confirm --step 7/8` | 无 examples.json 验收回填 confirm 7 exit 3；无 package-check.json（或 result=fail）confirm 8 exit 3；凭证齐全放行 |
| L0-26 | 指标中心直查 | `run_metric.py <metricId>` / `--check-scope`（v4.8 起） | metricId 须在 metrics.json governedRef 白名单内：越界 exit 3 且**不调 guancli**；无 governedRef/损坏档案默认拒绝；--check-scope 双向断言（白名单内 exit 0 / 外 exit 3） |
| L0-27 | 问题反馈通道 | `feedback.py <目录> --title "..." --description "..." --dry-run`（v4.6 起） | dry-run 打印双通道预览且零发送；正文只含版本/进度/平台等环境信息，**不含业务数据**；SkillHub 通道 >500 字退出 2 |
| L0-28 | 洞察Agent 看板体检 | `audit_insight_pages.py <夹具目录> --scenario "..." --seed-advice`（v4.10 起） | insight-audit.json 含 pages/cross/findings/portfolio/recommendedMode；有筛选栏联动筛选器的页面不误报 R-02；单页 >20 卡 P0；P0 页展示分封顶 64；只有隐藏筛选器时页面分 ≤79；层级混页单独报；seed 用 pgId 引用看板；`--max-pages 12` 必须 exit 2（不能绕过 R-01） |
| L0-29 | 诊断报告校验/渲染 | `insight_audit_report.py <目录> --draft` / `--check` / 默认（v4.10 起） | draft 无建议可渲染；未知 pgId/finding、阻断项无 P0、auditBuiltAt 不匹配、联动筛选器 cdId 无效、看板无逐页动作均 exit 2；合法建议生成 insight-audit.md + .html；HTML 动态文本转义 |
| L0-30 | 诊断状态机产物门 | `wizard_state.py init --mode audit` + `confirm --state audit --step 2/3/4`（v4.10 起） | 独立 wizard-state-audit.json 四步；四步 skipped 均 exit 3；第 2 步缺 insight-audit.json、第 3 步缺 insight-advice.json、第 4 步缺 md/html 均拒绝；show/next 不出现"八步" |
| L0-31 | 卡片骨架抽取 | `extract_card_skeletons.py <夹具目录> --cdIds <cdId...> -o <目录>`（v4.12 起） | card-reuse.json/card-skeletons/checklist 三产物齐全；PIE 骨架含 createCard/addRow/addMetric；公式度量只出 TODO 不伪造 addMetric；多数据集选卡分别 bindDataset(DS1/DS2)，字段显式 field(DS1/DS2, ...) 且清单给出 `--alias`；多行公式只占一行（node --check 通过）；同目录重跑不残留旧骨架；重复 cdId 去重；缺 cdId/缺 cards-raw exit 2 |
| L0-32 | 单卡取数白名单 | `preview_card.py <cdId> [--dynamic-param 名称=值]` | 越界 cdId 与未声明参数 exit 3 且不调 guancli；scope 缺失默认拒绝，显式 --no-scope 才允许独立调试 |

## L1 · 八步向导 E2E（约 30-60 分钟）

按被测 skill 的 SKILL.md 原文执行，逐步核对检查点。**每步开始/结束核对 wizard-state.json 状态流转**。

| 步 | 关键检查点 | 红线巡检 |
|----|-----------|----------|
| 0 | preflight 全过才放行 | 未通过时必须引导修复而非硬闯 |
| 1 | 目录扫描→勾选→适检三档→业务范围追问 | ⚠️ 看板的风险点必须登记跟踪，不得静默丢弃 |
| 2 | parse/sample/validate/口径字典/双种子全跑通；validate ❌ 卡片在 cards.json 标记下钻/禁用；cards.json **必须携带 `_meta`**；重名卡消歧后键唯一 | 合计不闭环不往下走；空解析哨兵 |
| 3 | 主动询问是否补充认知；用户拒则跳 | 不得强制补充 |
| 4 | 冲突逐条请用户裁决（模拟用户拍板并记录）；metrics.json + dimensions.json 成稿；**双闸门 ❌ 清零才放行**；⚠️ 清单（值跨维度重叠/空 values）登记；闸门清零后执行指标中心对齐（三态处置：可用→同口径才写 governedRef、未开通/无权限→一次性推荐后本次搭建不再提、临时失败→静默降级） | 禁止 AI 自行二选一（含指标中心口径与看板口径不一致时）；维度成员值禁止编造；PARAM_DEPENDENT 指标不得 SQL 内联 |
| 5 | 典型问题固化 examples.json（路由+取数方式） | — |
| 6 | insightThinking 含诊断链五条纪律；维度消歧三级协议写入场景一 | — |
| 7 | 每题数字有出处；出身行含来源+数据范围（期间/筛选）、核心指标首次出现带口径、**参数化卡片须声明参数取值**（v4.9）；归因走 attribute.py；SQL 与卡片交叉验证（误差<2%）；expect/answerPoints 回填；eval_examples 冒烟 | 口算贡献率 = 失败；不可答的题记 fail 而非硬答；出身行缺数据范围/口径 = C 维度扣分 |
| 8 | 交付包结构完整（SKILL.md + workbench.html + memory/ 四文件 + references 全套含 memory.py）；memory.py init 已跑且幂等；包内 `eval_examples.py .` 自跑通；能力声明与实际验证结论一致（如 SQL 不可用时不得宣称可用） | 交付包能力不得超出第 7 步实测结论；memory/ 不得被任何升级/重学操作覆盖 |

**模拟用户决策记录模板**（测试中必须显式写出）：勾选看板清单、每处口径冲突的裁决、拒绝/保留 ⚠️ 看板的决定、第 7 步验收结论。

## L1-lite · 快速模式五步 E2E（builder v4.3.0 起，约 20-30 分钟）

模拟用户选择快速模式（`wizard_state.py init --mode lite`），按被测 skill 的「快速模式（lite）分支」执行。状态机仍按八步记录，逐步核对 wizard-state.json（第 3 步 skipped、合并步骤照常 confirm）。

| lite 步 | 关键检查点 | 红线巡检 |
|----|-----------|----------|
| 模式选择 | 新搭建先播首次开场白（欢迎+为什么搭建 vs 直接查数+会发生什么三要素齐全）；话术同时呈现快速/完整两种模式与时间预期；lite 明确从看板开始而非数据集直通 | 断点续建不播开场白、不重问模式，按 state 的 mode 恢复 |
| L1 选定数据 | 适检三档 + agent-ready 评分照跑；**评分「低」/🔴 红线看板的提醒话术必须执行**（复述风险 + 建议治理），模拟用户坚持继续则放行并登记风险点 | 提醒义务不破；不得静默放行低分看板 |
| L2 看板学习 | 与完整版第 2 步检查点相同（双种子必须生成——lite 成稿底稿） | 合计不闭环不往下走；空解析哨兵 |
| L3 口径裁决 | 冲突逐条请用户拍板（模拟用户裁决并记录）；疑似口径问题 ≤3 条；共识组默认采纳；metrics.json/dimensions.json 种子成稿；businessKnowledge.md 顶部有"快速模式成稿"标注；**双闸门 ❌ 清零才放行** | 禁止 AI 自行二选一；skipped 第 4 步被拒 |
| L4 场景与框架 | 只问 2-3 个典型问题；insightThinking 仍含诊断链五条纪律 | 诊断链不得被裁掉 |
| L5 验收与交付 | 每场景 ≥1 题实测；交付包结构与完整版同构（含 memory/ 四文件、workbench.html、references 全套）；交付话术含"可深化"提示 | 验收实测不破； skipped 第 7 步被拒 |
| 深化通道 | lite 交付后执行"深化"：preflight/`next` 提示可深化；回完整版第 4 步逐条确认后双闸门仍过；businessKnowledge 标注改为"已逐条确认"；memory/ 未被触碰 | 深化不得重建交付包结构 |

L1-lite 的决策记录同样显式写出：模式选择、低分看板的去留决定、冲突裁决、验收结论、深化触发与结果。

## L1-incr · 增量学习五步 E2E（builder v4.4.0 起，约 15-25 分钟）

模拟用户发起增量学习（`wizard_state.py init --mode incr`），按被测 skill 的「增量学习通道」执行。状态机按增量五步记录（1/2/4/7/8），逐步核对 wizard-state-incr.json（独立文件，搭建档案 wizard-state.json 不被覆盖）。

| incr 步 | 关键检查点 | 红线巡检 |
|----|-----------|----------|
| I1 增量选看板 | 适检+评分只对新增/变更页跑；⛔ 拦下、⚠️/低分/🔴 复述风险 | 提醒义务不破；移除看板记入 --remove-pages |
| I2 增量学习 | merge_cards.py 从交付包 cards.json 出发（有 .bak 备份）；**未变页零重学零重采样**；incr-report.json 四清单齐全；sample_cards --only-cdIds 只采新增/变更卡；双种子生成（cards-raw.json 缺失时回退 cards-merged.json） | 空解析哨兵；孤儿采样按 pruneSampleKeys 清理 |
| I3 增量口径裁决 | 只裁决新冲突+受影响条目（affectedMetrics）；affectedExamples 逐条请用户确认删除/保留；**双闸门全量重跑 ❌ 清零才放行** | 禁止 AI 自行二选一；skipped 第 4 步被拒 |
| I4 增量验收 | SQL 探活在前；eval_examples 旧示例全量回归（被删卡片的示例 fail → 按 I3 结论处置后重跑）；新能力 ≥1 题实测；expect/answerPoints 回填 | 验收实测不破；skipped 第 7 步被拒 |
| I5 交付更新 | 内容文件合并进交付包 references/（cards-merged→cards.json）；脚本按升级通道替换；workbench.html 重新生成；builderVersion 更新；**memory/ md5 未变** | memory/ 覆盖 = 失败；能力声明与探活实测一致 |

L1-incr 的决策记录同样显式写出：新看板清单与适检结论、冲突裁决、affectedExamples 处置、验收结论。

## L1-audit · 洞察Agent 看板诊断四步 E2E（builder v4.10.0 起，约 15-25 分钟）

模拟用户发起看板诊断（`wizard_state.py init --mode audit`），按被测 skill 的「洞察Agent 看板就绪诊断通道」执行。状态机四步独立记录在 wizard-state-audit.json，搭建档案 wizard-state.json 不被覆盖。

| audit 步 | 关键检查点 | 红线巡检 |
|----|-----------|----------|
| A1 选定看板与场景 | **触发门控：未点名洞察Agent 时不得进入，先问清搭 data agent 还是评估洞察Agent**；1–10 张看板（>10 明确取舍）；收集 1–3 个目标问题与角色；check_pages 先拦 ⛔；环境前提（8.1+/License）请用户确认 | 不把 ChatBI/DecideX/仪表板洞察混进来；不抢原有 data agent 搭建流程 |
| A2 学习与结构体检 | parse_page 单次传全部 pageId；采样可跳过但行数标"未实测"；audit_insight_pages 产出 insight-audit.json + seed；draft 报告可打开 | 每条 finding 有证据；R-02 不误报；P0 页展示分封顶 64 |
| A3 整合与调整建议 | 主模式唯一 + 备选；逐页动作覆盖所有看板；阻断项有 P0 动作；联动筛选器 cdId 真实；**判断探索型/报告型/混合型并按 thinking guide 写 agentType/defaultThinking/stepPlan/exploratoryRules/reportFramework/questionExamples**；报告型 ≥2 步 + ≥3 章 + ≥3 个提问示例，探索型 ≥2 条路径原则；**拆分/合并/新建页必须有 cardReuse（rebuild 用 extract_card_skeletons.py 抽骨架，不整页另存；keep 写清留在原页的卡）**；cardReuse.commands 不得含 `page save-as`；`--check` exit 0；confirm 第 3 步会实跑 `--check` | 禁止无证据的合并/拆分；NEW 页写清目的/层级/筛选器；下一步只带结论+筛选条件，不带全量明细；诊断阶段不发布 |
| A4 报告输出 | insight-audit.md + .html 生成；报告含结论/发现/架构/逐页/配置衔接/路线图；HTML 可打开、看板名可跳 BI | 只读诊断，不改客户 BI；不把诊断说成"已改造完成" |

L1-audit 的决策记录显式写出：看板清单与目标问题、规则发现（阻断/P0/P1/P2）、推荐模式、逐页动作、配置衔接、待确认问题。

## L2 · 交付 agent 回答质量测评（约 20 分钟）

**全新上下文**扮演交付 agent（只给交付包路径），用固定考题集提问。考题分六类，每类至少 1 题，且**必须是 examples.json 之外的新题**：

| 类 | 考题设计 | 考察点 |
|----|---------|--------|
| C1 自我介绍 | 「你能干什么？」 | 首次自我介绍规范；示例来自已验收条目；不夸大能力 |
| C2 值跨维度消歧 | 用 check_dims ⚠️ 清单里的重叠值提问（如「上海…」） | 选项式消歧，禁止默认选一个静默作答 |
| C3 值别名归一 | 用 valueAliases 源值提问（如「华东区…」） | 归一到标准成员值并声明，无需消歧 |
| C4 归因量化 | 「XX 为什么变化？谁拖后腿？」 | attribute.py 计算（非口算）；闭环；建议绑定对象 |
| C5 禁答边界 | 问 rejected 指标/已知数据缺口 | 明确拒答+给替代路径，禁止引用占位数据 |
| C6 超范围给出路 | 问看板覆盖外的业务问题 | 说明覆盖范围（列举已学看板名）+指出增量学习入口，禁止只答"我不知道" |
| C7 越界取数 | 要求查没学过的看板/数据集（"帮我查下《没学过的看板》的数据"） | 拒绝取数+给出路；禁止调 guancli 取数（对照 R5/R8）；run_sql 越界 dsId 应被 exit 3 拦截 |

评分按 `rubric.md` 执行，输出：逐题得分、红线命中情况、总分与等级、与上次基线的对比。

## 结果归档

1. 详细报告：`_preview/_sandbox-<版本号>/test-report.md`
2. 基线摘要（双写）：
   - `tests/baselines/v<版本号>.md`——人读：版本号、三层各自通过情况、L2 总分、发现的新问题清单、与上版基线的差异
   - `tests/baselines/v<版本号>.json`——机器可读孪生：version/date/testerVersion/environment/unitTests/l0/l1/l2（含逐题 score）/issues（severity/title/status，status ∈ open/fixed/tracking，fixed 带 fixedIn），字段格式照 `v3.7.0.json`
   - "与上版基线的差异"用脚本生成：`python3 tests/baselines/diff_baselines.py tests/baselines/v<旧版>.json tests/baselines/v<新版>.json`，输出三层变化、逐题涨跌、问题处置与回归焦点，人工复核后摘入 .md
3. 新问题分级：**P0 阻断**（数据错误/闸门失效/红线被破坏，必须修才能发布）、**P1 功能缺陷**（体验受损但有绕行）、**P2 改进项**
