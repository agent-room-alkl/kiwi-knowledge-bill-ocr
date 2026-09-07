# kiwi-knowledge-bill-ocr

NZ bank-statement servicing assessment: extract statements → classify → compute totals in code → render a lender-ready Excel/Markdown report.

Split by design: **arithmetic lives in code**, **per-applicant judgement lives in the Foundry agent prompt**. The model classifies; it never computes totals.

## Layout

| Path | What it is |
|---|---|
| `function_app/` | Azure Functions app (Python v2 model) — the deployed HTTP tools |
| `foundry/` | Azure AI Foundry agent instructions, prompts, and the OpenAPI spec used to hang the tools |
| `pipeline/` | Test harness for the function-app modules, plus the extract/normalize design note |
| `schemas/` | Canonical transaction + classification JSON Schemas and the expense taxonomy |
| `templates/` | Report template and the Excel builder (`build_excel.py`) |
| `fixtures/` | Synthetic fixture generator + notes on public NZ statement layout sources |
| `specs/` | Original assessment spec |

## Function app

Three HTTP routes (`host.json` route prefix `api`):

- `POST /api/extract_and_normalize` — Document Intelligence `prebuilt-layout` → canonical transaction rows
- `POST /api/compute_summary` — code-only exclusions, frequency detection, monthly equivalents, conduct counts, Part 1/3/4 figures
- `POST /api/render_report` — fills the lender-assessment report and returns the `.xlsx`

Deploy:

```bash
cd function_app && func azure functionapp publish <your-function-app-name>
```

App settings required at runtime (Document Intelligence endpoint/key, storage connection, container allowlist) are read from the environment — nothing is committed.

## Tests

```bash
python3 pipeline/test_compute_summary.py
```

Each `pipeline/test_*.py` is a standalone harness that re-runs the real modules and asserts exact deltas, rather than reading the code.

## Generated files (not committed)

```bash
python3 fixtures/generate_fixtures.py   # synthetic FAKE statement PDFs
python3 templates/build_excel.py        # lender-assessment template + gold xlsx
```

No real customer data, and no statement PDFs from any bank, are in this repo — every fixture is synthetic.
