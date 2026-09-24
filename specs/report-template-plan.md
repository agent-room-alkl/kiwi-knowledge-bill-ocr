# 报告模板需求与实施方案（给 Robin 的一份）

合并来源：`specs/vikas-skill-vs-ours-analysis.md`（Claude / T-02）+ internal Codex analysis（T-01）。
两份冲突处见第 6 节，每处写了采纳谁、为什么。本文件只谈需求和怎么做，**不改代码**。

---

## 1. 附件是什么，缺哪 4 个文件

Vikas 回了两个附件。`from vikas/SKILL.md` 是一份 **Anthropic Claude Skill**（`statement-categoriser`），不是 Foundry prompt，也不是能直接跑的程序：它规定本地 agent 抽流水、先查商户缓存再上网、分类、再填 HTML。`from vikas/report-template.html` 是 AIA 品牌的贷款风险报告壳子，34 个 `{{UPPER_SNAKE}}` 占位符 + 8 组 `<!-- REPEAT -->` 注释块（注释不是模板循环，纯字符串替换生不出多行表）。Skill 还引用了 5 个文件，其中 `assets/report-template.html` 就是这份已送达的模板；**真正缺的 4 个是** `references/categories.md`（他的分类表，最关键）、`references/nz-vendors.md`、`references/vendor-cache.md`、`data/vendors.csv`。没有 `categories.md`，他的类目和我们 15 类对不上，只能猜。

目标一句话：分类之后，用**代码算出来的数**自动填进最终报告。不要让模型自己填金额。

---

## 2. 统一缺口清单

Claude 的 G1–G11 与 Codex 的 12 行 HTML 区域表去重后如下。每条只标一种归属。

| ID | 缺什么 | 归属 | 来源 |
|---|---|---|---|
| G1 | `essential` / discretionary：taxonomy 没有正式维度，模板要 `ESSENTIAL_SPLIT` 和承诺表的 `ESSENTIAL_YN` | 纯代码（15 类静态表 + `other`/现金不自动美化） | Claude G1；Codex Essential 行 |
| G2 | 交易级 `risk_flag` + 原因（赌博 / payday / dishonour / BNPL 逾期 / 现金>$500） | **一期纯代码**（dishonour/透支/滞纳费正则 + 现金>$500）；赌博/payday/BNPL **需要模型，放二期** | Claude G2；Codex Risk 行；房间已定一期范围 |
| G3 | 行级 `confidence`：schema 有，`part2[]` 没透传 | 纯代码 | Claude G3；Codex ledger 行 |
| G4 | 商户 `source` / `source_url`（cache / pattern / companies-office / nzbn / web / manual / unresolved） | 一期纯代码只标 `pattern`/`unresolved`；做成可点链接 **需要 Robin 拍板**（是否联网）；完整 cache **需要资料** | Claude G4；Codex ledger 行 |
| G5 | 账号只留后 4 位；地址 / IRD / NHI 不进报告 | 纯代码 | Claude G5；Codex header / 隐私 |
| G6 | 逐账户余额对账：`opening + Σin − Σout ≈ closing`，不平写进 exceptions，禁止改 closing | 纯代码 | Claude G6；Codex Exceptions 行 |
| G7 | 观察期原始合计（TOTAL_INCOME / TOTAL_EXPENSES / CATEGORY_TOTAL / NET）vs 现有月均等值。两套数不能混贴 | 纯代码（口径见第 5 节已定项） | Claude G7；Codex Income/Expenses/Net/Category 行 |
| G8 | HTML 渲染器：`<!-- REPEAT -->` 必须真循环；文本 HTML escape；`source_url` allowlist；生成文件不得残留 `{{...}}` 或示例行 | 纯代码 | Claude G8 + 3.11；Codex 渲染节 |
| G9 | Vikas 的 `categories.md`（以及 vendors 三件套） | 需要资料；**是否现在向 Vikas 要，需要 Robin 拍板** | Claude G9 |
| G10 | 行级 `merchant`：`part2[]` 15 个键里没有 merchant，聚合层 `part2_calculations[].merchant` 不能反推行级 ledger | 纯代码（从 joined 行透传 `collapse_merchant` 结果） | Claude G10；Codex ledger 行 |
| G11 | `needs_review` 混了 unclear / underwriter_manual / business yes|review，不能整桶塞进「待人工分类」 | 纯代码（拆三栏 / `review_type`） | Claude G11；Codex Manual 行 |
| G12 | 单值 header 对不上多账户 binder（一个 SOURCE_FILE / BANK / ACCOUNT） | 纯代码（binder 主报告改成账户列表；原单值模板只给单 statement 附录） | Codex header 行 |
| G13 | `{{SUBCATEGORY}}` 没有统一字段，只有 utility/insurance/income 子类型 | 纯代码（闭合 subtype，禁止任意字符串） | Claude 3.8；Codex ledger 行 |
| G14 | 收入 regularity、one-off/unknown 展示规则 | 纯代码（由观测次数 + frequency 派生） | Claude 3.4；Codex Income 行 |
| G15 | 分类占比的分母要写死（观察期、非 duplicate、非 info 的 household outflow；排除项是否进分母要配置并标在标签上） | 纯代码 | Codex Category percent |
| G16 | 品牌 CSS（AIA 占位色 vs Kiwi Knowledge） | **需要 Robin 拍板**（改 `:root` token 即可） | Claude Q3 |
| G17 | 无客户数据的 merchant correction registry（只存归一化 key，不写客户交易） | 纯代码，二期；与 G4 cache 一起做 | Codex 人工回路 |

