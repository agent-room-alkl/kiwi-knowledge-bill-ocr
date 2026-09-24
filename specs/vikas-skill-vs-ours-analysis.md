# Vikas 附件分析：他的 Skill / 模板 vs 我们的方案，以及「分类结果自动填模板」怎么做

分析对象：`from vikas/SKILL.md`、`from vikas/report-template.html`
对照对象：本仓库 `foundry/`（Foundry agent 指令）+ `function_app/`（extract_and_normalize / compute_summary / render_report）+ `schemas/` + `templates/`
分支：`integration-deployed`，HEAD `9f2d008`
本文档只做分析，不改任何代码。

---

## 1. 两个附件分别是什么

### 1.1 `SKILL.md` —— 一个 Anthropic **Claude Skill**（不是 Foundry prompt）

判定依据：文件头是 Skill 的 YAML frontmatter：

```yaml
name: statement-categoriser
description: 'Use when analysing New Zealand bank statements for loan/credit risk assessment...'
argument-hint: '<path to statement file or folder> [optional: applicant reference]'
```

`name` / `description` / `argument-hint` 是 Claude Skill 的标准字段，`description` 里塞满触发关键词（bank statement, ANZ, ASB, BNZ, Westpac, Kiwibank…）——这是给 skill 路由用的，不是给模型做分类用的。

它描述的是一条**本地文件工作流**，7 步：

| 步骤 | 内容 |
|---|---|
| Step 1 | 接收 pdf/png/jpg/webp/html，按文件清点；**一个源文件一份报告** |
| Step 2 | 抽取交易 → `date, narrative_raw, particulars, code, reference, debit, credit, balance, source_page`；要求 `opening + Σcredit − Σdebit ≈ closing` 对账 |
| Step 3 | **商户识别：本地 CSV 缓存优先 → 已知模式文件 → 最后才上网**（Companies Office / NZBN）；每行必须带 `source` 和 `source_url` 溯源 |
| Step 4 | 按固定 taxonomy 分类；不确定就 `Other / Uncategorised`，并进「待人工分类」区；另外打 `recurring` / `essential` / `risk_flag` |
| Step 5 | 新解析出的商户回写 `data/vendors.csv`（缓存自我成长） |
| Step 6 | 用 `assets/report-template.html` 生成 HTML 报告 + `transactions.csv` |
| Step 7 | **人工补分类 → 写回缓存 → 重新生成报告**（闭环学习） |

它还引用了 5 个**没发给我们**的文件：

- `references/categories.md` —— 他的分类 taxonomy（**这是最关键的缺件**）
- `references/nz-vendors.md` —— NZ 商户 narrative 模式库
- `references/vendor-cache.md` —— vendors.csv 的 schema 和归一化规则
- `data/vendors.csv` —— 商户缓存种子数据
- `assets/report-template.html` —— 就是发给我们的那个模板

没有 `categories.md`，任何「他的分类 → 我们的分类」的映射都只能靠猜。**这是要向 Vikas 索要的第一件东西。**

### 1.2 `report-template.html` —— 报告模板（AIA 品牌），纯前端、可离线打开

结构：

- `:root` 里一组 `--brand-*` CSS token，注释明说是占位色，接真 AIA 品牌色时只改这一段
- 占位符两种语法：
  - `{{UPPER_SNAKE}}` 单值替换（如 `{{TOTAL_INCOME}}`）
  - `<!-- REPEAT: ... -->` / `<!-- END REPEAT -->` 包住的行模板，按数据条数复制
- 9 个固定区块，顺序是写死的：Header → Summary cards → Category breakdown（表 + 纯 CSS 条形图）→ Income analysis → Recurring commitments → Risk flags → Needs manual categorisation → Full transaction ledger（带内联 JS 排序）→ Exceptions
- 没有任何外部依赖（无 CDN、无 chart 库），`file://` 双击即可打开——这是刻意的

**注意：它跟我们的 `templates/lender-assessment.md` 不是同一套东西。** 我们的是 `{{mustache}}` + `{{#section}}` 循环的 Markdown，产出走 `.xlsx`；他的是 HTML。两者的**字段集合也不一样**（见第 3 节）。

---

## 2. 逐维度差异对照

