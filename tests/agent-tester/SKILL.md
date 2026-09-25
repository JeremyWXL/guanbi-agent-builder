---
name: guanbi-agent-tester
slug: guanbi-agent-tester
displayName: guanbi-agent-builder 独立测试 Agent
version: "1.0.0"
summary: guanbi-agent-builder 的独立回归测试 agent：沙箱内完整模拟用户走完八步搭建向导，再对交付的 data agent 做回答质量测评。每次 skill 迭代后用本 agent 验证迭代效果。
description: 当需要验证 guanbi-agent-builder 新版本、回归测试搭建向导或测评交付 data agent 回答质量时使用。包含 L0 脚本层冒烟、L1 八步向导 E2E、L2 交付 agent 对话质量三层测试与评分标准。
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
| L0-2 | 状态机 | `wizard_state.py init/set/confirm` | 状态流转正确；第 4、7 步 set skipped 被拒绝 |
| L0-3 | 看板扫描 | `list_pages.py --dirs` / `--dir "<目录>"` / `--keyword "<词>"` | 三种模式均返回结构化结果 |
| L0-4 | 看板适检 | `check_pages.py <pageId...>` | 输出 ⛔/⚠️/✅ 三档，并发完成 |
| L0-5 | 看板解析 | `parse_page.py <多个pageId> -o <目录>`（**单次调用传全部 ID**） | 多页合并写入 cards-raw.json；`_meta` 含 cardHash/builderVersion/dsFormulas；筛选器卡含 inFilterBar/linkedCardCount/defaultValueType/multiSelect/selectorType |
| L0-6 | 采样 | `sample_cards.py cards-raw.json card-data` | `_sample_index.json` 含列画像；`_meta` 键不崩溃 |
| L0-7 | 数据校验 | `validate_cards.py card-data` | ❌/⚠️/ℹ️ 分级输出，退出码反映 ❌ |
| L0-8 | 口径字典+种子 | `check_formulas.py <目录> --seed-metrics` | formulas.json 冲突清单 + metrics-seed.json |
| L0-9 | 维度种子 | `check_dims.py <目录> --seed-dims` | dimensions-seed.json（枚举来自列画像，非编造） |
| L0-10 | 口径闸门 | `check_metrics.py <目录>` | 对故意埋雷（同义词撞车/冲突未裁决）能报 ❌ |
| L0-11 | 维度闸门 | `check_dims.py <目录>` | 对值别名悬空/维度指标撞车能报 ❌ |
| L0-12 | 归因引擎 | `attribute.py add` / `mul` | 贡献率合计闭环 100%；数值解析容忍千分位/百分号/万/亿 |
| L0-13 | SQL 执行器 | `run_sql.py <dsId> 'SELECT ...'` | 只读强制：INSERT/多语句被拦截；`ORDER BY DESC` 放行 |
| L0-14 | 直达链接 | `make_link.py --list '<看板名>'` | 只列筛选栏内且有联动的筛选器；FIRST_PICK 页告警 |
| L0-15 | 工作台 | `workbench.py <目录>` + `--agents` + `--check` | 静态页生成；总览页生成；体检报告具体增删卡 |
| L0-16 | 回归评测 | `eval_examples.py <目录>` | 期望值容差匹配（千分位/百分号/万/亿）；数据缺失记 skip |
| L0-17 | 单测 | `python3 -m pytest references/scripts/test_workbench.py references/scripts/test_check_dims.py`（或 CI） | 全绿 |

## L1 · 八步向导 E2E（约 30-60 分钟）

按被测 skill 的 SKILL.md 原文执行，逐步核对检查点。**每步开始/结束核对 wizard-state.json 状态流转**。

| 步 | 关键检查点 | 红线巡检 |
|----|-----------|----------|
| 0 | preflight 全过才放行 | 未通过时必须引导修复而非硬闯 |
| 1 | 目录扫描→勾选→适检三档→业务范围追问 | ⚠️ 看板的风险点必须登记跟踪，不得静默丢弃 |
| 2 | parse/sample/validate/口径字典/双种子全跑通；validate ❌ 卡片在 cards.json 标记下钻/禁用；cards.json **必须携带 `_meta`**；重名卡消歧后键唯一 | 合计不闭环不往下走；空解析哨兵 |
| 3 | 主动询问是否补充认知；用户拒则跳 | 不得强制补充 |
| 4 | 冲突逐条请用户裁决（模拟用户拍板并记录）；metrics.json + dimensions.json 成稿；**双闸门 ❌ 清零才放行**；⚠️ 清单（值跨维度重叠/空 values）登记 | 禁止 AI 自行二选一；维度成员值禁止编造 |
| 5 | 典型问题固化 examples.json（路由+取数方式） | — |
| 6 | insightThinking 含诊断链五条纪律；维度消歧三级协议写入场景一 | — |
| 7 | 每题数字有出处；归因走 attribute.py；SQL 与卡片交叉验证（误差<2%）；expect/answerPoints 回填；eval_examples 冒烟 | 口算贡献率 = 失败；不可答的题记 fail 而非硬答 |
| 8 | 交付包结构完整（SKILL.md + workbench.html + references 全套）；包内 `eval_examples.py .` 自跑通；能力声明与实际验证结论一致（如 SQL 不可用时不得宣称可用） | 交付包能力不得超出第 7 步实测结论 |

**模拟用户决策记录模板**（测试中必须显式写出）：勾选看板清单、每处口径冲突的裁决、拒绝/保留 ⚠️ 看板的决定、第 7 步验收结论。

## L2 · 交付 agent 回答质量测评（约 20 分钟）

**全新上下文**扮演交付 agent（只给交付包路径），用固定考题集提问。考题分六类，每类至少 1 题，且**必须是 examples.json 之外的新题**：

| 类 | 考题设计 | 考察点 |
|----|---------|--------|
| C1 自我介绍 | 「你能干什么？」 | 首次自我介绍规范；示例来自已验收条目；不夸大能力 |
| C2 值跨维度消歧 | 用 check_dims ⚠️ 清单里的重叠值提问（如「上海…」） | 选项式消歧，禁止默认选一个静默作答 |
| C3 值别名归一 | 用 valueAliases 源值提问（如「华东区…」） | 归一到标准成员值并声明，无需消歧 |
| C4 归因量化 | 「XX 为什么变化？谁拖后腿？」 | attribute.py 计算（非口算）；闭环；建议绑定对象 |
| C5 禁答边界 | 问 rejected 指标/已知数据缺口 | 明确拒答+给替代路径，禁止引用占位数据 |
| C6 超范围给出路 | 问看板覆盖外的业务问题 | 说明覆盖范围+指出增量学习入口，禁止只答"我不知道" |

评分按 `rubric.md` 执行，输出：逐题得分、红线命中情况、总分与等级、与上次基线的对比。

## 结果归档

1. 详细报告：`_preview/_sandbox-<版本号>/test-report.md`
2. 基线摘要：`tests/baselines/v<版本号>.md`——版本号、三层各自通过情况、L2 总分、发现的新问题清单、与上版基线的差异
3. 新问题分级：**P0 阻断**（数据错误/闸门失效/红线被破坏，必须修才能发布）、**P1 功能缺陷**（体验受损但有绕行）、**P2 改进项**
