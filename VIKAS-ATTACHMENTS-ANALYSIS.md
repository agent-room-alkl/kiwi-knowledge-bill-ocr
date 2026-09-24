# Vikas 附件分析与模板自动填充方案

## 结论

`from vikas/SKILL.md` 是一份“如何处理新西兰银行流水”的 Codex/Agent Skill 说明，不是可直接运行的程序。`from vikas/report-template.html` 是它要求生成的 HTML 报告骨架，也不是 Excel 模板。两者表达的目标确实是：先抽取并分类交易，再用计算结果自动生成完整报告。

这两个附件不能原样直接接入当前项目：Skill 引用了 `references/categories.md`、`references/nz-vendors.md`、`references/vendor-cache.md`、`data/vendors.csv` 和 `assets/report-template.html`，但邮件附件目录里只有 `SKILL.md` 和 `report-template.html`。模板还使用了 34 个占位符和 8 个“REPEAT”注释块；这些重复块只是说明，不是 Jinja/Handlebars 等模板语法，因此仅做字符串替换无法生成多行表格。

当前项目已经有更可靠的核心链路：

`extract_and_normalize -> 模型分类 -> compute_summary（代码计算） -> render_report（Excel）`

建议保留这条链路作为唯一计算来源，在 `compute_summary` 之后新增一个报告视图层，再由同一份视图数据同时生成现有 Excel 和新的 HTML。不要把金额合计、月化或风险计数重新交给 Skill/模型计算。

## 两套方案的定位差异

| 方面 | Vikas 附件 | 当前项目 | 判断 |
|---|---|---|---|
| 主要目标 | 单份 statement 的交易分类、商户识别和可读 HTML | 多文件 binder 的贷款/信用 servicing assessment | 当前项目更接近最终审批用途 |
| 输出 | 每个源文件一份 HTML + CSV | binder 级 lender-assessment.xlsx | 建议 binder 主报告 + 可选逐 statement 附录 |
| 算术责任 | Skill 步骤中由执行 Agent 汇总 | `compute_summary.py` 统一计算，模型禁止算总数 | 保留当前设计，审计性更强 |
| 分类体系 | 引用缺失的 `categories.md`；概念包括 essential、risk flag、subcategory | 已有闭合的 NZ lender taxonomy、排除项、收入、business 标记 | 以当前 taxonomy 为主，新增明确映射 |
| 商户识别 | 本地 vendor cache 优先，未知商户才查网络，并记录来源 URL | 模型分类 + `collapse_merchant`，没有可审计 vendor cache/URL | 可吸收其 cache 和 provenance 思路 |
| 人工修正学习 | 人工分类后更新 `vendors.csv` 并重做报告 | 暂无持久化 merchant correction registry | 值得作为后续功能，但不能把客户交易写入 cache |
| 隐私 | 明确遮蔽账号；网络只查 merchant token | Azure Document Intelligence/Storage 管线；报告目前使用 account label | 必须明确现有 Azure 数据边界，并在报告视图统一遮蔽账号 |
| 风险提示 | 交易级 gambling、payday lending、dishonour、BNPL arrears、大额现金 | 账户 conduct、evidence gaps、unclear/business review | 需要新增确定性的交易级风险规则，而不是从现有 conduct 数字硬映射 |
| 报告深度 | summary、分类、income、commitments、risk、manual review、全量 ledger | applicant、accounts、income、Part 1-5、liabilities、evidence gaps | 两者互补；HTML 不能取代当前 lender pack |

## Vikas HTML 模板实际需要什么

模板包含以下数据区。映射状态按当前 `compute_summary` 返回结构判断。