| 维度 | Vikas 的 skill | 我们的方案 |
|---|---|---|
| **定位** | 贷款风险**分类 + 可读报告** | NZ 房贷 **servicing 评估**（Part 1–5 放款包） |
| **运行形态** | Claude Skill，跑在本地 agent 工作区，直接读写文件 | Azure Functions 三个 HTTP 工具 + Foundry agent 挂工具 |
| **抽取方式** | 图片/扫描件让模型**看图转写**；PDF 有文本层用 pdfplumber；HTML 解 DOM | Document Intelligence `prebuilt-layout` → canonical rows，**确定性，不靠模型看图** |
| **谁做算术** | **模型做**（总额、月均、recurring 判定都在 agent 里） | **只有代码做**（`compute_summary.py`），模型只打标签。这是我们的核心设计约束 |
| **分类体系** | 家庭风险类（groceries/transport/gambling/…）+ `Other/Uncategorised`；定义在未提供的 `categories.md` | 封闭 enum：15 生活开支 + 8 排除项 + 6 收入 + `business_receipts` + `underwriter_manual` + `unclear`，由 `classification.schema.json` 校验 |
| **商户识别** | **三级：本地 CSV 缓存 → 模式库 → 联网（Companies Office / NZBN）**，缓存会自我成长 | 只有正则归一化 `merchant_normalized`，**无持久缓存、无联网、无溯源** |
| **溯源** | 每行带 `source`（cache/pattern/companies-office/nzbn/web:domain/manual/unresolved）+ `source_url`，报告里渲染成可点链接 | **完全没有这个概念** |
| **风险信号** | `risk_flag`：赌博、发薪日/高息贷、退票/透支费、BNPL 逾期、单笔取现 > $500 | 有 conduct 计数、排除项、一次性支出、business flag；**没有 risk_flag / 赌博 / 取现阈值** |
| **essential 区分** | 每笔有 `essential` 布尔，报告里出 essential vs discretionary 占比 | **没有**（taxonomy 里没有 essential 标记） |
| **人工回路** | Step 7 闭环：人补分类 → 写 vendors.csv → 重新生成报告，下次自动命中 | `unclear` / `underwriter_manual` 交给 underwriter，**没有回写学习** |
| **对账** | 强制 `opening + Σcredit − Σdebit ≈ closing`，不平就在报告里大声说 | 有 `opening_balance`/`closing_balance` 字段，但**没有对账校验输出** |
| **隐私** | 写死规则：账号只留后 4 位、联网只能带商户 token、不许把 narrative 发出去 | 代码里没有掩码逻辑（`account_label` 原样输出） |
| **报告粒度** | **一个源文件一份报告** | 一个 binder（多账户多文件）一份评估 |
| **产物** | `output/<file>-report.html` + `<file>-transactions.csv` | `lender-assessment.xlsx`（+ markdown 模板） |
| **频率 → 月均** | agent 自己判断 cadence | 代码里固定换算表（weekly ×52/12、fortnightly ×26/12、quarterly ÷3、annual ÷12） |
| **增量分类** | 无 | 有：`compute_summary` 支持 `merge_classifications: true`，按 `batch_id` 服务端合并，补分类只发增量 |

**一句话总结差异**：他做的是「**给风险经理看的、会自我学习的商户识别 + 分类报告**」；我们做的是「**给 underwriter 用的、算术不许模型碰的 servicing 数字包**」。两者不冲突——他的强项（商户溯源、风险标记、人工回路、可读 HTML）正好是我们的空白；我们的强项（代码算账、封闭 schema、月均换算、增量分类）正好是他的风险点。

---

## 3. 模板占位符 → 我们现有字段的逐项映射

数据源统一记为 `S` = `compute_summary` 的返回 JSON（键名见 `function_app/compute_summary.py:1467` 起的返回字典）。

### 3.1 Header（区块 1）

| 占位符 | 我们的来源 | 状态 |
|---|---|---|
| `{{REPORT_TITLE}}` | 常量 + 文件名 | ✅ |
| `{{SOURCE_FILE}}` | `S.accounts[].source_file` | ✅ |
| `{{BANK}}` | `S.accounts[].institution` | ✅ |
| `{{MASKED_ACCOUNT}}` | `S.accounts[].account_label` | ⚠️ **缺掩码**：现在原样输出，需加「只留后 4 位」 |
| `{{STATEMENT_PERIOD}}` | `period_start` – `period_end` | ✅ |
| `{{OPENING_BALANCE}}` / `{{CLOSING_BALANCE}}` | `S.accounts[].opening_balance` / `closing_balance` | ✅（可能为 null，需兜底文案） |
| `{{GENERATED_DATE}}` | `S.assessment_date` | ✅ |

