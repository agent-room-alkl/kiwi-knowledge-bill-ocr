# -*- coding: utf-8 -*-
"""Fill from vikas/report-template.html from a T-04 report_view. No arithmetic."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from report_view_fields import CATEGORY_LABELS

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HTML_CONTENT_TYPE = "text/html; charset=utf-8"

ALLOWED_VENDOR_HOST_SUFFIXES = (
    "companiesoffice.govt.nz",
    "nzbn.govt.nz",
)
LINKABLE_VENDOR_SOURCES = frozenset({"companies_office", "nzbn", "web"})
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
REPEAT_RE = re.compile(
    r"<!--\s*REPEAT:.*?-->\s*(.*?)\s*<!--\s*END REPEAT\s*-->",
    re.DOTALL | re.IGNORECASE,
)


def _template_path() -> Path:
    here = Path(__file__).resolve().parent
    candidates = (
        here / "report_template.html",
        here.parent / "from vikas" / "report-template.html",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("report_template.html not found next to the function or under from vikas/")


def escape_text(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def format_nzd(value: Any) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if number < 0 else ""
    return f"{sign}${abs(number):,.2f}"


def format_percent(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def format_confidence(value: Any) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if 0 <= number <= 1:
        return f"{round(number * 100)}%"
    return escape_text(value)


def humanize(value: Any) -> str:
    return str(value or "").replace("_", " ")


def category_label(category: Any) -> str:
    key = str(category or "")
    return CATEGORY_LABELS.get(key, humanize(key) or "Unclear")


def safe_filename(name: str | None, ext: str, default_stem: str = "lender-assessment") -> str:
    raw = Path(name or default_stem).name
    stem = Path(raw).stem
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-") or default_stem
    return f"{cleaned}.{ext.lstrip('.')}"


def allowlisted_https_url(url: Any) -> str | None:
    text = str(url or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    if not any(host == suffix or host.endswith("." + suffix) for suffix in ALLOWED_VENDOR_HOST_SUFFIXES):
        return None
    return text


def source_cell(item: dict[str, Any]) -> str:
    source = item.get("vendor_source") or "unresolved"
    label = escape_text(humanize(source) or "unresolved")
    if source not in LINKABLE_VENDOR_SOURCES:
        return label
    href = allowlisted_https_url(item.get("vendor_source_url"))
    if not href:
        return label
    return (
        f'<a href="{html.escape(href, quote=True)}" target="_blank" rel="noopener">{label}</a>'
    )


def _fill(template: str, values: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        return values.get(match.group(1), "")

    return PLACEHOLDER_RE.sub(repl, template)


def _expand_repeats(template: str, blocks: list[list[dict[str, str]]]) -> str:
    remaining = template
    for rows in blocks:
        match = REPEAT_RE.search(remaining)
        if match is None:
            raise ValueError("HTML template is missing a REPEAT block the renderer expected")
        row_tpl = match.group(1)
        rendered = "".join(_fill(row_tpl, row) for row in rows)
        remaining = remaining[: match.start()] + rendered + remaining[match.end() :]
    if REPEAT_RE.search(remaining):
        raise ValueError("HTML template still has an unexpanded REPEAT block")
    return remaining


def _money_header(accounts: list[dict[str, Any]], field: str) -> str:
    if not accounts:
        return "—"
    if len(accounts) == 1:
        return format_nzd(accounts[0].get(field))
    return "; ".join(
        f"{escape_text(acc.get('masked_account') or '••••')}: {format_nzd(acc.get(field))}"
        for acc in accounts
    )


def _header_values(view: dict[str, Any]) -> dict[str, str]:
    meta = view.get("meta") or {}
    cash = view.get("observed_cashflow") or {}
    breakdown = view.get("category_breakdown") or {}
    risks = view.get("risk_flags") or {}
    accounts = list(meta.get("accounts") or [])
    source_files = meta.get("source_files") or []
    institutions = meta.get("institutions") or []
    masked = meta.get("masked_account")
    if not masked:
        masked = "; ".join(str(a.get("masked_account") or "••••") for a in accounts) or "••••"
    generated = str(meta.get("generated_at") or "")
    generated_date = generated[:10] if generated else ""
    essential = breakdown.get("essential_percent")
    discretionary = breakdown.get("discretionary_percent")
    return {
        "REPORT_TITLE": escape_text(meta.get("report_title") or "Bank Statement Analysis Report"),
        "SOURCE_FILE": escape_text("; ".join(str(x) for x in source_files) or "unknown"),
        "BANK": escape_text("; ".join(str(x) for x in institutions) or "Unknown"),
        "MASKED_ACCOUNT": escape_text(masked),
        "STATEMENT_PERIOD": escape_text(
            f"{meta.get('period_start') or '—'} to {meta.get('period_end') or '—'}"
        ),
        "OPENING_BALANCE": _money_header(accounts, "opening_balance_nzd"),
        "CLOSING_BALANCE": _money_header(accounts, "closing_balance_nzd"),
        "GENERATED_DATE": escape_text(generated_date or generated or "—"),
        "TOTAL_INCOME": format_nzd(cash.get("total_inflows_nzd")),
        "TOTAL_EXPENSES": format_nzd(cash.get("total_outflows_nzd")),
        "NET_POSITION": format_nzd(cash.get("net_movement_nzd")),
        "ESSENTIAL_SPLIT": escape_text(
            f"{format_percent(essential)}% essential / {format_percent(discretionary)}% discretionary"
        ),
        "RISK_FLAG_COUNT": escape_text(str(int(risks.get("count") or 0))),
    }


def _category_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "CATEGORY": escape_text(row.get("label") or category_label(row.get("category"))),
        "CATEGORY_TOTAL": format_nzd(row.get("observed_total_nzd")),
        "CATEGORY_MONTHLY_AVG": format_nzd(row.get("monthly_equivalent_nzd")),
        "CATEGORY_PERCENT": escape_text(format_percent(row.get("percent_of_denominator"))),
    }


def _income_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "INCOME_SOURCE": escape_text(row.get("source") or "Unknown source"),
        "INCOME_CADENCE": escape_text(humanize(row.get("frequency") or "unknown")),
        "INCOME_AVG_AMOUNT": format_nzd(row.get("dominant_amount_nzd")),
        "INCOME_REGULARITY": escape_text(humanize(row.get("regularity") or "not assessable")),
    }


def _commitment_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "VENDOR": escape_text(row.get("merchant") or "Unknown"),
        "CATEGORY": escape_text(category_label(row.get("category"))),
        "AMOUNT": format_nzd(row.get("dominant_amount_nzd")),
        "CADENCE": escape_text(humanize(row.get("frequency") or "unknown")),
        "ESSENTIAL_YN": "Yes" if row.get("essential") else "No",
    }


def _risk_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "DATE": escape_text(row.get("date") or "—"),
        "NARRATIVE_RAW": escape_text(row.get("description") or "Not provided"),
        "AMOUNT": format_nzd(row.get("amount_nzd")),
        "RISK_REASON": escape_text(row.get("reason") or humanize(row.get("rule_id")) or "review"),
    }


def _manual_row(row: dict[str, Any]) -> dict[str, str]:
    review = humanize(row.get("review_type") or "unclear")
    narrative = row.get("description") or "Not provided"
    return {
        "DATE": escape_text(row.get("date") or "—"),
        "NARRATIVE_RAW": escape_text(f"[{review}] {narrative}"),
        "AMOUNT": format_nzd(row.get("amount_nzd")),
    }


def _ledger_row(row: dict[str, Any]) -> dict[str, str]:
    label = category_label(row.get("category"))
    sub = row.get("subcategory")
    if sub:
        category_cell = escape_text(f"{label} / {humanize(sub)}")
    else:
        category_cell = escape_text(label)
    return {
        "DATE": escape_text(row.get("date") or "—"),
        "NARRATIVE_RAW": escape_text(row.get("description") or "Not provided"),
        "VENDOR": escape_text(row.get("merchant") or "—"),
        "CATEGORY": category_cell,
        "SUBCATEGORY": "",
        "AMOUNT": format_nzd(row.get("amount_nzd")),
        "CONFIDENCE": format_confidence(row.get("confidence")),
        "SOURCE_CELL": source_cell(row),
        "SOURCE_URL": "",
        "SOURCE_LABEL": "",
    }


def _exception_row(row: dict[str, Any]) -> dict[str, str]:
    return {"EXCEPTION_DESCRIPTION": escape_text(row.get("description") or "Unspecified exception")}


def build_html_document(report_view: dict[str, Any]) -> str:
    if not isinstance(report_view, dict):
        raise ValueError("report_view must be an object")
    breakdown = report_view.get("category_breakdown") or {}
    category_rows = list(breakdown.get("rows") or [])
    bar_rows = sorted(category_rows, key=lambda r: float(r.get("observed_total_nzd") or 0), reverse=True)
    manual = report_view.get("manual_review") or {}
    # Template section is "Other/Uncategorised" — not already-classified business.
    # Dumping business_review here made Cursor/Anthropic look like unclear.
    manual_rows = list(manual.get("unclear") or []) + list(
        manual.get("underwriter_manual") or []
    )
    template = _template_path().read_text(encoding="utf-8")
    filled = _expand_repeats(
        template,
        [
            [_category_row(r) for r in category_rows],
            [_category_row(r) for r in bar_rows],
            [_income_row(r) for r in report_view.get("income_sources") or []],
            [_commitment_row(r) for r in report_view.get("recurring_commitments") or []],
            [_risk_row(r) for r in (report_view.get("risk_flags") or {}).get("rows") or []],
            [_manual_row(r) for r in manual_rows],
            [_ledger_row(r) for r in report_view.get("ledger") or []],
            [_exception_row(r) for r in report_view.get("exceptions") or []],
        ],
    )
    # Ledger template is `{{CATEGORY}} / {{SUBCATEGORY}}`; subcategory is folded into CATEGORY.
    filled = filled.replace(" / </td>", "</td>")
    filled = _fill(filled, _header_values(report_view))
    # Developer notes inside REPEAT were copied onto every ledger row (145KB
    # of SOURCE_CELL instructions on a real binder). Strip leftover comments
    # after expansion so they cannot ship to the underwriter.
    filled = re.sub(r"<!--.*?-->", "", filled, flags=re.DOTALL)
    if "{{" in filled or "}}" in filled or "REPEAT" in filled or "SOURCE_CELL" in filled:
        raise ValueError("rendered HTML still contains template tokens")
    return filled


def build_html_bytes(summary: dict[str, Any]) -> bytes:
    view = (summary or {}).get("report_view")
    if not isinstance(view, dict):
        raise ValueError(
            "summary has no report_view; re-run compute_summary and pass that summary_id"
        )
    return build_html_document(view).encode("utf-8")


def build_report_artifacts(
    summary: dict[str, Any],
    applicant: dict[str, Any] | None = None,
    fmt: str = "xlsx",
    filename: str | None = None,
) -> list[dict[str, Any]]:
    kind = str(fmt or "xlsx").strip().lower()
    if kind not in {"xlsx", "html", "both"}:
        raise ValueError("format must be xlsx, html, or both")
    artifacts: list[dict[str, Any]] = []
    if kind in {"xlsx", "both"}:
        from render_report import build_workbook

        artifacts.append(
            {
                "kind": "xlsx",
                "filename": safe_filename(filename, "xlsx"),
                "content": build_workbook(summary, applicant),
                "content_type": XLSX_CONTENT_TYPE,
            }
        )
    if kind in {"html", "both"}:
        artifacts.append(
            {
                "kind": "html",
                "filename": safe_filename(filename, "html"),
                "content": build_html_bytes(summary),
                "content_type": HTML_CONTENT_TYPE,
            }
        )
    return artifacts