| HTML 区域 | 建议数据来源 | 当前可用性 | 必须先解决的问题 |
|---|---|---|---|
| Source file / Bank / Period / Opening / Closing | `accounts[]` | 大部分已有 | 一个 binder 有多个账户和文件，单值占位符不够；账号必须遮蔽 |
| Total income | `income[]` 或原始 inflow | 部分已有 | 必须定义是“观察期总流入”还是“验证月收入”；两者不能混用 |
| Total expenses | `part2[]` 原始 outflow 或 Part 1 月化 | 部分已有 | 必须定义是观察期总支出、全部 debits，还是 recommended monthly living |
| Net position | 同口径 income - expenses | 可计算但未返回 | 只能使用同期间、同口径的数据 |
| Essential vs discretionary | category policy + summary | 缺失 | 当前 taxonomy 没有正式 essential/discretionary 维度，需版本化映射和 underwriter 确认 |
| Risk flag count + rows | 新的 deterministic risk engine | 缺失 | `account_conduct` 不能替代交易级 risk rows |
| Category total / monthly average / percent | `part2[]` + observation months | 部分已有 | 当前 Part 1 是月化值，模板还要观察期 raw total 和百分比分母 |
| Income source / cadence / average / regularity | `income[]`、`part2_calculations[]` | 大部分已有 | 需明确 one-off/unknown 的展示规则和 regularity 字段 |
| Recurring commitments | `part2_calculations[]` | 大部分已有 | 需增加 essential 标记；仅包含真实 recurring，不把 one-off 当 commitment |
| Manual categorisation | `part2[].needs_review` | 部分已有 | 当前 `needs_review` 还包含 business yes/review；必须把 `unclear`、`underwriter_manual`、business review 分开展示 |
| Full ledger | `part2[]` | 不足 | `part2` 目前不输出 merchant、classification confidence、subcategory、vendor source/source_url |
| Exceptions | extraction errors、reconciliation、evidence gaps | 部分已有 | 需把 extraction errors 和逐账户余额 reconciliation 作为结构化结果返回 |

## 关键口径决定

实现前需要把以下定义写进 schema 和测试，不能由模板或模型临时决定：

1. 报告范围：主报告按整个 binder 汇总；逐 statement 报告只作为可选附录。贷款 servicing 需要跨账户去重、识别内部转账，并使用统一 observation window。
2. `Total income`：建议显示“观察期流入总额”和“可用于 servicing 的验证月收入”两个不同指标。现有模板只有一个卡片，必须改模板或选定其中一个并写清单位。
3. `Total expenses`：建议同时区分“观察期全部 outflows”和“recommended monthly living”。不能把 Part 1 月化金额标成 statement total。
4. `Net position`：只能用观察期原始 inflow - outflow；不应用月收入减月化 living 后冒充 statement cash movement。
5. Category percent：建议分母为观察期、非 duplicate、非 info 的 household outflows；排除内部转账、债务还款、income、business、one-off 是否进入分母要显式配置并在标签中写明。
6. Essential/discretionary：建立 `category_policy.json`，逐 category 标记 `essential`、`discretionary`、`savings_giving`、`excluded`、`manual`。有歧义的 `other` 和现金提款不应自动美化成 discretionary。
7. Risk flags：规则引擎只做可证实规则，例如已分类 gambling、payday/high-cost lending、dishonour fee、BNPL arrears、单笔现金提款大于阈值。模型推断只能进入 `review`，不能直接变成事实。
8. 账号与个人信息：HTML 中账号统一只保留后四位；地址、IRD/NHI 不输出；模板渲染必须 HTML escape，来源 URL 必须 allowlist/校验。

## 推荐的数据与渲染架构

### 1. 新增稳定的报告视图模型

在 `compute_summary` 后新增纯代码函数，例如：

`build_report_view(canonical, classifications, summary, scope="binder") -> report_view`

建议输出这些顶层块：

- `meta`: scope、source files、banks、masked accounts、period、opening/closing balances、generated date
- `observed_cashflow`: raw inflows、raw outflows、net movement、reconciliation status
- `servicing`: assessable monthly income、recommended monthly living、savings/giving、business expenses、one-offs
- `category_breakdown`: raw total、monthly equivalent、percent、policy bucket
- `income_sources`: source、dominant amount、cadence、monthly equivalent、regularity、evidence
- `recurring_commitments`: merchant、category、dominant amount、cadence、monthly impact、essential
- `risk_flags`: transaction id、date、description、amount、rule id、reason、severity
- `manual_review`: review type、transaction id、reason、model confidence
- `ledger`: 完整展示字段和 vendor provenance
- `exceptions`: extraction、join、reconciliation、missing evidence、unresolved vendor

该 view 必须由代码计算，模型只能提供分类、reason、merchant hint、business judgement 等受 schema 约束的输入。

### 2. 补齐当前 schema/summary 字段

