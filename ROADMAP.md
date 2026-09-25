# 迭代路线图（ROADMAP）

> 本文档是跨 session 的接力棒：记录当前状态、下一步计划与必须守住的设计原则。
> 历史变更看 [CHANGELOG.md](CHANGELOG.md)；评审原文（对照 GitHub 20+ 个 data agent 项目的分析）见 v2.5 当次会话结论，要点已融入本文。
> 最近更新：2026-09-25（v3.3.0）

## 当前状态快照

- **版本**：v3.3.1（交互体验第二批：对话体验规范），已发布 GitHub 与 SkillHub（skillId=246636）至 v3.3.0，v3.3.1 待发布
- **架构**：SKILL.md（八步向导 + 全程红线）+ references/scripts（14 个脚本 + test_workbench.py 单测）+ references/templates（7 个模板）+ references/cognitive-foundation.md + sql-guide.md；CI 在 .github/workflows/ci.yml
- **脚本现状**：`list_pages.py` / `check_pages.py`（看板适检三档）/ `parse_page.py`（raw JSON 主解析+文本回退+哨兵+公式收割+结构指纹）/ `check_formulas.py`（口径字典 + `--seed-metrics` 种子）/ `check_metrics.py`（口径档案校验闸门）/ `sample_cards.py`（截断+列画像）/ `validate_cards.py` / `run_sql.py`（只读强制）/ `preflight.py`（前置检查+断点检测）/ `wizard_state.py`（断点状态机）/ `attribute.py`（归因引擎）/ `eval_examples.py`（回归评测）/ `workbench.py`（保存回调已抽离为 make_save_file，核心路径有单测覆盖；整体仍单文件——交付模型约束，勿拆多文件）
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

## v3.3（交互体验主线）——第一批完成（v3.3.0）

> 来源：2026-09-25 交互体验评审。三层界面（搭建向导/交付助手/工作台）的共识：功能骨架已扎实，差距在"省不省事、迷不迷路"。

- ~~P0 文档同步~~ —— ✅ v3.3.0：agent-SKILL.md 体检段更新为结构指纹版，口径来源接入 metrics.json/check_metrics.py
- ~~P1.1 口径纠错对话闭环~~ —— ✅ v3.3.0：复述确认 → 双写回 metrics.json + businessKnowledge.md → check_metrics.py 校验 → "已记住"
- ~~P1.2 首次对话自我介绍~~、~~P1.3 数据出身行~~、~~P1.4 模糊问题选项式消歧~~、~~P1.5 超范围给出路~~ —— ✅ v3.3.1：agent-SKILL.md 新增「对话体验规范」一节，insightThinking.md 场景一同步
- ~~P2.6 口径确认异议驱动~~ —— ✅ v3.3.0：共识条目分组默认采纳，冲突/存疑项置顶拍板（红线不破）
- ~~P2.7 每步进度播报~~ —— ✅ v3.3.0："第 N 步/共 8 步 · 干什么 · 还要多久"，断点续建同样播报
- **P1.6 看板筛选直达链接**（⏸️ 待验证，现场在 `git stash@{0}`）：观远官方文档支持页面 URL 拼 `?筛选器ID=值`，但实机三次（cdId / fdId / DOM data-test-id）均未生效；文档说真 ID 要从筛选器编辑 UI"复制筛选器ID"获取，合成点击唤不起该菜单。下一步：人工复制一次真 ID 复核格式，再决定 make_link.py 的 ID 获取通道（若真 ID 不在 page get --raw 返回里，此能力需降级为"手工配一次 ID 映射"）
- **P3 工作台指标档案表格视图**：metrics.json 从裸 JSON 变表单化展示/编辑（工作量最大，单列）

## v3.x（治理与升级）——✅ 主线全部完成（v3.1.0–v3.2.1）

- ~~资产体检升级~~、~~builderVersion 升级通道~~ —— ✅ v3.1.0：结构指纹双信号 + 具体增删报告 + `--fresh-days` 复核阈值 + `_meta.builderVersion` 升级提示（总览页徽章）
- ~~businessKnowledge 结构化~~ —— ✅ v3.2.0：metrics.json 机器可读口径档案（OSI 对齐）+ check_metrics.py 校验闸门 + `--seed-metrics` 种子生成
- ~~workbench.py 工程化~~ —— ✅ v3.2.1：保持单文件交付形态（约束），保存回调抽离 make_save_file + test_workbench.py 10 例最小单测 + GitHub Actions CI（含版本号一致性检查）

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
- preflight.py `--json` 输出不是纯 JSON（人类可读行与 JSON 块混排，finish() 设计如此）；如需管道化解析需截取 JSON 块或另做改造
- eval_examples.py 的 fetch.file 相对工作目录解析，与 sample_cards.py 的扁平命名 `card-data/<看板名>__<卡片名>.json` 对齐；交付包内回归用 `python3 references/eval_examples.py .`（包根目录），run_sql.py 定位优先 `<工作目录>/references/scripts/`、回退同目录
