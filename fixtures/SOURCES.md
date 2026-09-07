# Public NZ statement layout sources

Search date: 2026-08-31.

NZ banks do **not** publish downloadable customer statement PDFs. Official pages only show how to export *your own* statements from internet banking. Paid "ANZ statement templates" and leaked Scribd uploads were ignored (forgery / real PII).

## What brokers actually receive

Mortgage Lab and similar NZ adviser guides: **PDF from internet banking only**. CSV / QIF / OFX / screenshots are typically rejected. Production input is therefore bank-generated PDFs (everyday account and credit card).

## Official specimens Claude downloaded (preferred over field-text only)

| File | URL | Use |
|---|---|---|
| Westpac credit-card "how to read" | https://www.westpac.co.nz/assets/Personal/credit-cards/documents/Westpac-how-to-read-your-credit-card-statement-guide-PDF.pdf | Best layout + fake line items. Columns: TRANSACTION DATE, PROCESS DATE, DETAILS, AMOUNT $. Dates without year. Amounts unsigned; direction from section header / `CR`. |
| Kiwibank print-statements how-to | https://media.kiwibank.co.nz/media/documents/Internet_Banking_How_To_Guide_Print_Statements.pdf | Screenshot-only (no text layer) — OCR path |
| BNZ QRG | https://www.bnz.co.nz/assets/personal-banking-help-support/Internet-Banking/PDFs/qrg-View-Statements-IB.pdf | UI screenshots |
| ANZ Card Summary sample | https://www.anz.co.nz/content/dam/anzconz/documents/rates-fees-agreements/credit-cards/ANZ-Card-summary-sample.pdf | Negative fixture: not a statement |
| Broker download guide | https://youm.co.nz/wp-content/uploads/2022/05/Bank-Statement-and-IRD-Summary-Download-Guide-2022-2.pdf | Export paths only |

Do not use Scribd personal statements or fill-and-sign fake-statement sites.

## Official field guides (use these to build synthetic fixtures)

| Bank | Product | Public source | Fields called out |
|---|---|---|---|
| Kiwibank | Everyday | https://www.kiwibank.co.nz/help/accounts/balances-statements/bank-statements/read-statement/ | Account name, number, end-of-period balance; dated withdrawals/deposits/interest/fees; running balance on the right; `POSREJ` (declined, no balance change) |
| Kiwibank | Credit card | https://www.kiwibank.co.nz/help/cards/manage-a-card/understand-a-credit-card-statement/ | Closing balance, credit limit, available credit, opening balance, interest summary (purchases / cash advances / transfers), transaction details, minimum payment due, payment due date, statement period on each page |
| Westpac | Credit card | https://www.westpac.co.nz/personal/life-money/managing-your-money/understanding-credit-card-statements/ | Transactions, payments, fees, interest; labelled PDF guide on that page (login-free marketing page) |
| ANZ / ASB / BNZ / Westpac / TSB | Everyday | Bank help + adviser download guides | PDF via Documents / Statement Vault / Download statements. No public sample PDF |

Adviser how-to (export path only, no sample files):

- https://www.mortgagelab.co.nz/blog/how-to-correctly-export-your-bank-statements
- https://www.maxmoneygroup.co.nz/bank-statement-download-guide

## Recommended fixture set (synthetic, labelled FAKE)

Build PDFs that *look like* the official field layout, using invented people and merchants. Do not copy real customer rows.

Minimum coverage:

1. ANZ everyday — 3 monthly PDFs, running balance, salary credit, rent, groceries, internal transfer
2. ASB Visa/Mastercard — 3 monthly PDFs, purchases + card payment + interest
3. BNZ everyday — fees / dishonour if we need conduct tests
4. Westpac credit card — limit, min payment, due date
5. Kiwibank everyday — include one `POSREJ` row
6. Optional: TSB / Cooperative / Heartland everyday; Afterpay or Gem/Q Card for BNPL in Part 4

Each file stamped `SYNTHETIC TEST FIXTURE — NOT A REAL BANK DOCUMENT`.

## Gold output

The Gemini prompt writes **5-part Markdown tables**, not Excel. If the assessor artefact is `.xlsx`, drop a gold workbook here and map Part 1–5 onto sheets.
