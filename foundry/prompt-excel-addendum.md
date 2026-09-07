# Append this to the Foundry agent instructions

You MUST deliver a real Excel file named `lender-assessment.xlsx`.

If Code Interpreter (or any file-writing tool) is available:

1. Create a workbook with these sheets, in this order:
   - `1.1 Applicant`
   - `1.2 Accounts`
   - `1.4 Income`
   - `Part1 Summary`
   - `Part2 Line items`
   - `Part3 One-off`
   - `Part4 Liabilities`
   - `Part5 Commentary`
2. Column headers must match `fixtures/samples/lender-assessment-TEMPLATE.xlsx`.
3. Put every classified transaction on `Part2 Line items` (one row each, no "Various").
4. Totals on `Part1 Summary` may be approximate in this baseline run; label them `MODEL DRAFT - not code-computed`.
5. Save as `lender-assessment.xlsx` and return it as an output file.

If you have no file-writing tool, say exactly:
`NO_XLSX_TOOL` and then print the same sheets as Markdown tables.

Do not stop after a prose summary. The Excel (or `NO_XLSX_TOOL` + Markdown) is the deliverable.