### 3.2 Summary cards（区块 2）

| 占位符 | 我们的来源 | 状态 |
|---|---|---|
| `{{TOTAL_INCOME}}` | `S.income[].amount_observed` 求和 / 或按 direction=inflow 汇总 | ⚠️ **口径不一致**：模板要的是「本期总额」，我们产出的是「月均等值」。需要新增 period 口径的合计 |
| `{{TOTAL_EXPENSES}}` | `S.part2` 中 outflow 行 `amount` 求和 | ⚠️ 同上，需新增 period 合计 |
| `{{NET_POSITION}}` | 上面两者相减 | ⚠️ 依赖上面两项 |
| `{{ESSENTIAL_SPLIT}}` | — | ❌ **完全缺失**：我们没有 `essential` 概念 |
| `{{RISK_FLAG_COUNT}}` | — | ❌ **完全缺失**：我们没有 `risk_flag` 概念 |

### 3.3 Category breakdown（区块 3）

| 占位符 | 我们的来源 | 状态 |
|---|---|---|
| `{{CATEGORY}}` | `S.part1[].category`（15 类标签） | ✅ |
| `{{CATEGORY_MONTHLY_AVG}}` | `S.part1[].monthly_equivalent` | ✅ 直接对上 |
| `{{CATEGORY_TOTAL}}` | 按 category 聚合 `S.part2[].amount` | ⚠️ 需新增（period 原始合计，不是月均） |
| `{{CATEGORY_PERCENT}}` | `CATEGORY_TOTAL / TOTAL_EXPENSES` | ⚠️ 依赖上面 |

### 3.4 Income analysis（区块 4）

| 占位符 | 我们的来源 | 状态 |
|---|---|---|
| `{{INCOME_SOURCE}}` | `S.income[].source` | ✅ |
| `{{INCOME_CADENCE}}` | `S.income[].frequency` | ✅ |
| `{{INCOME_AVG_AMOUNT}}` | `S.income[].amount_observed` | ✅ |
| `{{INCOME_REGULARITY}}` | 由观测次数 + frequency 推出（如 "4 次，双周稳定"） | ⚠️ 派生字段，代码里加一行即可 |

### 3.5 Recurring commitments（区块 5）—— 契合度最高的一块

| 占位符 | 我们的来源 | 状态 |
|---|---|---|
| `{{VENDOR}}` | `S.part2_calculations[].merchant` | ✅ |
| `{{CATEGORY}}` | `S.part2_calculations[].category` | ✅ |
| `{{AMOUNT}}` | `S.part2_calculations[].average_amount` | ✅ |
| `{{CADENCE}}` | `S.part2_calculations[].assessed_frequency` | ✅ |
| `{{ESSENTIAL_YN}}` | — | ❌ 缺 `essential` |

筛选条件「出现 ≥3 次」用 `S.part2_calculations[].observations >= 3`，已有。

### 3.6 Risk flags（区块 6）

| 占位符 | 我们的来源 | 状态 |
|---|---|---|
| `{{DATE}}` / `{{NARRATIVE_RAW}}` / `{{AMOUNT}}` | `S.part2[]` 对应字段 | ✅ |
| `{{RISK_REASON}}` | — | ❌ **整块缺失** |

### 3.7 Needs manual categorisation（区块 7）—— 直接对上

`S.part2[]` 中 `needs_review == true` 的行，取 `date` / `description` / `amount`。

⚠️ **更正（Codex 在 T-01 指出，已核对 `compute_summary.py:1203-1204`）**：`needs_review` 的实际定义是

```python
"needs_review": category in {"unclear", "underwriter_manual"} or business_flag in {"yes", "review"},
```

也就是说它**还包含 `is_business` 为 `yes`/`review` 的行**，比「待人工分类」宽。直接拿它当模板的 "Needs Manual Categorisation" 会把已经分好类的商业支出也塞进去。

正确做法：分三栏展示，不要合并——
- `unclear` → 真正的「待人工分类」（对应他的 `Other/Uncategorised`）
- `underwriter_manual` → underwriter 手动评估（如 council rates）
- `is_business ∈ {yes, review}` → 商业支出复核

