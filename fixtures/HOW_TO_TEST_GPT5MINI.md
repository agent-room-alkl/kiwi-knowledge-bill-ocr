# GPT-5 mini smoke test

Do **not** paste real customer statements.

## Files to upload

All under `fixtures/samples/` — every page is stamped FAKE.

| File | What it is | Landmines |
|---|---|---|
| `ANZ-everyday-FAKE-2026-07.pdf` | Everyday + running balance | Salary, rent, 3× Pak N Save stores, Netflix, power, KiwiSaver, Afterpay, quarterly water, **annual AA insurance $1,200**, internal transfer, mortgage |
| `Westpac-mastercard-FAKE-2026-07.pdf` | Card, Westpac-like columns | Two date cols, dates without year, `CR`, interest rows, card payment, Q Card/Gem |
| `Kiwibank-everyday-FAKE-2026-06.pdf` | Everyday | `POSREJ`, WFF credit, unarranged O/D fee, internal transfer, donation |
| `ASB-visa-FAKE-2026-05.pdf` | Card | Card payment, Apple sub, **Air NZ international one-off** |

## Prompt

Paste `foundry/prompt-gpt5.md` as the system / developer prompt.
Assessment date: `2026-08-31`.

Without the extract/compute tools, mini will still try to write the report. That is useful as a **failure baseline**. Check:

1. Income section exists (two ACME salary credits + WFF).
2. KiwiSaver and donations are **not** inside recommended living.
3. AA Insurance $1,200 is `insufficient_observations` or one-off — not silently ÷12.
4. Watercare quarterly is not silently ÷3 unless marked underwriter.
5. Three Pak N Save stores collapse to one merchant for ?3 / top-10.
6. Interest and card/mortgage/internal transfers excluded from living.
7. Air NZ international is one-off, not recreation.
8. No invented applicant age (binder says not provided).
9. Totals that the model typed by hand — treat as untrusted until tools exist.

## Expected: this run will be messy

That is the point. Foundry needs T-02 tools before numbers are lender-ready.
The prompt is the guardrail; these PDFs are the first binder.
