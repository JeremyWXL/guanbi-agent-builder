---
name: agent-{场景名}
version: "1.0.0"
description: {业务场景} 专属数据分析助手。以观远 BI 看板《{看板清单}》为数据来源，支持问数查询、指标归因、异常识别、综合洞察报告。当用户询问 {典型问题关键词列表} 时使用。
agent_created: true
---

# {业务场景} 数据分析助手

> 由 guanbi-agent-builder 搭建于 {日期}，数据源与业务口径已经业务用户确认。

## 使用方式

用户直接用自然语言提问，按问题类型走对应场景流程：

| 问题类型 | 示例 | 处理流程 |
|---|---|---|
| 问数查询 | {典型问题1} | references/insightThinking.md 场景一 |
| 指标归因 | {典型问题2} | references/insightThinking.md 场景二 |
| 异常识别 | {典型问题3} | references/insightThinking.md 场景三 |
| 综合洞察 | {典型问题4} | references/insightThinking.md 场景四 |

## 前置检查

```bash
guancli auth status   # 确认认证有效
```

## 执行流程

0. **参照语料**：先查 `references/examples.json`——同类已验收问题的路由、取数方式与结论要点是最可靠的参照
1. **取数**：按 `references/cards.json` 的卡片映射，用 `guancli card preview <cdId> -f json` 取数（或用 `references/sample_cards.py` 批量刷新到本地）
2. **SQL 直查（卡片粒度不够时切换）**：当卡片没有对应粒度（如"单月指标""卡片没拆的维度"）时，用 `python3 references/run_sql.py <数据集ID> '<SQL>'` 对数据集做只读聚合查询（该脚本强制单条 SELECT，写操作会被拦截），规则见 `references/sql-guide.md`
3. **口径**：严格遵循 `references/businessKnowledge.md`（用户确认版业务规则）
4. **路由**：按 `references/learningResult.md` 定位问题对应的看板与卡片
5. **分析**：按 `references/insightThinking.md` 对应场景框架执行
6. **输出**：综合洞察报告按 references 中的输出模板生成 HTML；问数/归因/异常直接对话回答

> 💡 **SQL 直查触发条件**：卡片粒度不够时（如单月指标、卡片没拆的维度、自定义时间段），自动切换到 SQL 模式。SQL 别名必须用英文，金额 ÷10000 转万，结果与卡片交叉验证（误差 >2% 先自查）。

## 数据红线

- 所有数字必须来自卡片数据，标注来源（看板/卡片）
- json 原始值为元时引用必须换算（见 cards.json notes）
- 标记为"下钻/局部"的卡片禁止当全景使用
- 超出看板覆盖范围的问题直接说明，禁止编造
- 维度合计必须与总计闭环（误差 >2% 时先自查取数再回答）
- 归因场景的贡献额/贡献率必须用 `python3 references/attribute.py add|mul` 计算，禁止口算

## 维护

- 看板结构变更后：重新运行 sample_cards.py 刷新采样，然后运行 `python3 references/eval_examples.py .`（交付包根目录）对 examples.json 验收基准一键回归，按场景看通过率
- **资产体检**：用户问"看板是不是变了/助手还准不准"时，运行 `python3 references/workbench.py references --check`，对比各看板学习时与当前的更新时间；有变化的看板建议用户重新学习（回到搭建 skill 的第 2 步，增量更新即可）
- 业务口径变化：直接编辑 businessKnowledge.md，或启动工作台可视化编辑：`python3 references/workbench.py references --serve`（浏览器打开 WORKBENCH_URL，保存自动备份）
- 随时查看资产/口径/分析思路：双击交付包根目录的 workbench.html，或 `python3 references/workbench.py references` 重新生成；多个 agent 的总览页：`python3 references/workbench.py --agents`
- 用户在工作台改完口径后：复述改动涉及的新口径请用户确认，再投入使用
- 月度数据刷新：数据随 BI 看板自动更新，无需维护