**一期可开工的纯代码：G1、G2（代码部分）、G3、G5、G6、G7、G8、G10、G11、G12、G13、G14、G15。** G4 一期只做字段、不做联网。G2 模型部分、G9、G16、G17 不挡 schema / view 开工，但 G16/G9/联网要 Robin 点头才定最终报告长相。

---

## 3. `report_view` 分层 ↔ 模板 9 个区块

**统一采用 Codex 的分层**（房间已定）：现有管线是唯一算术来源。

```
extract_and_normalize
  → 模型只分类（schema 约束）
  → compute_summary（代码算数，现有 Part 1–5 / Excel 数字不变）
  → build_report_view(...)   ← 新增，纯代码，schema 约束
  → 同一份 view 同时喂：lender-assessment.xlsx  +  HTML  +  可选 CSV
```

不要让 Foundry 把分类结果字符串替换进 HTML。不要让 HTML 自己做月化。

| `report_view` 顶层块 | 填模板哪一块 | 主要缺口 |
|---|---|---|
| `meta` | 1 Header（source / bank / 掩码账号 / period / opening / closing / generated） | G5、G12 |
| `observed_cashflow` | 2 Summary 的 TOTAL_INCOME / TOTAL_EXPENSES / NET_POSITION；9 Exceptions 里的对账 | G6、G7 |
| `servicing` | 不直接对应 Vikas 卡片；喂现有 Excel Part 1 / 1.4。HTML 若只留一格收入卡片，必须写清单位，不能和 observed 混用 | G7 |
| `category_breakdown` | 3 Category breakdown（表 + 条形图） | G1、G7、G15 |
| `income_sources` | 4 Income analysis | G14 |
| `recurring_commitments` | 5 Recurring commitments | G1 |
| `risk_flags` | 2 的 RISK_FLAG_COUNT + 6 Risk flags 表 | G2 |
| `manual_review` | 7 Needs manual categorisation（按 `review_type` 分栏） | G11 |
| `ledger` | 8 Full transaction ledger | G3、G4、G10、G13 |
| `exceptions` | 9 Exceptions | G6 |

`{{ESSENTIAL_SPLIT}}` 从 `category_breakdown` 的 policy bucket 汇总，不另开一块。

---

## 4. 实施顺序（Codex 5 步 + Claude W1–W8）

Robin 点头开工之前，只做沟通（W9），不改 `function_app/`。

