# -*- coding: utf-8 -*-
"""Build the T-04 report_view contract from compute_summary internals.

Does not change Part 1–5 or Excel numbers. Attaches a single `report_view` key.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from extract_normalize import vendor_provenance

CATEGORY_POLICY: dict[str, str] = {
    "transport": "essential",
    "utilities": "essential",
    "insurance": "essential",
    "food_grocery_clothing_personal_care": "essential",
    "recreation_entertainment": "discretionary",
    "monthly_subscriptions": "discretionary",
    "education": "essential",
    "kiwisaver_savings_investments": "savings_giving",
    "childcare_child_support": "essential",
    "donations_tithings": "savings_giving",
    "rent_board_paid": "essential",
    "medical": "essential",
    "extracurricular": "discretionary",
    "other": "manual",
    "one_off": "excluded",
}

# Risk rules split by what can be proven. A fee is a fee because the bank
# printed the word on the line, and a $600 ATM withdrawal is $600 whoever
# took it - those are code's job, and code must not defer to the model on
# them. Whether a merchant is a casino or a payday lender is not in the
# narrative at all, so the model answers that one, under a closed enum, and
# its answer lands as `review` rather than as an established fact.
CASH_WITHDRAWAL_THRESHOLD_NZD = 500.0

_TEXT_RISK_RULES: tuple[tuple[str, re.Pattern[str], str, str], ...] = (
    (
        "dishonour_fee",
        re.compile(r"\b(DISHONOUR|DISHONOR|DISHON\b|BOUNCED|RETURNED ITEM|REVERSAL FEE)", re.I),
        "high",
        "bank charged a dishonour fee, so a payment failed for want of funds",
    ),
    (
        "overdraft_fee",
        re.compile(r"\b(UNARRANGED OVERDRAFT|OVERDRAFT FEE|OD FEE|EXCESS FEE|HONOUR FEE)", re.I),
        "high",
        "bank charged an overdraft fee, so the account went beyond its limit",
    ),
    (
        "late_payment_fee",
        re.compile(r"\b(LATE PAYMENT|LATE FEE|DEFAULT FEE|ARREARS FEE|PENALTY (?:FEE|INTEREST))", re.I),
        "high",
        "bank or lender charged a late-payment fee",
    ),
)

# The model may only speak through these three, and only about merchants.
_MODEL_RISK_RULES: frozenset[str] = frozenset(
    {"gambling", "payday_high_cost_lending", "bnpl_arrears"}
)

_MODEL_RISK_REASONS: dict[str, str] = {
    "gambling": "model identified the merchant as gambling",
    "payday_high_cost_lending": "model identified the merchant as payday / high-cost lending",
    "bnpl_arrears": "model identified a buy-now-pay-later arrears charge",
}

# `_CASH_RE` is bound to CASH_WITHDRAWAL_RE below, where that pattern is
# defined. Deliberately NOT a bare `W/D`: Kiwibank prints card purchases as
# `POS W/D <merchant>`, so matching `W/D` alone flagged a $612 wholesale
# invoice at a named supplier as an unexplained cash withdrawal. Risk
# flagging must not be looser than the living-expense rule it is named
# after, so the two share one pattern rather than two that can drift.


def _risk_rows(joined: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every transaction that trips a risk rule, most severe first.

    A row can trip more than one rule (a $600 withdrawal that also carries a
    dishonour fee); each trip is its own line, because the underwriter is
    reading reasons, not rows.
    """
    rows: list[dict[str, Any]] = []
    for r in joined:
        if r.get("direction") == "info":
            continue
        description = str(r.get("description") or "")
        amount = abs(float(r.get("amount") or 0))
        hits: list[tuple[str, str, str]] = []

        for rule_id, pattern, severity, reason in _TEXT_RISK_RULES:
            if pattern.search(description):
                hits.append((rule_id, severity, reason))

        # Cash leaves no counterparty behind, so a large withdrawal is a hole
        # in the evidence rather than a proven problem: flag it for review,
        # never as `high`.
        if (
            r.get("direction") == "outflow"
            and amount > CASH_WITHDRAWAL_THRESHOLD_NZD
            and _CASH_RE.search(description)
        ):
            hits.append(
                (
                    "cash_withdrawal_over_500",
                    "review",
                    f"cash withdrawal over ${CASH_WITHDRAWAL_THRESHOLD_NZD:,.0f} "
                    "- no counterparty is recorded for this spend",
                )
            )

        model_flag = str(r.get("risk_flag") or "").strip().lower()
        if model_flag in _MODEL_RISK_RULES:
            hits.append((model_flag, "review", _MODEL_RISK_REASONS[model_flag]))

        for rule_id, severity, reason in hits:
            rows.append(
                {
                    "transaction_id": str(r.get("transaction_id") or ""),
                    "date": str(r.get("date") or ""),
                    "description": description,
                    "amount_nzd": round(amount, 2),
                    "rule_id": rule_id,
                    "severity": severity,
                    "reason": reason,
                }
            )

    rows.sort(key=lambda x: (x["severity"] != "high", x["date"], x["rule_id"]))
    return rows


