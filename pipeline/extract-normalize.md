# Extract + normalize (T-02 stub)

Azure AI Foundry tool: `extract_and_normalize`.
Does not call a bank. Input = user-supplied files.

## Binder triage

Reject non-statements before extraction (ANZ card-summary / Ts&Cs). Set `is_statement=false` and `reject_reason`.

## Extract

1. Prefer Azure Document Intelligence `prebuilt-layout` (or bankStatement if the resource has it).
2. Screenshot-only PDFs (Kiwibank how-to) have no text layer — same tool, OCR path.
3. Map tables to rows. Keep `raw_anchor` (page + snippet) for audit.

## Date

- Prefer **transaction date** over process date (Westpac two-column specimen).
- If the cell has no year (`03 Sept`), take year from `period_start`/`period_end`.
- December ? January across the period: increment year.

## Amount + direction

`amount` is always **positive**. `direction` carries the sign.

### Everyday / savings

- Withdrawal / debit column ? `outflow`
- Deposit / credit column ? `inflow`
- `POSREJ` ? `info`, amount 0, do not change balance

### Credit card

Opposite of household cash:

| Line | direction | Why |
|---|---|---|
| Purchase / cash advance / fee | `outflow` | Increases debt |
| Payment / refund / `CR` | `inflow` | Reduces debt |
| Interest | `outflow` then **exclude** in classify (`interest_charge`) | |

Unsigned amount + section header (`General Payments & Charges`) + `CR` suffix — that is the Westpac specimen.

Cards usually have **no running balance**. Do not fail the file for a missing balance column. Everyday files should reconcile opening + in ? out ? closing (±$0.02).

## Merchant key

Strip suburb / city / `NZL` / store street. Uppercase. Collapse spaces.
`Pak N Save Wairau Road Northshore NZL` ? `PAK N SAVE`.

## Output

JSON that validates against `schemas/canonical-transaction.schema.json`.
Classification (`classify_transactions`) consumes `transaction_id` from this batch.
