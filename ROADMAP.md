# 迭代路线图（ROADMAP）

> 本文档是跨 session 的接力棒：记录当前状态、下一步计划与必须守住的设计原则。
> 历史变更看 [CHANGELOG.md](CHANGELOG.md)；评审原文（对照 GitHub 20+ 个 data agent 项目的分析）见 v2.5 当次会话结论，要点已融入本文。
> 最近更新：2026-09-25（v3.1.0）

## 当前状态快照

- **版本**：v3.1.0（资产体检升级 + builderVersion 升级通道），已发布 GitHub（fc4195c）与 SkillHub（skillId=246636，409 探针确认入库；install 短时仍旧版本是索引延迟）
- **架构**：SKILL.md（八步向导 + 全程红线）+ references/scripts（12 个脚本）+ references/templates（6 个模板）+ references/cognitive-foundation.md + sql-guide.md
- **脚本现状**：`list_pages.py` / `check_pages.py`（看板适检三档）/ `parse_page.py`（raw JSON 主解析+文本回退+哨兵+公式收割+结构指纹）/ `check_formulas.py`（口径字典）/ `sample_cards.py`（截断+列画像）/ `validate_cards.py` / `run_sql.py`（只读强制）/ `preflight.py`（前置检查+断点检测）/ `wizard_state.py`（断点状态机）/ `attribute.py`（归因引擎）/ `eval_examples.py`（回归评测）/ `workbench.py`（1300+ 行单文件，无测试，是工程债）
- **发布方式**：见 `~/.agents/skills/publishing-skills/`（git push 不通时 `scripts/gh_api_push.py` 精确重放；SkillHub 用 `scripts/stage_skill.py` 构建 staging 后 publish，LICENSE/.gitignore 不入包）

## 设计原则（迭代时不得破坏）

1. **对话对象是不懂技术的业务用户**：禁用术语，每步只问必须决定的事，技术动作静默执行
2. **确认点不可跳过**：第 1、3（若补充）、4、5、7 步必须等用户明确确认；口径确认（第 4 步）是质量命门
3. **每步落盘**：产物立即写工作目录，会话中断可续建
4. **数据红线**：合计不闭环/单位存疑的卡片必须修复或标记禁用；SQL 直查必须走 run_sql.py；SQL 与看板口径差异必须声明
5. **诊断链方法论是核心差异化资产**：归因必须量化、动态下钻、建议绑定对象（开源世界无同类产品，保持领先）
6. **skill 规范**：frontmatter description 只写触发场景（瘦）；版本史只记 CHANGELOG；why-over-MUST

## v3.0（质量护城河）——✅ 已完成（2026-09-25，v3.0.0）

四项全部落地：examples.json 示例库（模板 + 第 5/7/8 步接线，对齐 Vanna 语料三分法的"示例对"）、eval_examples.py 回归评测（数据层自动核验 + 结论层人工确认状态位）、attribute.py 归因引擎（加法拆解 + 2~4 因子 Shapley 乘法拆解，精确闭环）、wizard_state.py 断点状态机 + preflight 断点检测（第 4/7 命门步禁止 skipped）。详见 CHANGELOG。

## v3.x（治理与升级）——下一主线

- ~~资产体检升级~~、~~builderVersion 升级通道~~ —— ✅ 已完成（v3.1.0）：结构指纹双信号 + 具体增删报告 + `--fresh-days` 复核阈值 + `_meta.builderVersion` 升级提示（总览页徽章）
1. **businessKnowledge 结构化**：从自然语言规则清单升级为机器可读的指标定义（指标名/公式/维度/同义词/示例问题），可被脚本校验；字段设计向 OSI（开放语义交换标准）对齐，让口径档案跨工具可存活
2. **workbench.py 工程化**：拆分模板渲染/数据收集/服务层，对 collect()/check_staleness() 补最小单测（1300+ 行无测试是最大工程债）

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
- preflight.py `--json` 输出不是纯 JSON（人类可读行与 JSON 块混排，finish() 设计如此）；如需管道化解析需截取 JSON 块或另做改造
- eval_examples.py 的 fetch.file 相对工作目录解析，与 sample_cards.py 的扁平命名 `card-data/<看板名>__<卡片名>.json` 对齐；交付包内回归用 `python3 references/eval_examples.py .`（包根目录），run_sql.py 定位优先 `<工作目录>/references/scripts/`、回退同目录