CATEGORY_LABELS: dict[str, str] = {
    "transport": "Transport",
    "utilities": "Utilities",
    "insurance": "Insurance (combined)",
    "food_grocery_clothing_personal_care": "Food / grocery / clothing / personal care",
    "recreation_entertainment": "Recreation and entertainment",
    "monthly_subscriptions": "Monthly subscriptions",
    "education": "Education",
    "kiwisaver_savings_investments": "KiwiSaver and savings",
    "childcare_child_support": "Childcare and child support",
    "donations_tithings": "Donations / tithings",
    "rent_board_paid": "Rent / board paid",
    "medical": "Medical",
    "extracurricular": "Extracurricular",
    "other": "Other",
    "one_off": "One-off",
}

POLICY_BUCKETS = ("essential", "discretionary", "savings_giving", "excluded", "manual")

NON_HOUSEHOLD_CATEGORIES = frozenset(
    {
        "internal_transfer",
        "credit_card_repayment",
        "loan_repayment",
        "mortgage_repayment",
        "interest_charge",
        "redraw",
        "reimbursement",
        "income_credit",
        "salary_wages",
        "benefit",
        "child_support_received",
        "rental_income",
        "investment_income",
        "other_income",
        "business_receipts",
        "underwriter_manual",
        "unclear",
        "one_off",
    }
)

CASH_WITHDRAWAL_RE = re.compile(
    r"\b(?:ATM\s*W/?D|CASH\s*(?:WITHDRAWAL|W/?D)|ATM\s+WITHDRAWAL)\b",
    re.IGNORECASE,
)

_CASH_RE = CASH_WITHDRAWAL_RE  # see the note beside _TEXT_RISK_RULES

RECONCILE_TOLERANCE = 0.05


def is_cash_withdrawal(description: str) -> bool:
    return bool(CASH_WITHDRAWAL_RE.search(str(description or "")))


def policy_bucket(category: str, description: str = "") -> str:
    if is_cash_withdrawal(description):
        return "manual"
    if category == "other":
        return "manual"
    return CATEGORY_POLICY.get(str(category or ""), "manual")