他的 `Other / Uncategorised` 只等价于我们的 `unclear`。

### 3.8 Full transaction ledger（区块 8）

| 占位符 | 我们的来源 | 状态 |
|---|---|---|
| `{{DATE}}` | `S.part2[].date` | ✅ |
| `{{NARRATIVE_RAW}}` | `S.part2[].description` | ✅ |
| `{{VENDOR}}` | — | ❌ **更正：拿不到**。`S.part2[]` 的行字典（`compute_summary.py:1189-1206`）只有 date / description / amount / direction / frequency / include / category / transaction_id / source_file / account / exclusion_reason / reason / classified / needs_review / is_business —— **没有 merchant 字段**。归一化商户只存在于 `part2_calculations[].merchant`（聚合层），无法按行取回。见新增缺口 G10 |
| `{{CATEGORY}}` | `S.part2[].category` | ✅ |
| `{{SUBCATEGORY}}` | `utility_type` / `insurance_type` / `income_type` | ⚠️ 我们没有统一的 subcategory 字段，只有三个分类下的子类型；其余类别留空或回填 category 标签 |
| `{{AMOUNT}}` | `S.part2[].amount` | ✅ |
| `{{CONFIDENCE}}` | classification 的 `confidence` | ❌ **schema 里有，但 `compute_summary` 没有透传到行级**（代码里只在 `reason` 文案中间接体现，见 `compute_summary.py:845`） |
| `{{SOURCE_CELL}}` / `{{SOURCE_URL}}` | — | ❌ **完全缺失**：没有 source / source_url |

### 3.9 Exceptions（区块 9）

| 内容 | 我们的来源 | 状态 |
|---|---|---|
| 未 join 上的行 | `S.audit.join_miss_rows` | ✅ |
| 未分类行 | `S.audit.transaction_count - S.audit.classified_rows` | ✅ |
| 未解析商户 | — | ⚠️ 可用 `merchant_normalized` 为空来近似 |
| **对账失败** | — | ❌ 没做对账校验 |

### 3.10 缺口汇总（9 项）

| # | 缺什么 | 归属 | 要不要模型 |
|---|---|---|---|
| G1 | `essential` 布尔 | 15 个类别一张静态表就能定死 | 不需要模型 |
| G2 | `risk_flag` + 原因 | 费用/取现用正则；赌博、发薪日贷、BNPL 逾期需要模型判断 | 部分需要 |
| G3 | 行级 `confidence` 透传 | 已在 classification 里，只是没传下去 | 不需要 |
| G4 | `source` / `source_url` 商户溯源 | 需要新字段 + 可选 vendors.csv 缓存 | 不需要（联网另说） |
| G5 | 账号掩码（后 4 位） | extract 或 render 层加一个函数 | 不需要 |
| G6 | 余额对账校验 | `opening + Σin − Σout ≈ closing` | 不需要 |
| G7 | period 口径合计（收入/支出/分类总额） | 现在只有月均等值 | 不需要 |
| G8 | HTML 渲染器本身 | 新增 `render_html` | 不需要 |
| G9 | 他的 `categories.md` 原文 | **要向 Vikas 索要** | — |
| G10 | **行级 `merchant`** —— `part2[]` 不输出归一化商户，ledger 的 Vendor 列填不出来 | `collapse_merchant` 的结果只进了聚合层，透传到行即可 | 不需要 |
| G11 | **`needs_review` 拆分** —— 现在把 unclear / underwriter_manual / business review 混成一个布尔 | 拆成 `review_type` 三态 | 不需要 |

**结论：11 个缺口里 9 个是纯代码工作，1 个部分需要模型（risk_flag 中的赌博/高息贷），1 个是要资料。**

> G10 / G11 是复核 Codex 的 T-01 时发现的，他先看出来的；我原稿 3.7 / 3.8 两处写错，已在上面就地更正。

### 3.11 复核 T-01 后并入的三条（原稿没有，但应进实施计划）

1. **HTML 转义 + source URL allowlist**。模板要把 `source_url` 渲染成可点链接，客户流水的 `description` 也要进 HTML——这两处都是注入面，渲染器必须转义，链接必须校验白名单。
2. **`<!-- REPEAT -->` 不是模板语法**，是人写的注释。纯字符串替换生不出多行表格；渲染器要么改成真模板循环，要么自己构造每个表格区块。
3. **硬验收**：生成的 HTML 里不得残留任何 `{{...}}` 或 REPEAT 示例行；Excel 与 HTML 的同名指标必须逐项相等（共用同一份 view 数据，防数字漂移）。