| 步 | Codex 步骤 | 挂上的工作项 | 依赖 | 可否并行 | 建议 owner | 建议 verifier |
|---|---|---|---|---|---|---|
| 0 | 确认口径 / 范围 / essential 规则 / risk 一期范围 | 第 5 节已定项写入本文件即可；W9 向 Vikas 要 4 个文件 | Robin 拍 Q3/Q4/要文件/开工 | 与代码无关，可马上发邮件 | Robin（沟通） | — |
| 1 | 先写 `report-view.schema.json` + fixture 期望；**先不改模板** | 新工作：view schema（Claude 原稿没有这一层） | 步 0 的已定口径 | 单独先做 | Codex | Claude |
| 2a | 扩展 view builder / `compute_summary` 透传 | W1 essential 表；W3 confidence；W5 掩码；W6 对账；W7 观察期合计；G10 行级 merchant；G11 review_type；G13 subtype；G14 regularity；G15 分母 | 步 1 schema | **这些小项彼此可并行**，合并进同一个 view PR 或拆 2–3 个 PR | Cursor Grok 4.6（W1/W5/W6/W7）；Codex（G10/G11/透传） | 对方互验 |
| 2b | 交易级 risk（代码能坐实的） | W2 一期：dishonour/透支/滞纳费 + 现金>$500。schema 加可选 enum 和 prompt **放二期** | 步 1；不挡 2a | 可与 2a 并行 | Claude | Cursor Grok 4.6 |
| 2c | 商户 provenance 一期 | W4 一期：字段 + `pattern`/`unresolved`。cache / 联网不做 | 步 1；Robin Q4 未定时不要做链接 | 可与 2a 并行 | Claude | Codex |
| 3 | 真 HTML 渲染器 + 把 Vikas 模板改成可循环；保留现有 Excel | W8；G8 escape/allowlist；G12 binder header | 步 2a 至少就绪（W1/W3/W5/W6/W7/G10/G11） | 不可抢跑 | Cursor Grok 4.6 | Codex |
| 4 | 回归测试 + 部署 + OpenAPI `format: xlsx\|html\|both` 或独立 HTML 路由 | 硬验收见下 | 步 3 | — | Codex | Claude |

二期（不在开工第一批）：W2 模型部分、W4 cache + 人工回路（G17）、逐 statement HTML 附录。

---

## 5. 口径决定表

### 已定（房间 + 两份文档对齐后锁定）

| # | 决定 | 依据 |
|---|---|---|
| D1 | 主报告按 **整个 binder 合并**；逐 statement HTML 只做可选附录 | Claude Q1；Codex 口径 1；Moderator 已定 |
| D2 | 报告类目用 **我们的 15 类**（+ 排除项 / 收入 / business_receipts / unclear）。他的 Other/Uncategorised ≡ `unclear` | Claude Q2；Moderator 已定。换他的类会让 HTML 和 xlsx 对不上 |
| D3 | `risk_flag` **一期只做代码能坐实的**（退票/透支/滞纳费、单笔现金>$500）。赌博/payday/BNPL 二期再动 schema+prompt | Claude Q5；Codex 口径 7；Moderator 已定 |
| D4 | `needs_review` **拆三栏**：unclear / underwriter_manual / business review，禁止整桶映射到「待人工分类」 | Codex 先指出；Claude 收为 G11 |
| D5 | ledger 的 merchant **从 joined 行透传**，禁止用 `part2_calculations[].merchant` 反推 | Codex；Claude G10 |
| D6 | 渲染必须 **HTML escape + source URL allowlist** | Codex 增量；Claude 3.11 已并入 |
| D7 | `Total income` / `Total expenses` / `Net position` 用 **观察期原始 inflow/outflow**；Part 1 月均是另一套数，标签必须写清。Net 不能用「月收入 − 月生活费」冒充流水净变动 | Codex 口径 2–4（见第 6 节冲突 4） |
| D8 | 模型不算总数、不填 HTML 数字。`report_view` 是 Excel 和 HTML 的唯一共同数据源 | 两份独立结论；房间已定 |

