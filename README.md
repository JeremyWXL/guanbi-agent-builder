# guanbi-agent-builder

Data Agent 搭建向导：把熟悉的观远 BI 看板变成 AI data agent 的引导式 skill。

本 skill 以对话方式引导**不懂技术的业务用户**一步步搭建自己的 data agent——以观远 BI 仪表板为数据来源，覆盖问数查询、指标归因、异常识别、综合洞察四类场景，参照观远官方 Dashboard Agent 的配置结构（pages / learningResult / businessKnowledge / insightThinking / outputFormat）自动生成配置，关键环节由用户确认纠偏。

## 特性

- **八步向导**：选定数据范围 → 看板资产学习 → 业务认知补充 → 口径确认 → 场景确认 → 配置生成 → 测试验收 → 固化交付
- **行业认知预研 + 历史报告提炼**（v2.0 起）：解决"裸看板搭建、缺业务输入"的核心短板
- **自动校验**：生成的卡片/页面配置带校验脚本，减少手工排错
- **勾选式看板选择**（v2.2 起）：自动列出用户有权限的仪表板供点击勾选/编号勾选，候选看板带 BI 链接可点开核对，确认前生成核对页（含适检结论），所有确认点提供"就这样/改某条/跳过"结构化出口
- **校验工作台**（v2.3 起）：资产目录/业务口径/分析思路变成浏览器里可查看、可直接编辑的本地页面，保存自动备份；交付包内含只读工作台 workbench.html
- **资产体检与多 agent 总览**（v2.4 起）：看板学习时点与当前更新时间对比，看板改版自动提醒重新学习；`--agents` 生成多 agent 管理总览页（业务头像 + 独立卡片 + 逐个体检）；工作台内看板一键跳转 BI 平台
- **健壮性强化**（v2.5 起）：看板解析改走结构化 JSON（带空解析哨兵与文本回退）、采样默认截断 200 行并输出列画像（枚举值防取值幻觉）、SQL 直查强制走只读执行器 run_sql.py、前置检查 preflight.py 一键确认环境。详见 [CHANGELOG.md](CHANGELOG.md)

## 依赖

- `guancli`（观远 BI CLI）：`guancli auth login`
- `python3`（系统自带）：运行 `references/scripts/` 下的向导脚本

## 安装

将本仓库的 `SKILL.md` 与 `references/` 放入你的 skill 加载目录（如 `~/.workbuddy/skills/guanbi-agent-builder/`）即可。

## License

[MIT](LICENSE)

> 本作品为个人开发者作品（作者：Jeremy），与观远数据（Guandata）官方无关；"观远 BI"等字样仅表示本工具面向该平台的数据看板使用。

## 迭代计划

见 [ROADMAP.md](ROADMAP.md)（跨 session 接力：当前状态、v3.0 质量护城河计划、设计原则与已踩过的坑）。

## 历史

- 2026-09：曾尝试 PaySkill 收费版（v1.0.0–v3.0.1），经实测收费模式不成立，已封存于 [archive/](archive/README.md)，项目转为开源继续迭代。