当前 `compute_summary` 在 join 时没有把这些分类字段传到最终 `part2`：`confidence`、展示用 `merchant`、可选 `subcategory`、vendor identification `source` 和 `source_url`。建议：

- 分类 schema 增加 `subcategory` 或建立 category-specific subtype；不能让任意字符串破坏闭合 taxonomy。
- 把 `confidence` 保留到 joined row 和 report view。
- 明确区分 `source_file`（交易来自哪个文件）与 `vendor_source`（商户识别证据来自哪里）。
- 为 merchant correction 建立独立、无客户数据的 registry；只存 normalized key、vendor、category hint、来源、更新时间。
- 新增逐账户 `reconciliation`：opening + inflow - outflow 与 closing 的差额、容差、状态和异常原因。

### 3. 把 HTML 改成真实模板

当前 HTML 中的 `<!-- REPEAT -->` 只是人工说明。建议改为真正的模板循环，或让 renderer 明确构造每个表格区块。渲染器应：

- 对所有文本做 HTML escape；只对通过校验的 source URL 生成链接。
- 对金额、日期、百分比用统一 formatter，不在模板里做业务计算。
- 遇到未提供的必填字段时生成清楚的 `Not provided in binder` 或 exception，不能残留 `{{PLACEHOLDER}}`。
- binder 模式把单值 header 改成账户/文件列表；如果坚持原模板，则只用于单 statement 附录。
- 同一 `report_view` 同时供 HTML 和 Excel renderer 使用，防止两份报告数字漂移。

### 4. 保留并扩展现有输出

推荐最终交付为：

1. `lender-assessment.xlsx`：正式 underwriter 工作底稿，保留现有 applicant、income、Part 1-5、liabilities 和 evidence gaps。
2. `lender-assessment.html`：人类可读摘要与完整 ledger，吸收 Vikas 模板的分类图表、risk、manual review、source provenance。
3. 可选 `transactions.csv`：机器可读明细；字段由 schema 固定，不能从 HTML 反解析。

## 实施顺序

1. 先确认上面的金额口径、binder/statement 范围、essential mapping 和 risk rules。
2. 定义 `report-view.schema.json`，写 fixture 预期结果；先不改模板。
3. 扩展 `compute_summary`/view builder，补 merchant、confidence、provenance、raw totals、reconciliation、risk flags。
4. 写真实 HTML renderer，并将 Vikas 模板转换为可循环模板；保留现有 Excel renderer。
5. 增加回归测试后部署 Azure Functions，并在 OpenAPI 增加 `format: xlsx|html|both` 或单独的 HTML render route。

## 验收标准

- 每一笔非 info、非 duplicate 交易都在 ledger 中恰好出现一次。
- 观察期 inflow、outflow、net 与 canonical transactions 独立重算一致。
- 每个 category raw total 之和与定义好的 expense denominator 一致；百分比按同一分母计算。
- monthly equivalent 与现有 `compute_summary` 完全一致；HTML 不自行月化。
- 每个 summary 卡片可追溯到 report view 的结构化字段和源交易。
- 所有 unclear、underwriter_manual、business review 分栏展示，无静默丢弃。
- 账户 reconciliation 通过或明确列出差额；不得静默调整 closing balance。
- 生成 HTML 中没有残留 `{{...}}` 或 REPEAT 示例行，没有未转义的客户文本，没有未遮蔽账号。
- Excel 与 HTML 的共同指标逐项一致。
- 原有 compute/render 测试继续通过，并增加多账户、内部转账、重复行、低置信度、风险规则和恶意 HTML 文本 fixture。

## 最终判断

Vikas 的附件最有价值的是“报告体验、vendor cache/provenance、manual correction loop 和交易级 risk/manual review”的产品思路；当前项目最有价值的是“binder 级 lender taxonomy、代码负责算术、服务端保存 batch/summary、防止上下文截断、evidence gaps 和 Excel underwriter pack”的工程基础。

正确合并方式不是用 Vikas Skill 替换现有 prompt，也不是让 Foundry 直接把分类结果字符串替换进 HTML。应当把当前管线作为唯一事实来源，补一个经过 schema 约束的 report view，再渲染两种输出。这样才真正实现“交易记录 -> 分类 -> 可审计算法 -> 自动填入最终模板”。
