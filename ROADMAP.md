# 迭代路线图（ROADMAP）

> 本文档是跨 session 的接力棒：记录当前状态、下一步计划与必须守住的设计原则。
> 历史变更看 [CHANGELOG.md](CHANGELOG.md)；评审原文（对照 GitHub 20+ 个 data agent 项目的分析）见 v2.5 当次会话结论，要点已融入本文。
> 最近更新：2026-09-24（v2.5.0 发布后）

## 当前状态快照

- **版本**：v2.5.0，已发布 GitHub（main = bb7a3f0）与 SkillHub（skillId=246636，免费版）
- **架构**：SKILL.md（八步向导 + 全程红线）+ references/scripts（7 个脚本）+ references/templates（5 个模板）+ references/cognitive-foundation.md + sql-guide.md
- **脚本现状**：`list_pages.py` / `parse_page.py`（raw JSON 主解析+文本回退+哨兵）/ `sample_cards.py`（截断+列画像）/ `validate_cards.py` / `run_sql.py`（只读强制）/ `preflight.py`（前置检查）/ `workbench.py`（1027 行单文件，无测试，是工程债）
- **发布方式**：见 `~/.agents/skills/publishing-skills/`（git push 不通时 `scripts/gh_api_push.py` 精确重放；SkillHub 用 `scripts/stage_skill.py` 构建 staging 后 publish，LICENSE/.gitignore 不入包）

## 设计原则（迭代时不得破坏）

1. **对话对象是不懂技术的业务用户**：禁用术语，每步只问必须决定的事，技术动作静默执行
2. **确认点不可跳过**：第 1、3（若补充）、4、5、7 步必须等用户明确确认；口径确认（第 4 步）是质量命门
3. **每步落盘**：产物立即写工作目录，会话中断可续建
4. **数据红线**：合计不闭环/单位存疑的卡片必须修复或标记禁用；SQL 直查必须走 run_sql.py；SQL 与看板口径差异必须声明
5. **诊断链方法论是核心差异化资产**：归因必须量化、动态下钻、建议绑定对象（开源世界无同类产品，保持领先）
6. **skill 规范**：frontmatter description 只写触发场景（瘦）；版本史只记 CHANGELOG；why-over-MUST

## v3.0（质量护城河）——下一主线

目标：把"一次性验收"变成"可回归的质量体系"，把 LLM 口算变成脚本计算。

1. **examples.json few-shot 示例库**
   - 第 5 步确认的典型问题 + 第 7 步验收通过的答案，固化为 `examples.json`：问题 → 路由看板/卡片 → 取数方式 → 期望结论要点
   - 对齐 Vanna 语料三分法（schema 文档 + 业务文档 + 示例对），目前唯一缺的是示例对
   - 交付时复制进产物包 references/，agent 回答时作为参照
2. **回归评测脚本**（新 `eval_examples.py`）
   - 重跑 examples.json 里的问题，按场景（问数/归因/异常/洞察）分类统计通过率
   - 每题带"人工确认"状态位（业界 benchmark 标注错误率可达 50%+，用户确认是本项目做对的地方，保留）
   - 用途：看板改版重新学习后一键回归"新 agent 和旧 agent 一样准吗"；第 7 步验收产物自动汇入
3. **attribute.py 归因计算引擎**
   - 加法拆解（各维度成员对总变化的贡献额/贡献率排序）与乘法拆解（店数×单店类）脚本化
   - LLM 只负责解释计算结果，禁止口算贡献占比（LLM 算术是"归因必须量化"最大的可靠性漏洞）
   - 方法论参照阿里异动归因公开方案（加/乘/除公式拆解 + 决策树剪枝），与诊断链五条铁律对接
4. **wizard-state.json 断点状态机**
   - 记录当前步骤、已完成确认点、各产物路径；替换现在"从落盘产物猜进度"的恢复方式
   - 第 0 步 preflight 后自动检测：有 state 文件则提示"从第 N 步继续"

## v3.x（治理与升级）

1. **businessKnowledge 结构化**：从自然语言规则清单升级为机器可读的指标定义（指标名/公式/维度/同义词/示例问题），可被脚本校验；字段设计向 OSI（开放语义交换标准）对齐，让口径档案跨工具可存活
2. **资产体检升级**：mtime 对比 → 结构 hash diff（学习时存卡片清单 hash，体检对比 hash+mtime 双信号）；freshness 阈值可配置（"超过 N 天未复核即提醒"）；提示具体化（"《XX》新增 2 张卡片，建议补学"）
3. **builderVersion 升级通道**：交付包写入 builder 版本号；体检时提示老 agent 可升级运行脚本（workbench.py 等交付副本目前永远停留在搭建时刻版本）
4. **workbench.py 工程化**：拆分模板渲染/数据收集/服务层，对 collect()/check_staleness() 补最小单测（1027 行无测试是最大工程债）

## 生态侧（随时可做）

- **CI**：GitHub Actions 对 7 个脚本做 py_compile + 冒烟（parse 空解析哨兵、run_sql 拦截用例），frontmatter lint
- **英文版 README**："BI dashboard → 受治理对话式 agent 搭建向导"在英文社区无同类，是发声点
- **agentskills #436**：跟进"上游来源声明"提案，本项目的 `_meta` 体检机制是超前实现，可作案例
- **趋势锚点**：Vanna 已归档、纯 RAG text-to-SQL 路线正被"受治理语义层+agent"（WrenAI/SuperSonic/Cube）取代——本项目的"口径确认产物作为查询唯一入口"定位踩在新路线上，继续强化，勿退回自由 SQL

## 已踩过的坑（迭代时避开）

- 文本正则解析 CLI 输出是最大脆弱源：v2.4 文本路径 51 卡静默丢 28（位置标记白名单过窄 + 空命名卡片）；一切解析优先走 `--raw` JSON，文本只做回退
- `_meta` 键曾导致 sample_cards.py KeyError：遍历 cards-raw.json 必须跳过 `_` 前缀键
- LLM 自由 SQL 无硬约束是事故温床：任何新取数能力都要脚本层强制（参照 run_sql.py）
- 大卡片全量采样会撑爆上下文：sample_cards.py 的 200 行截断 + profile 是底线，勿回退
