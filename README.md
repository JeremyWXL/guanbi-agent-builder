# guanbi-agent-builder

Data Agent 搭建向导：把熟悉的观远 BI 看板变成 AI data agent 的引导式 skill。

本 skill 以对话方式引导**不懂技术的业务用户**一步步搭建自己的 data agent——以观远 BI 仪表板为数据来源，覆盖问数查询、指标归因、异常识别、综合洞察四类场景，参照观远官方 Dashboard Agent 的配置结构（pages / learningResult / businessKnowledge / insightThinking / outputFormat）自动生成配置，关键环节由用户确认纠偏。

## 两种用法

- **搭 data agent**（八步向导 / 快速模式 / 增量学习）：把看板变成 WorkBuddy 里能问数、归因、出报告的助手。
- **诊断洞察Agent 看板**（v4.10 起，audit 四步）：指定 1–10 张看板，按观远洞察Agent 对看板的要求做结构体检，给出合并/拆分/补筛选器/补层/统一口径等整合建议，并附配置衔接草案。只读诊断，不改客户 BI。

**触发门控**：默认走 data agent 搭建；只有用户明确点名「洞察Agent」或要求配置洞察Agent 时才走诊断。用户只说"看板体检/看板优化"但没点名时，先问清是搭 data agent 还是评估洞察Agent，不主动切通道。

> 边界：观远洞察Agent（Data Agent > 洞察智能体）≠ ChatBI ≠ DecideX ≠ 仪表板洞察 ≠ 本工具八步向导产出的 WorkBuddy data agent。

## 特性

- **八步向导**：选定数据范围 → 看板资产学习 → 业务认知补充 → 口径确认 → 场景确认 → 配置生成 → 测试验收 → 固化交付；另有**快速模式**（v4.3 起，约 15 分钟五步先跑起来，随时深化）与**增量学习通道**（v4.4 起，加看板/改版重学/移除看板，只学增量不动已有口径与记忆）
- **行业认知预研 + 历史报告提炼**（v2.0 起）：解决"裸看板搭建、缺业务输入"的核心短板
- **质量前置闸**（v4.1 起）：看板适检三档 + agent-ready 评分，口径混乱的知识源在投入学习前拦下来；没有合适看板时可走数据集直通路径（v4.1.1 起，能力边界诚实标注为"数据探索型"）
- **洞察Agent 看板就绪诊断**（v4.10 起）：1–10 张看板的结构体检 + 六维就绪度评分 + 五模式建议（宽表/多层下钻/主从Agent/批量分治/链路复盘）+ 逐页调整清单 + 每页联动筛选器/业务范围/默认思路等配置衔接；规则依据官方文档与项目方法论，输出 HTML/Markdown 报告与机器可读 JSON
- **双档案口径治理**（v3.2/v3.7 起）：metrics.json / dimensions.json 机器可读档案 + 双闸门校验，口径冲突逐条请用户裁决、禁止 AI 二选一；指标中心轻量集成（v4.8 起，引用平台已发布口径走 governedRef 直查）
- **交付工程化**（v4.7 起）：build_package 机械组装 + 模板渲染 + check_package 三层体检总闸门，验收实测回填后才允许交付——低配模型也搭不出"瘫痪包"
- **记忆系统**（v4.0 起）：交付 agent 带用户画像/问答流水/纠错台账，脚本升级永不覆盖用户资产
- **范围守卫**（v4.5 起）：取数白名单脚本化 + 问答流水审计，覆盖外看板/数据集的数据禁止当答案
- **校验工作台与资产体检**（v2.3/v2.4 起）：资产/口径/分析思路变成浏览器里可查看、可直接编辑的页面，保存自动备份；卡片结构指纹比对，看板改版自动提醒重新学习；`--agents` 多 agent 管理总览
- **全局参数全链路**（v4.9 起）：DYNAMIC_PARAMS 学习可发现、口径有分类（PARAM_DEPENDENT 禁止 SQL 内联）、取数可传参
- **自动校验与健壮性**：看板解析走结构化 JSON（空解析哨兵 + 文本回退）、采样截断 200 行 + 列画像（枚举值防取值幻觉）、SQL 直查强制只读执行器 run_sql.py、preflight.py 一键前置检查。详见 [CHANGELOG.md](CHANGELOG.md)

## 依赖

- `guancli`（观远 BI CLI）：`guancli auth login`
- `python3`（系统自带）：运行 `references/scripts/` 下的向导脚本

## 安装

将本仓库的 `SKILL.md` 与 `references/` 放入你的 skill 加载目录（如 `~/.workbuddy/skills/guanbi-agent-builder/`）即可。

## License

[MIT](LICENSE)

> 本作品为个人开发者作品（作者：Jeremy），与观远数据（Guandata）官方无关；"观远 BI"等字样仅表示本工具面向该平台的数据看板使用。

## 迭代计划

见 [ROADMAP.md](ROADMAP.md)（跨 session 接力：当前状态快照、设计原则、规划中方向与已踩过的坑）。

## 历史

- 2026-09：曾尝试 PaySkill 收费版（v1.0.0–v3.0.1），经实测收费模式不成立，已封存于 [archive/](archive/README.md)，项目转为开源继续迭代。
