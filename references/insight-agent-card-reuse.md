# 洞察Agent 看板重建：卡片级复用与重建指引

> 适用：诊断报告给出“拆分 / 合并 / 新建页 / 改造页”后，需要把原看板中**符合洞察Agent 要求、用户已经看惯的卡片**保留到新看板。
>
> 原则：**不整页另存**。原页面通常带大量冗余卡片/数据，整页复制会把冗余一起带过去；只挑真正有价值的卡片，在新工程里用 `createCard()` 重建，保持图表类型、字段、聚合、格式、筛选和描述不变。

---

## 0. 当前工具能力（guanvis 0.1.50）

| 能力 | 是否支持 | 说明 |
|---|---|---|
| 单张卡片另存为 | ❌ 没有 `card save-as` | `guanvis card` 只有 `set-description` |
| 整页另存为 | ✅ `guanvis page save-as` | 服务端整页复制，会连冗余卡片一起复制；**本指引不作为默认方案** |
| checkout 源页 | ✅ `guanvis checkout <pgId>` | 只读拉取源页与卡片定义；用于读配置，不用于复制新页 |
| checkout 的 card JS | ⚠️ `attachCard(cdId, ".guanvis/base/cards/<cdId>.json")` | 不是完整图表 DSL，依赖源工程 base/manifest；**不能直接搬到 `guanvis init` 新工程** |
| 新工程重建 | ✅ `guanvis init <dsId>` + `createCard()` + `guanvis genid` | 本指引的主路径；按源卡配置重写 DSL |

**结论**：源卡配置从 `.guanvis/base/cards/<cdId>.json` 与 `cards-raw.json` 读取，在新工程用 `createCard()` 重建；不要复制 `attachCard` 的 card JS，也不要把 `attachCard` 直接改写成 `createCard` 后不经核对就发布。

---

## 1. 主流程：卡片级筛选 + 重建

### 1.1 选卡

从诊断报告或 `insight-audit.json` 中挑出要保留的卡片，判断标准见第 2 节。只保留能服务目标业务问题、口径清晰、结构可控的卡片；其余删除或留在原页。

### 1.2 拉源卡配置（只读）

```bash
guanvis checkout <源pgId> -d ./src
```

读两类文件：

- `./src/.guanvis/base/cards/<cdId>.json`：源卡的完整 JSON（字段、图表配置、格式、筛选、描述等）。
- `<工作目录>/cards-raw.json`：审计时已解析的卡片结构（dims/measures/formula/filterDetails/dynamicParams），用于快速看字段与口径。

> checkout 生成的 `card_*.js` 只是 `attachCard` 引用，不要直接复制到目标工程；它离开源工程会找不到 base-card/manifest。

### 1.3 抽取卡片骨架

用本 Skill 的抽取器，把选中的源卡转成 `createCard()` 骨架：

```bash
python3 references/scripts/extract_card_skeletons.py <工作目录> \
  --cdIds <cdId1,cdId2,...> \
  -o ./card-reuse
```

产出：

- `card-reuse/card-reuse.json`：选中卡的结构、数据集、维度、度量、公式、筛选、需人工确认项。
- `card-reuse/card-skeletons/card_XX_<cdId>.js`：每张卡的 `createCard()` 骨架。
- `card-reuse/card-reuse-checklist.md`：重建步骤、每张卡的人工核对清单。

### 1.4 建目标工程并重建

```bash
# 目标数据集（新看板要用的数据集；可多个）
guanvis init <目标dsId> -d ./dst

# 把骨架复制进目标工程，按 TODO 补齐：
# - 计算字段/公式（骨架会列出原公式，不会伪造）
# - 图表格式、排序、图例、标签、颜色、对比指标
# - 卡片描述、单位、精度
cp card-reuse/card-skeletons/*.js ./dst/

# 新资源 ID（按需）
guanvis genid
```

每张骨架的形态：

```javascript
// 源：<源看板名> / <卡名> (<cdId>)
// 原图表类型：PIE；数据集：<dsId>
// 需人工确认：格式/排序/图例/标签/筛选器联动；计算字段见下方 TODO
var card = createCard(ChartType.PIE, "商品杯型占比")
    .setId("c7f3a9b2d4e64718a9c1f0b3")  // 必须是新 ID，不能复用源 cdId；可用 guanvis genid 替换
    .bindDataset(DS)
    .addRow(f("杯型名称"))
    .addMetric(f("销售杯数", { aggrType: AggrType.SUM }))
    .setDescription("从原看板复用：商品杯型占比");
registerCard(card.build());
```

> 目标 `dsId` 必须与源卡一致，或目标数据集暴露同名字段。`guanvis init` 显示 0 fields 时，先用有数据集权限的账号重试；否则 `f("字段")` 会报 field not found。

### 1.5 组装新页面

在 `./dst/page.js` 里只放选中的卡片，按诊断建议的层级/顺序布局；不要把所有卡片都放进去。

### 1.6 验证与发布

```bash
guanvis preview ./dst
guanvis diff ./dst
guanvis publish ./dst --dry-run
guanvis publish ./dst
```

