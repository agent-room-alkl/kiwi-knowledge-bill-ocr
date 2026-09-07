# How to hang the 3 functions on a Foundry agent

Foundry Playground cannot run our Python by itself (Code Interpreter improvises and gets Part 1 wrong). The agent must **call HTTP tools**. You hang **one OpenAPI 3.0 spec** that exposes three `operationId`s.

| operationId | Who runs it | What it does |
|---|---|---|
| `extract_and_normalize` | Azure Function + Document Intelligence | PDF/image ? canonical transactions |
| `compute_summary` | Azure Function (pure Python) | classifications + rows ? Part 1–4 numbers |
| `render_report` | Azure Function + openpyxl | summary JSON ? `lender-assessment.xlsx` |

The model **classifies** (JSON). It must not write Part 1 totals.

Spec file in this repo: `foundry/openapi-servicing.json`.

## 0. Azure pieces you create (once)

1. **Function App** (Python 3.11+, HTTP trigger, same region as Foundry).
2. **Document Intelligence** resource (you already created this). Give the Function App a key or managed identity with `Cognitive Services User` on that resource.
3. Deploy the functions in `function_app/` (when present) so these routes exist:

```
POST https://<app>.azurewebsites.net/api/extract_and_normalize
POST https://<app>.azurewebsites.net/api/compute_summary
POST https://<app>.azurewebsites.net/api/render_report
```

4. Until Functions are deployed, you can still hang the spec, but the agent will get HTTP errors. **Calc tests run locally** without Azure (`python3 pipeline/test_compute_summary.py`).

## 1. Put the Function URL into the spec

Open `foundry/openapi-servicing.json`. Set:

```yaml
servers:
  - url: https://<your-function-app>.azurewebsites.net/api
```

Every path must have an `operationId` using only letters, `_`, `-`.

## 2. Hang it on the agent (Foundry portal)

1. Open [https://ai.azure.com](https://ai.azure.com) ? your project ? the Vikas agent.
2. **Tools / Actions** ? **Add**.
3. Choose **OpenAPI 3.0 specified tool** (not Code Interpreter, not Bing).
4. Name: `vikas_servicing`. Description: `Extract NZ bank statements, compute servicing totals, render Excel. Never invent Part 1 numbers.`
5. Paste the contents of `foundry/openapi-servicing.json`.
6. Authentication:
   - First test: **Anonymous** only if the Function App allows it (dev only).
   - Next: **API key** via a Foundry **Connected resource** (custom keys) holding `x-functions-key`.
   - Production: **Managed identity**; Audience = the Function App / Easy Auth Application ID URI.
7. Save. Confirm the tool shows three operations.
8. **Turn Code Interpreter off** for this agent so it cannot bypass the calc tool.
9. Agent instructions: use `foundry/agent-instructions.md` plus: *You must call extract_and_normalize, then return classifications, then call compute_summary, then render_report. Do not put dollar totals in chat except the 5-line audit summary from the tool output.*

## 3. Run

Attach statement PDFs ? send a short user message: `Assess servicing. assessment_date=2026-08-31.`  
The agent should: extract ? classify ? compute_summary ? return xlsx from render_report.

## 4. What you do vs what Cursor does

| You (Azure) | Cursor (repo) |
|---|---|
| Function App + DI connection + paste OpenAPI on the agent | `compute_summary.py`, tests, OpenAPI spec, this doc |
| API key / managed identity | Function handler stubs when we add `function_app/` |

Do not add eight bank-specific tools. One extract operation; layout model is bank-agnostic.
