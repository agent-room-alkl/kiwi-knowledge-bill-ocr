# -*- coding: utf-8 -*-
"""Offline tests for the HTML lender-report renderer. No Azure, no network."""

from __future__ import annotations

import copy
import json
import re
import sys
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "function_app"))

from render_html import (  # noqa: E402
    allowlisted_https_url,
    build_html_document,
    build_report_artifacts,
    format_nzd,
    safe_filename,
    source_cell,
)
from render_report import build_workbook  # noqa: E402

FIXTURE = json.loads((ROOT / "pipeline" / "report_view.valid.fixture.json").read_text(encoding="utf-8"))


def _empty_view() -> dict:
    view = copy.deepcopy(FIXTURE)
    view["category_breakdown"]["rows"] = []
    view["income_sources"] = []
    view["recurring_commitments"] = []
    view["risk_flags"] = {"count": 0, "rows": []}
    view["manual_review"] = {"unclear": [], "underwriter_manual": [], "business_review": []}
    view["ledger"] = []
    view["exceptions"] = []
    return view


def test_renderer_fills_template_and_leaves_no_tokens():
    html = build_html_document(FIXTURE)
    assert "{{" not in html
    assert "}}" not in html
    assert "REPEAT" not in html
    assert "Category Breakdown" in html
    assert "Income Analysis" in html
    assert "Recurring Commitments" in html
    assert "Risk Flags" in html
    assert "Needs Manual Categorisation" in html
    assert "Full Transaction Ledger" in html
    assert "Exceptions" in html
    assert "FAKE-westpac-statement.pdf" in html
    assert "••••1234" in html
    assert "FAKE EMPLOYER" in html
    assert "FAKE GROCER" in html
    assert "Single cash withdrawal exceeds NZD 500." in html
    assert "[unclear] PAYPAL *TRUNCATED" in html
    assert "[underwriter manual] COUNCIL RATES" in html
    assert "[business review] WHOLESALE SUPPLIER" not in html
    assert "Applicant dependants were not provided in the binder." in html
    # Developer notes must not be copied onto every ledger row.
    assert "SOURCE_CELL" not in html
    assert "<!--" not in html
    assert "Never render a link" not in html
    assert "var PAGE_SIZE = 20" in html


def test_empty_arrays_drop_sample_rows():
    html = build_html_document(_empty_view())
    assert "{{" not in html
    assert "REPEAT" not in html
    assert "FAKE EMPLOYER" not in html
    assert "FAKE GROCER STORE 001" not in html
    assert "one <tr> per" not in html
    assert html.count("<tbody>") >= 5
    for match in re.finditer(r"<tbody>\s*</tbody>", html):
        assert match, match


def test_html_escape_and_url_allowlist():
    view = copy.deepcopy(FIXTURE)
    view["ledger"][0]["description"] = '<script>alert("xss")</script>'
    view["ledger"][0]["merchant"] = "A&B <Co>"
    view["ledger"][0]["vendor_source"] = "web"
    view["ledger"][0]["vendor_source_url"] = "javascript:alert(1)"
    view["meta"]["report_title"] = "Title <b>bold</b>"
    html = build_html_document(view)
    assert '<script>alert("xss")</script>' not in html
    assert "javascript:alert" not in html
    assert "&lt;script&gt;" in html
    assert "A&amp;B &lt;Co&gt;" in html
    assert "Title &lt;b&gt;bold&lt;/b&gt;" in html
    assert allowlisted_https_url("https://evil.example/x") is None
    assert allowlisted_https_url("http://www.nzbn.govt.nz/x") is None
    assert allowlisted_https_url("https://www.nzbn.govt.nz/search?q=1")
    assert "href=" not in source_cell(
        {"vendor_source": "web", "vendor_source_url": "https://evil.example"}
    )
    cell = source_cell(
        {
            "vendor_source": "nzbn",
            "vendor_source_url": "https://www.nzbn.govt.nz/search?q=1",
        }
    )
    assert 'href="https://www.nzbn.govt.nz/search?q=1"' in cell
    assert "rel=" in cell and "noopener" in cell
    assert source_cell({"vendor_source": "pattern", "vendor_source_url": "https://www.nzbn.govt.nz/x"}) == "pattern"


def test_amounts_match_report_view_not_recalculated():
    html = build_html_document(FIXTURE)
    cash = FIXTURE["observed_cashflow"]
    assert format_nzd(cash["total_inflows_nzd"]) in html
    assert format_nzd(cash["total_outflows_nzd"]) in html
    assert format_nzd(cash["net_movement_nzd"]) in html
    row = FIXTURE["category_breakdown"]["rows"][0]
    assert format_nzd(row["observed_total_nzd"]) in html
    assert format_nzd(row["monthly_equivalent_nzd"]) in html
    assert "100.00%" in html
    # HTML must not invent a servicing net (5000-2000 monthly) as a third number.
    servicing = FIXTURE["servicing"]
    assert format_nzd(servicing["assessable_income_monthly_nzd"]) != format_nzd(cash["net_movement_nzd"])


