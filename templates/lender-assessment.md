# Lender-ready assessment summary

> All `$` amounts, day counts, and monthly equivalents are filled by the **calc engine**.
> The model writes classification labels, inclusion flags, and Part 5 commentary only.
> Placeholders use `{{mustache}}` syntax. Do not invent numbers in the template.

Assessment date: `{{assessment_date}}`

---

# SECTION 1: APPLICANT PROFILE & BINDER INDEX

## 1.1 Applicant Details

| Field | Value |
|:---|:---|
| Full Name(s) | {{applicant.full_name}} |
| Age(s) | {{applicant.age}} |
| Dependants | {{applicant.dependants}} |
| Current Residential Address & Living Situation | {{applicant.address_and_living_situation}} |

If a field is absent from the binder, write exactly: `Not provided in binder`.

## 1.2 Linked Accounts Inventory

| Institution | Account / card | Type | Statement period | Days covered | Days old (vs assessment date) | Source file |
|:---|:---|:---|:---|---:|---:|:---|
{{#accounts}}
| {{institution}} | {{account_label}} | {{account_type}} | {{period_start}} – {{period_end}} | {{days_covered}} | {{days_old}} | {{source_file}} |
{{/accounts}}

## 1.3 Document Index & Account Conduct Summary

{{#accounts}}
### {{institution}} — {{account_label}}

Documents (chronological):

{{#documents}}
- {{file_name}} ({{period_start}} – {{period_end}})
{{/documents}}

**Account Conduct Assessment**

| Signal | Count / detail |
|:---|:---|
| Arrears or overdrawn instances | {{conduct.arrears_or_overdrawn}} |
| Late payment / dishonour / unarranged overdraft fees | {{conduct.penalty_fees}} |
| Limit excesses or irregular activity | {{conduct.limit_excess_or_irregular}} |

{{/accounts}}

---

# SECTION 1.4: INCOME VERIFICATION (binder + credits)

Not in the Gemini prompt. Required because Vikas asked for income **and** expense, and servicing cannot be computed from expenses alone.

These figures are produced by the calc engine from credits classified as income. The model only labels the credit. Do not invent employer or net/gross if the binder does not state it.

| Source / Employer | Income type | Amount observed ($) | Frequency | Monthly equivalent ($) | Gross / net | Evidence |
|:---|:---|---:|:---|---:|:---|:---|
{{#income.rows}}
| {{source}} | {{income_type}} | {{amount_observed}} | {{frequency}} | {{monthly_equivalent}} | {{gross_or_net}} | {{evidence}} |
{{/income.rows}}

- **Total verified monthly income:** {{income.total_monthly_verified}}
- **Notes / insufficient observations:** {{income.notes}}

---

# SECTION 2 / OUTPUT PARTS

Present the lender expense pack in this order. Income sits **before** Part 1 so servicing has a numerator.

---

## Part 1: Applicant Expense Summary

| Category | Monthly Equivalent ($) | Notes / Calculation Basis |
|:---|---:|:---|
| Transport | {{part1.transport}} | |
| Utilities | {{part1.utilities}} | {{part1.utilities_notes}} |
| Insurance (Combined) | {{part1.insurance}} | {{part1.insurance_notes}} |
| Food, Grocery, Clothing & Personal Care | {{part1.food_grocery_clothing_personal_care}} | |
| Recreation & Entertainment | {{part1.recreation_entertainment}} | {{part1.recreation_notes}} |
| Monthly Subscriptions | {{part1.monthly_subscriptions}} | {{part1.subscriptions_notes}} |
| Education | {{part1.education}} | |
| KiwiSaver & Savings / Investments | {{part1.kiwisaver_savings_investments}} | |
| Childcare & Child Support | {{part1.childcare_child_support}} | |
| Donations / Tithings | {{part1.donations_tithings}} | |
| Rent / Board Paid | {{part1.rent_board_paid}} | |
| Medical Expenses | {{part1.medical}} | |
| Extracurricular Activities | {{part1.extracurricular}} | |
| Other Expenses | {{part1.other}} | |
| **TOTAL RECOMMENDED MONTHLY LIVING EXPENSES** | **{{part1.total_recommended_monthly_living_expenses}}** | |

- **Total Recurring Monthly Expenses by Category:** {{part1.total_recurring_monthly}}
- **Total One-Off Expenses Excluded:** {{part1.total_one_off_excluded}}
- **Total Monthly Living Expenses Recommended for Servicing:** {{part1.total_recommended_monthly_living_expenses}}

Council rates are excluded from automated totals and flagged for manual underwriter assessment.

---

## Part 2: Regular Expenses (Categorized Line Items)

Every transaction is a row. Do not group as "Various".

{{#part2.categories}}
### {{label}}

#### Transaction Table

| Date | Description | Amount ($) | Frequency Pattern | Include |
|:---|:---|---:|:---|:---|
{{#transactions}}
| {{date}} | {{description}} | {{amount}} | {{frequency}} | {{include}} |
{{/transactions}}

#### Frequency Assessment & Calculation Table

| Merchant | Dates Observed | Average Amount ($) | Assessment / Frequency | Calculated Monthly Impact ($) |
|:---|:---|---:|:---|---:|
{{#merchants}}
| {{merchant}} | {{dates_observed}} | {{average_amount}} | {{assessment}} | {{monthly_impact}} |
{{/merchants}}

{{/part2.categories}}

---

## Part 3: One-Off Expenses

| Date | Description | Amount ($) | Reason Excluded |
|:---|:---|---:|:---|
{{#part3.items}}
| {{date}} | {{description}} | {{amount}} | {{reason_excluded}} |
{{/part3.items}}

---

## Part 4: Existing Liabilities

| Institution / Lender | Facility Type | Credit Limit ($) | Current Balance ($) | Observed Repayment ($) | Frequency |
|:---|:---|---:|---:|---:|:---|
{{#part4.liabilities}}
| {{institution}} | {{facility_type}} | {{credit_limit}} | {{current_balance}} | {{observed_repayment}} | {{frequency}} |
{{/part4.liabilities}}

Facility types expected: home loan, personal loan, credit card, hire purchase, BNPL, other.

---

## Part 5: Assessor Commentary

*(Model-authored. Must not introduce numbers that are not already in Parts 1–4.)*

### Top 10 Recurring Merchants by Annual Spend

| Merchant Name | Annual Spend ($) | Category |
|:---|---:|:---|
{{#part5.top10_merchants}}
| {{merchant}} | {{annual_spend}} | {{category}} |
{{/part5.top10_merchants}}

### High-Frequency Merchants

Merchants appearing 3 or more times in the statement period:

{{#part5.high_frequency_merchants}}
- {{merchant}} ({{count}} times)
{{/part5.high_frequency_merchants}}

### Underwriter Audit Notes

{{part5.underwriter_audit_notes}}