---

## 4. 实现路线

### 4.1 三条路

| 方案 | 做法 | 评价 |
|---|---|---|
| A. 直接采纳他的 skill | 整套搬过来，agent 本地跑 | 起步快，但**模型重新接管算术**——这正是我们当初设计要消除的风险；也丢掉 Azure 部署 |
| B. **保留我们的管线，加一个 `render_html` 路由**（推荐） | 模板是纯 mustache + REPEAT 注释块，写一个渲染器从同一份 `compute_summary` JSON 填充，形状跟 `render_report.py::build_workbook` 一样 | 模型继续不碰算术；HTML 和 xlsx 共用同一份数字，不会出现两份报告对不上 |
| C. 混合 | 我们的管线出数字；他的 skill 作为**交互式前端**做人工补分类 + 商户缓存学习 | 值得作为 B 之后的第二阶段 |

**推荐 B，第二阶段吸收 C 的人工回路。**

### 4.2 工作项拆分（建议各自单独开 task）

| ID | 工作项 | 依赖 | 规模 |
|---|---|---|---|
| W1 | `essential` 静态映射表（15 类）+ essential/discretionary 占比 | — | 小 |
| W2 | `risk_flag`：代码正则（dishonour/overdraft/late fee、取现 > $500）+ 给 `classification.schema.json` 加可选 `risk_flag` enum（gambling / payday_lending / bnpl_arrears）+ prompt 补充说明 | — | 中 |
| W3 | 行级 `confidence` 透传到 `part2` | — | 小 |
| W4 | `source` / `source_url` 字段；一期只填 `pattern` / `unresolved`；二期接 vendors.csv 缓存 | — | 中 |
| W5 | 账号掩码后 4 位 | — | 小 |
| W6 | 余额对账校验 → 写进 exceptions | — | 小 |
| W7 | period 口径合计（TOTAL_INCOME / TOTAL_EXPENSES / CATEGORY_TOTAL） | — | 小 |
| W8 | `render_html` 渲染器 + 路由 + 测试（对齐 `pipeline/test_render_report.py` 的写法） | W1–W7 | 中 |
| W9 | 向 Vikas 索要 `references/categories.md`、`nz-vendors.md`、`vendor-cache.md`、`data/vendors.csv` | — | 沟通 |

**建议顺序**：W9（并行发出）→ W1/W3/W5/W6/W7（都是小改，可一批做）→ W2 → W8 → 二期 W4 缓存 + 人工回路。

---

## 5. 需要 Robin 拍板的开放问题

1. **报告粒度**：他是「一个源文件一份 HTML」，我们是「一个 binder 一份评估」。HTML 报告按他的来（每文件一份），还是按我们的来（合并一份）？**建议两种都支持，默认合并**，因为 servicing 本来就是跨账户看的。
2. **哪套 taxonomy 上报告**：HTML 里显示他的风险类别，还是我们的 15 类？**建议以我们的 15 类为准渲染进他的版式**——我们的类别是 schema 封闭校验的，而且 Part 1 的数字就是按这 15 类算的，换一套会导致报告数字和 xlsx 对不上。
3. **品牌**：模板是 AIA 品牌（而且注释里明说颜色是占位值）。最终报告是给 AIA，还是要换成 Kiwi Knowledge 自己的？改一组 CSS token 即可。
4. **是否允许联网做商户识别**（Companies Office / NZBN）。他的 skill 默认允许但要求只发商户 token。我们现在是全离线。这会影响 W4 的范围。
5. **`risk_flag` 里赌博/发薪日贷这类**，是让模型判断（要改 schema + prompt），还是先只做代码能判的（费用、大额取现）？

---

## 附：核对用命令

```bash
ls -l "from vikas"
grep -c "{{" "from vikas/report-template.html"
grep -n "essential\|risk_flag\|gambling" function_app/*.py schemas/*.json   # 应无输出 → 证明 G1/G2 确实缺
grep -n "confidence" function_app/compute_summary.py                        # 只有 3 处文案，无行级透传 → 证明 G3
```