def test_xlsx_path_unchanged_and_format_dispatch():
    summary = {
        "assessment_date": "2026-09-01",
        "part1": [{"category": "Rent / board paid", "monthly_equivalent": 2400, "notes": "monthly"}],
        "part2": [],
        "part4": [],
        "part5": {},
        "report_view": FIXTURE,
    }
    xlsx_only = build_report_artifacts(summary, fmt="xlsx")
    assert [a["kind"] for a in xlsx_only] == ["xlsx"]
    assert xlsx_only[0]["filename"] == "lender-assessment.xlsx"
    wb = load_workbook(BytesIO(xlsx_only[0]["content"]))
    assert "Part1 Summary" in wb.sheetnames
    assert wb["Part1 Summary"]["B2"].value == 2400
    # Same sheets/values as the existing Excel renderer. Do not compare raw
    # zip bytes: openpyxl stamps the package clock, so two builds of the
    # same summary are not byte-identical.
    existing = load_workbook(BytesIO(build_workbook(summary)))
    assert wb.sheetnames == existing.sheetnames
    for name in wb.sheetnames:
        left, right = wb[name], existing[name]
        for a, b in zip(left.iter_rows(values_only=True), right.iter_rows(values_only=True)):
            assert a == b, name

    html_only = build_report_artifacts(summary, fmt="html", filename="../../evil<script>.xlsx")
    assert [a["kind"] for a in html_only] == ["html"]
    assert html_only[0]["filename"] == "evil-script.html"
    assert "/" not in html_only[0]["filename"]
    assert html_only[0]["content_type"].startswith("text/html")
    text = html_only[0]["content"].decode("utf-8")
    assert "{{" not in text
    assert format_nzd(FIXTURE["observed_cashflow"]["total_inflows_nzd"]) in text

    both = build_report_artifacts(summary, fmt="both")
    assert [a["kind"] for a in both] == ["xlsx", "html"]
    assert both[0]["filename"].endswith(".xlsx")
    assert both[1]["filename"].endswith(".html")


def _ledger_item(i: int) -> dict:
    return {
        "transaction_id": f"txn-{i}",
        "date": "2026-08-04",
        "description": f"FAKE ROW {i}",
        "amount_nzd": 1.0 + i,
        "direction": "outflow",
        "category": "food_grocery_clothing_personal_care",
        "source_file": "FAKE-westpac-statement.pdf",
        "merchant": f"FAKE {i}",
        "confidence": 0.9,
        "subcategory": None,
        "vendor_source": "unresolved",
        "vendor_source_url": None,
    }


def test_pager_keeps_every_row_and_pages_only_over_twenty():
    """Paging is display-only. Every row stays in the file; JS hides extras."""
    view19 = copy.deepcopy(FIXTURE)
    view19["ledger"] = [_ledger_item(i) for i in range(19)]
    html19 = build_html_document(view19)
    assert all(f"FAKE ROW {i}" in html19 for i in range(19))

    view20 = copy.deepcopy(FIXTURE)
    view20["ledger"] = [_ledger_item(i) for i in range(20)]
    html20 = build_html_document(view20)
    assert all(f"FAKE ROW {i}" in html20 for i in range(20))
    assert "var PAGE_SIZE = 20" in html20

    view21 = copy.deepcopy(FIXTURE)
    view21["ledger"] = [_ledger_item(i) for i in range(21)]
    html21 = build_html_document(view21)
    assert all(f"FAKE ROW {i}" in html21 for i in range(21))
    assert "var PAGE_SIZE = 20" in html21
    assert "paginateTables" in html21
    assert "Previous" in html21 and "Next" in html21


def test_safe_filename_strips_paths_and_forces_extension():
    assert safe_filename(r"C:\tmp\..\lender.html", "xlsx") == "lender.xlsx"
    assert safe_filename("ok_name", "html") == "ok_name.html"
    assert ".." not in safe_filename("../x", "html")


if __name__ == "__main__":
    test_renderer_fills_template_and_leaves_no_tokens()
    print("ok test_renderer_fills_template_and_leaves_no_tokens")
    test_empty_arrays_drop_sample_rows()
    print("ok test_empty_arrays_drop_sample_rows")
    test_html_escape_and_url_allowlist()
    print("ok test_html_escape_and_url_allowlist")
    test_amounts_match_report_view_not_recalculated()
    print("ok test_amounts_match_report_view_not_recalculated")
    test_xlsx_path_unchanged_and_format_dispatch()
    print("ok test_xlsx_path_unchanged_and_format_dispatch")
    test_pager_keeps_every_row_and_pages_only_over_twenty()
    print("ok test_pager_keeps_every_row_and_pages_only_over_twenty")
    test_safe_filename_strips_paths_and_forces_extension()
    print("ok test_safe_filename_strips_paths_and_forces_extension")
    print("ALL PASS")
