# Lender servicing taxonomy

Source of truth: `specs/Analyse the attached bank statement.txt` (Gemini prompt that already works).

This taxonomy is for **NZ mortgage/credit servicing assessment**, not household budgeting.

## Living-expense categories (exactly 15)

Used in Part 1 monthly-equivalent totals and Part 2 line-item tables.

| id | label | notes |
|---|---|---|
| `transport` | Transport | Fuel, vehicle registration, WOF, parking, public transit |
| `utilities` | Utilities | Power, water, gas, internet/Wi-Fi, phone/mobile. Monthly average per utility type, then sum |
| `insurance` | Insurance (unified) | All policies under one heading, then split by `insurance_type` |
| `food_grocery_clothing_personal_care` | Food, Grocery, Clothing & Personal Care | Essential groceries, basic toiletries, essential clothing |
| `recreation_entertainment` | Recreation & Entertainment | Non-essential retail, dining/cafes/takeaways/bars, domestic/local travel only |
| `monthly_subscriptions` | Monthly Subscriptions | Gym, gaming, streaming/OTT, cloud, Apple/Google services. Frequency shown explicitly |
| `education` | Education | Public & private tuition, school fees, uniforms |
| `kiwisaver_savings_investments` | KiwiSaver & Savings / Investments | |
| `childcare_child_support` | Childcare & Child Support | |
| `donations_tithings` | Donations / Tithings | |
| `rent_board_paid` | Rent / Board Paid | |
| `medical` | Medical Expenses | Doctors, pharmacy, dental (not health insurance — that is `insurance`) |
| `extracurricular` | Extracurricular Activities | Sports, clubs, lessons |
| `other` | Other Expenses | Recurring only; must not reasonably fit a category above |
| `one_off` | One-Off Expenses | Non-recurring / unusual / extraordinary, including major or international travel |

Council rates are **not** auto-calculated. Flag as `underwriter_manual` for the underwriter.

### Insurance subtypes

`home_contents` | `vehicle` | `life_personal_risk` | `medical_health` | `pet` | `funeral` | `other_insurance`

### Utility subtypes

`power` | `water` | `gas` | `internet` | `phone_mobile` | `other_utility`

## Exclusions (never in recommended monthly living expenses)

These still appear as classified line items so the assessor can audit the filter.

| id | label |
|---|---|
| `internal_transfer` | Internal transfer between applicant accounts |
| `credit_card_repayment` | Credit card repayment |
| `loan_repayment` | Loan repayment (excl. mortgage) |
| `mortgage_repayment` | Mortgage repayment |
| `interest_charge` | Interest charge |
| `redraw` | Redraw |
| `income_credit` | Income credit |
| `reimbursement` | Reimbursement |

## Income types (for applicant profile / cash-flow context only)

Not living expenses. Used to label credits that are income.

`salary_wages` | `benefit` | `child_support_received` | `rental_income` | `investment_income` | `other_income`

## Frequency values

`weekly` | `fortnightly` | `monthly` | `quarterly` | `annual` | `irregular` | `one_off` | `unknown`

Monthly equivalent (code only — LLM must not compute):

- weekly: `amount * 52 / 12`
- fortnightly: `amount * 26 / 12`
- quarterly: `amount / 3`
- annual: `amount / 12`
- monthly: `amount`

## Merchant normalisation (Part 5)

Westpac specimen rows look like `Pak N Save Wairau Road Northshore NZL`.
Part 5 top-10 and "appears ≥3 times" must key on a **normalised merchant**, not the raw descriptor.

Suggested key: strip store/suburb/city/`NZL` suffix, uppercase, collapse whitespace.
`Pak N Save Wairau Road Northshore NZL` and `Pak N Save Glenfield Auckland NZL` → `PAK N SAVE`.

## Classification output contract

For every extracted transaction the model returns one classification object that validates against `classification.schema.json`.

- `category` is a closed enum (15 living + 8 exclusions + 6 income + `underwriter_manual` + `unclear`).
- `include_in_living_expenses` must be `false` for exclusions, income, one-off, and underwriter-manual.
- `confidence` is 0–1. Rows below 0.6 stay `unclear` for human review.
- The model may suggest `frequency`; the calc engine is authoritative.
- Optional `merchant_normalized` is a hint only; calc engine owns Part 5 grouping.
- Optional `is_business` is `yes` | `no` | `review`. The engine excludes from recommended living only when the field is `yes`. Absent defaults to `no`. The model judges from the nature of the spend (premises, advertising, trade software, wholesale stock, freight, trade equipment vs household living); it does not use a merchant list. Optional `business_reason` is a short criterion.