发布前必须确认：

- 目标页是新页，不是覆盖原页。
- 只包含选中的卡片，冗余卡没有带过去。
- 卡片数在洞察Agent 可承受范围（建议 ≤12，最多不超过 20）。
- 每张卡与源卡对照：图表类型、字段、聚合、格式、筛选、描述、数值。
- 页面筛选栏有洞察Agent 可选的联动筛选器（R-02）。

---

## 2. 哪些卡片值得保留

优先保留：

- 目标业务问题的核心指标/主视图，用户日常必看。
- 指标已在 BI/数据集层算好，口径清晰，无同名冲突。
- 卡名可被 Agent 理解，不含“副本/测试/临时/固定年月”。
- 有明确时间范围/筛选条件，页面有联动筛选器承接。
- 图表类型适合该问题（趋势/对比/结构/明细），不是装饰性图表。
- 数据量可控，不是超大明细表。
- 用户依赖其格式/颜色/排序/描述（看数习惯）。

优先删除或重建：

- 与目标问题无关的装饰卡、重复卡、测试/副本卡。
- 同名多口径、口径冲突、来源不明的卡。
- 固定期间、无法参数化的快照卡。
- 明细行数超大、会撑爆上下文的表。
- 卡名不可理解、Agent 无法路由的卡。
- 需要改数据集/改口径/改图表的卡（保留原卡反而误导）。

---

## 3. 迁移方案怎么写进报告

诊断报告的 `cardReuse` 按目标页逐条写，方法只有两种：

```json
{
  "sourcePgId": "源看板 pgId",
  "target": "NEW 或目标 pgId",
  "targetName": "新看板名（target=NEW 时必填）",
  "method": "rebuild 或 keep",
  "keepCards": ["留在原页/不迁移的卡片"],
  "dropCards": ["删除的卡片"],
  "rebuildCards": ["在新页重建的卡片"],
  "reason": "为什么这样选，必须引用体检发现",
  "commands": ["建议执行的 guanvis 命令（可选）"]
}
```

- `rebuild`：在新工程用 `createCard()` 重建 `rebuildCards`；必须写清哪些卡、为什么值得保留。
- `keep`：卡片留在原页，新页通过跨页联动使用；不复制，避免冗余。
- 不写 `page_save_as`：整页另存会把冗余卡片一起带过去，不作为默认方案；除非用户明确要求整页复制。
- 不能只写“复用原卡片”，必须落到具体卡片和命令。
- 诊断阶段只读，不自动发布；发布是实施动作，必须用户确认后执行。

---

## 4. 上线前验收清单

- [ ] 目标页是新页，原页未被覆盖。
- [ ] 新页只包含选中的卡片；冗余卡没有带过去。
- [ ] 每张重建卡的图表类型、字段、聚合、格式、排序、描述与源卡一致。
- [ ] 计算字段/公式按源卡重建，结果与源卡一致。
- [ ] 页面筛选栏有洞察Agent 可选的联动筛选器（R-02）。
- [ ] 单页数据卡数量在阈值内（建议 ≤12，最多不超过 20）。
- [ ] 明细表行数已采样确认，未超 1 万行。
- [ ] 同名指标口径一致；跨页共享维度字段名一致。
- [ ] `guanvis preview` / `diff` / `publish --dry-run` 无阻断。
- [ ] 发布后抽查 3 张卡的数值与源卡一致。
- [ ] 用户确认“看数习惯没有被打断”。

---

## 5. 常见错误

| 错误 | 后果 | 正确做法 |
|---|---|---|
| 直接复制 checkout 的 `card_*.js` 到 `guanvis init` 新工程 | `attachCard` 找不到 base/manifest，发布失败或卡片不完整 | 用 `extract_card_skeletons.py` 生成 `createCard()` 骨架 |
| 把 `attachCard` 改写成 `createCard` 后直接发布 | 未表达的线上配置丢失，卡片外观/格式变了 | 逐项对照源卡；只用于少量卡片；先 preview/diff |
| 用整页 `save-as` 复制 | 冗余卡片/数据一起带过去，上下文爆 | 只挑卡片重建；整页复制仅用户明确要求时用 |
| 复制后不删冗余卡 | 新页仍然 40+ 卡，洞察Agent 上下文爆 | 只保留目标问题需要的卡片 |
| 用没有完整列权限的账号 checkout | 字段被裁剪，重建后缺列 | 用资源 owner/管理员账号 |
| 发布前不看 diff/dry-run | 联动/布局被改坏 | `preview` → `diff` → `publish --dry-run` → `publish` |

---

## 6. 与诊断报告的关系

- 诊断阶段（A1–A4）只读：给出 `cardReuse` 方案与重建清单，不执行发布。
- 实施阶段（用户确认后）：按方案执行 `checkout` / `init` / `extract_card_skeletons.py` / `createCard` / `preview` / `publish`，每一步先 dry-run。
- 报告只写“建议怎么复用”，不把“已复用”写成既成事实。