def mask_account_label(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return "••••"
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 4:
        return "••••" + digits[-4:]
    if digits:
        return "••••" + digits
    return "••••"


def _amount(row: dict[str, Any]) -> float:
    return abs(float(row.get("amount") or 0))


def _usable(row: dict[str, Any]) -> bool:
    return row.get("direction") != "info" and not row.get("extract_duplicate")


def is_household_outflow(row: dict[str, Any]) -> bool:
    if not _usable(row) or row.get("direction") != "outflow":
        return False
    if str(row.get("is_business") or "no").strip().lower() == "yes":
        return False
    return str(row.get("category") or "") not in NON_HOUSEHOLD_CATEGORIES


def _parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _observation_months(accounts: list[dict[str, Any]], joined: list[dict[str, Any]]) -> float:
    windows: list[tuple[date, date]] = []
    for account in accounts:
        start = _parse_iso_date(account.get("period_start"))
        end = _parse_iso_date(account.get("period_end"))
        if start and end and end >= start:
            windows.append((start, end))
    if not windows:
        dates = [_parse_iso_date(r.get("date")) for r in joined]
        dates = [d for d in dates if d]
        if dates:
            windows.append((min(dates), max(dates)))
    if not windows:
        return 1.0
    start = min(w[0] for w in windows)
    end = max(w[1] for w in windows)
    return max(((end - start).days + 1) / 30.436875, 1.0)


def _as_date(value: Any, fallback: str) -> str:
    parsed = _parse_iso_date(value)
    return parsed.isoformat() if parsed else fallback


def _reconcile_account(account: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    opening = account.get("opening_balance")
    closing = account.get("closing_balance")
    inflows = round(sum(_amount(r) for r in rows if r.get("direction") == "inflow"), 2)
    outflows = round(sum(_amount(r) for r in rows if r.get("direction") == "outflow"), 2)
    aid = str(account.get("account_id") or "unknown")
    rec = {
        "account_id": aid,
        "status": "not_assessable",
        "opening_balance_nzd": None if opening is None else float(opening),
        "total_inflows_nzd": inflows,
        "total_outflows_nzd": outflows,
        "expected_closing_balance_nzd": None,
        "reported_closing_balance_nzd": None if closing is None else float(closing),
        "difference_nzd": None,
    }
    if opening is None or closing is None:
        return rec
    try:
        open_n = float(opening)
        close_n = float(closing)
    except (TypeError, ValueError):
        return rec
    expected = round(open_n + inflows - outflows, 2)
    diff = round(expected - close_n, 2)
    rec.update(
        {
            "expected_closing_balance_nzd": expected,
            "reported_closing_balance_nzd": close_n,
            "difference_nzd": diff,
            "status": "balanced" if abs(diff) <= RECONCILE_TOLERANCE else "out_of_balance",
        }
    )
    return rec


def _ensure_accounts(
    accounts: list[dict[str, Any]],
    joined: list[dict[str, Any]],
    fallback_date: str,
) -> list[dict[str, Any]]:
    if accounts:
        return accounts
    source = next((str(r.get("source_file") or "") for r in joined if r.get("source_file")), "unknown")
    return [
        {
            "account_id": "unknown",
            "account_label": None,
            "institution": "Unknown",
            "period_start": fallback_date,
            "period_end": fallback_date,
            "opening_balance": None,
            "closing_balance": None,
            "source_file": source,
        }
    ]


def _part1_monthly_by_id(summary: dict[str, Any]) -> dict[str, float]:
    """Join Part 1 monthly figures by category id, never by display label.

    Part 1 labels carry suffixes such as `` (NOT in recommended)``. Using the
    short report_view label as a dict key silently zeros KiwiSaver/donations.
    """
    from compute_summary import PART1_ROWS

    by_label = {
        str(row.get("category")): float(row.get("monthly_equivalent") or 0)
        for row in (summary.get("part1") or [])
    }
    return {key: by_label.get(label, 0.0) for key, label in PART1_ROWS}


def _part1_total(summary: dict[str, Any], label: str) -> float:
    for row in summary.get("part1") or []:
        if row.get("category") == label:
            return float(row.get("monthly_equivalent") or 0)
    return 0.0


def build_report_view(
    canonical: dict[str, Any],
    joined: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    assessment = str(canonical.get("assessment_date") or summary.get("assessment_date") or "1970-01-01")[:10]
    accounts = _ensure_accounts(accounts, joined, assessment)
    usable = [r for r in joined if _usable(r)]
    total_inflows = round(sum(_amount(r) for r in usable if r.get("direction") == "inflow"), 2)
    total_outflows = round(sum(_amount(r) for r in usable if r.get("direction") == "outflow"), 2)
    household = [r for r in usable if is_household_outflow(r)]
    denominator = round(sum(_amount(r) for r in household), 2)

    by_category: dict[str, float] = defaultdict(float)
    for row in household:
        by_category[str(row.get("category") or "other")] += _amount(row)

    id_monthly = _part1_monthly_by_id(summary)
    rows = []
    essential_nzd = 0.0
    discretionary_nzd = 0.0
    for category, bucket in CATEGORY_POLICY.items():
        observed = round(by_category.get(category, 0.0), 2)
        if bucket == "essential":
            essential_nzd += observed
        elif bucket == "discretionary":
            discretionary_nzd += observed
        percent = round((observed / denominator) * 100, 2) if denominator else 0.0
        label = CATEGORY_LABELS[category]
        rows.append(
            {
                "category": category,
                "label": label,
                "observed_total_nzd": observed,
                "monthly_equivalent_nzd": round(id_monthly.get(category, 0.0), 2),
                "percent_of_denominator": percent,
                "policy_bucket": bucket,
                "essential": bucket == "essential",
            }
        )

    rows_by_account: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in usable:
        aid = str(row.get("account_id") or "")
        if aid:
            rows_by_account[aid].append(row)

    reconciliations = []
    exceptions = []
    for account in accounts:
        rec = _reconcile_account(account, rows_by_account.get(str(account.get("account_id") or ""), []))
        reconciliations.append(rec)
        if rec["status"] == "out_of_balance":
            exceptions.append(
                {
                    "type": "reconciliation",
                    "severity": "error",
                    "description": (
                        f"opening + inflows − outflows != closing by {rec['difference_nzd']}"
                    ),
                    "evidence": f"account_id={rec['account_id']} difference_nzd={rec['difference_nzd']}",
                }
            )
        elif rec["status"] == "not_assessable":
            exceptions.append(
                {
                    "type": "reconciliation",
                    "severity": "review",
                    "description": "opening_balance or closing_balance is null — not treated as balanced",
                    "evidence": f"account_id={rec['account_id']}",
                }
            )

    source_files = []
    institutions = []
    meta_accounts = []
    for account in accounts:
        src = account.get("source_file")
        if src and src not in source_files:
            source_files.append(str(src))
        inst = account.get("institution") or "Unknown"
        if inst not in institutions:
            institutions.append(str(inst))
        files = [str(src)] if src else [source_files[0] if source_files else "unknown"]
        meta_accounts.append(
            {
                "account_id": str(account.get("account_id") or "unknown"),
                "institution": str(inst),
                "masked_account": mask_account_label(account.get("account_label") or account.get("account_id")),
                "period_start": _as_date(account.get("period_start"), assessment),
                "period_end": _as_date(account.get("period_end"), assessment),
                "opening_balance_nzd": None if account.get("opening_balance") is None else float(account.get("opening_balance")),
                "closing_balance_nzd": None if account.get("closing_balance") is None else float(account.get("closing_balance")),
                "source_files": files,
            }
        )
    if not source_files:
        source_files = ["unknown"]
    if not institutions:
        institutions = ["Unknown"]

    starts = [_parse_iso_date(a.get("period_start")) for a in accounts]
    ends = [_parse_iso_date(a.get("period_end")) for a in accounts]
    starts = [d for d in starts if d]
    ends = [d for d in ends if d]
    period_start = min(starts).isoformat() if starts else assessment
    period_end = max(ends).isoformat() if ends else assessment

    allowed_income_types = {
        "salary_wages", "benefit", "child_support_received", "rental_income",
        "investment_income", "other_income", "business_receipts",
    }
    income_sources = []
    for row in summary.get("income") or []:
        income_type = str(row.get("type") or "other_income")
        if income_type == "side_business_gross_receipts":
            income_type = "business_receipts"
        elif income_type not in allowed_income_types:
            income_type = "other_income"
        frequency = str(row.get("frequency") or "unknown")
        regularity = row.get("regularity")
        if regularity not in {"regular", "irregular", "insufficient_observations", "not_assessable"}:
            regularity = (
                "not_assessable" if frequency == "unknown"
                else "insufficient_observations" if frequency == "one_off"
                else "irregular" if frequency == "irregular"
                else "regular"
            )
        income_sources.append(
            {
                "source": str(row.get("source") or "Unknown source"),
                "income_type": income_type,
                "dominant_amount_nzd": float(row.get("amount_observed") or 0),
                "frequency": frequency,
                "monthly_equivalent_nzd": float(row.get("monthly_equivalent") or 0),
                "regularity": regularity,
                "evidence": str(row.get("evidence") or "No dated evidence provided"),
            }
        )

    manual_review = {"unclear": [], "underwriter_manual": [], "business_review": []}
    ledger = []
    for row in summary.get("part2") or []:
        confidence = row.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            confidence = None
        ledger.append(
            {
                "transaction_id": str(row.get("transaction_id") or "unknown"),
                "date": _as_date(row.get("date"), assessment),
                "description": str(row.get("description") or "Not provided"),
                "amount_nzd": float(row.get("amount") or 0),
                "direction": row.get("direction") if row.get("direction") in {"inflow", "outflow", "info"} else "info",
                "category": str(row.get("category") or "unclear"),
                "source_file": str(row.get("source_file") or "unknown"),
                "merchant": row.get("merchant") or None,
                "confidence": confidence,
                "subcategory": row.get("subcategory") or None,
                # Audit trail: say how this name was arrived at, not how
                # confident we feel about it. See vendor_provenance().
                **dict(
                    zip(
                        ("vendor_source", "vendor_source_url"),
                        vendor_provenance(
                            str(row.get("merchant") or ""),
                            str(row.get("description") or ""),
                        ),
                    )
                ),
            }
        )
        review_type = row.get("review_type")
        if review_type in manual_review:
            manual_review[review_type].append(
                {
                    "review_type": review_type,
                    "transaction_id": str(row.get("transaction_id") or "unknown"),
                    "date": _as_date(row.get("date"), assessment),
                    "description": str(row.get("description") or "Not provided"),
                    "amount_nzd": float(row.get("amount") or 0),
                    "reason": str(row.get("reason") or row.get("exclusion_reason") or "Manual review required"),
                    "confidence": confidence,
                }
            )

    audit = summary.get("audit") or {}
    risk_rows = _risk_rows(joined)
    return {
        "meta": {
            "scope": "binder" if len(accounts) != 1 else "statement",
            "report_title": "Bank Statement Analysis Report",
            "source_files": source_files,
            "institutions": institutions,
            "masked_account": meta_accounts[0]["masked_account"] if len(meta_accounts) == 1 else None,
            "period_start": period_start,
            "period_end": period_end,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "accounts": meta_accounts,
        },
        "observed_cashflow": {
            "total_inflows_nzd": total_inflows,
            "total_outflows_nzd": total_outflows,
            "net_movement_nzd": round(total_inflows - total_outflows, 2),
            "observation_months": round(_observation_months(accounts, joined), 4),
            "reconciliations": reconciliations,
        },
        "servicing": {
            "assessable_income_monthly_nzd": float(audit.get("assessable_income_monthly") or 0),
            "recommended_living_monthly_nzd": float(summary.get("recommended_monthly_living") or 0),
            "savings_giving_monthly_nzd": _part1_total(summary, "TOTAL SAVINGS AND GIVING"),
            "business_expenses_monthly_nzd": float(summary.get("business_monthly") or 0),
            "side_business_gross_monthly_nzd": float(audit.get("side_business_gross_monthly") or 0),
        },
        "category_breakdown": {
            "denominator_nzd": denominator,
            "denominator_policy": "observed_household_outflows",
            "essential_percent": round((essential_nzd / denominator) * 100, 2) if denominator else 0.0,
            "discretionary_percent": round((discretionary_nzd / denominator) * 100, 2) if denominator else 0.0,
            "rows": rows,
        },
        "income_sources": income_sources,
        "recurring_commitments": [],
        "risk_flags": {"count": len(risk_rows), "rows": risk_rows},
        "manual_review": manual_review,
        "ledger": ledger,
        "exceptions": exceptions,
    }


def build_observed_fields(
    canonical: dict[str, Any],
    joined: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"report_view": build_report_view(canonical, joined, accounts, summary or {})}