### 待 Robin 拍板

| # | 问题 | 建议 |
|---|---|---|
| Q3 | 品牌：AIA（模板现状，颜色还是占位值）还是换成 Kiwi Knowledge？ | 改 `:root` token 即可，但要你定给谁看 |
| Q4 | 是否允许联网查商户（Companies Office / NZBN，只发 merchant token）？ | 建议一期离线，只标 `pattern`/`unresolved`。联网决定 G4 能不能出可点链接 |
| Q9 | 要不要现在向 Vikas 要那 4 个缺件（尤其 `categories.md`）？ | 建议要。没有它无法核对他心里的类目，但不挡我们用 15 类先做 view |
| Q0 | **是否开工**（按第 4 节派 W1–W8）？ | 分析阶段按你的原话停在文档。你点头再改 `function_app/` |

---

## 6. 两份源文档的冲突（显式取舍，不静默）

| # | 冲突 | 采纳 | 理由 |
|---|---|---|---|
| C1 | Skill 类型：Codex 写「Codex/Agent Skill」；Claude 写「Anthropic Claude Skill」 | **Claude** | frontmatter 的 `name` / `description` / `argument-hint` 是 Claude Skill 规范。用途描述 Codex 没错，出处标签不准（Claude 验 T-01 已记） |
| C2 | 架构：Claude 方案 B = `render_html` 直接吃 `compute_summary` JSON；Codex = 中间加 `report_view`，Excel/HTML 都吃 view | **Codex** | 房间已定。多一层才能保证两份报告数字不漂，也方便 binder vs statement 两个 scope |
| C3 | 缺件个数：Claude 原稿列 5 个引用（含已送达的 `assets/report-template.html`）；实际没发来的是 4 个 | **引用 5、缺 4** | 避免把已有模板再当成缺口 |
| C4 | `TOTAL_INCOME` 卡片：Claude 写成「period 合计即可」；Codex 要求同时保留「观察期流入」和「验证月收入」，模板只有一格 | **Codex** | 混用会把 servicing 月收入标成 statement total。view 出两个字段；HTML 要么改两张卡，要么一张卡写死单位 |
| C5 | 人工区 / ledger vendor：Claude 原稿 3.7、3.8 标成已有；Codex 指出 `needs_review` 混了 business、`part2` 没有 merchant | **Codex**（Claude 已收为 G10/G11） | 已打开 `compute_summary.py:1189-1206` 和 `:1203-1204` 核对 |
| C6 | 实施顺序：Claude 先并行小改再 W8 渲染；Codex 先 schema+fixture，再扩 summary，最后渲染 | **Codex 的 5 步，W1–W8 挂上去**（第 4 节） | 先锁 schema，fixture 才能当验收，避免渲染器一边写一边改口径 |
| C7 | W4 时机：Claude 把 cache 放二期；Codex 一期就要 provenance 字段 | **拆开**：一期字段 + `pattern`/`unresolved`；cache/联网等 Q4 | 字段不依赖联网；链接和 cache 依赖 Robin |

---

## 7. 硬验收（开工后用，现在先记下）

- 每一笔非 info、非 duplicate 交易在 ledger 恰好一次。
- 观察期 inflow / outflow / net 与 canonical 独立重算一致。
- 各类 raw total 之和 = 写死的 expense 分母；百分比用同一分母。
- 月均等值与现有 `compute_summary` 完全一致；HTML 不自行月化。
- unclear / underwriter_manual / business review 分栏，无静默丢弃。
- 账户对账通过或列出差额；不得改 closing。
- 生成 HTML 无残留 `{{...}}`、无 REPEAT 示例行、无未转义客户文本、无未掩码账号。
- Excel 与 HTML 同名指标逐项相等。
- 原有 compute/render 测试继续通过。

---

Robin 读到这里即可拍第 5 节四个问题。两份源文档留作附录，不必再通读。
