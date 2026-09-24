# -*- coding: utf-8 -*-
"""Observed-period / policy fields aligned to T-04 report-view.schema.json."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "function_app"))

from pipeline.compute_summary import compute_summary
from compute_summary import _closed_subcategory, _income_regularity
from report_view_fields import (
    CATEGORY_POLICY,
    POLICY_BUCKETS,
    is_cash_withdrawal,
    mask_account_label,
    policy_bucket,
)

ASSESSMENT = "2026-08-31"
ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schemas" / "report-view.schema.json"


def _txn(i, date, desc, amount, direction, merchant=None, account_id="a1"):
    return {
        "transaction_id": i,
        "account_id": account_id,
        "date": date,
        "description": desc,
        "amount": amount,
        "direction": direction,
        "source_file": "FAKE.pdf",
        "merchant_normalized": merchant or desc,
    }


def _cls(i, category, include, freq="unknown", **extra):
    row = {
        "transaction_id": i,
        "category": category,
        "include_in_living_expenses": include,
        "confidence": 0.9,
        "reason": "test",
        "suggested_frequency": freq,
    }
    row.update(extra)
    return row


def test_category_policy_covers_exactly_15_living_ids():
    assert len(CATEGORY_POLICY) == 15
    assert set(CATEGORY_POLICY.values()) <= set(POLICY_BUCKETS)
    assert CATEGORY_POLICY["other"] == "manual"
    assert CATEGORY_POLICY["one_off"] == "excluded"
    assert policy_bucket("other", "RANDOM SHOP") == "manual"
    assert policy_bucket("recreation_entertainment", "CINEMA") == "discretionary"


def test_cash_withdrawal_is_never_discretionary():
    assert is_cash_withdrawal("ATM W/D QUEEN ST")
    assert is_cash_withdrawal("CASH WITHDRAWAL 200")
    assert policy_bucket("food_grocery_clothing_personal_care", "ATM W/D") == "manual"
    assert policy_bucket("recreation_entertainment", "ATM W/D WESTPAC") == "manual"


def test_mask_account_keeps_last_four_digits():
    assert mask_account_label("Card ending 4567") == "••••4567"
    assert mask_account_label("12-3456-7890123-00") == "••••2300"
    assert mask_account_label("") == "••••"
    assert mask_account_label("No digits here") == "••••"


def test_reconciliation_unbalanced_does_not_rewrite_closing():
    canonical = {
        "assessment_date": ASSESSMENT,
        "accounts": [
            {
                "account_id": "a1",
                "account_label": "Westpac 12345678",
                "institution": "Westpac",
                "opening_balance": 100.0,
                "closing_balance": 50.0,
                "period_start": "2026-06-01",
                "period_end": "2026-06-30",
                "source_file": "FAKE.pdf",
                "is_statement": True,
            }
        ],
        "transactions": [
            _txn("o1", "2026-06-02", "COUNTDOWN", 20.0, "outflow", "COUNTDOWN"),
        ],
    }
    classifications = {
        "assessment_date": ASSESSMENT,
        "classifications": [_cls("o1", "food_grocery_clothing_personal_care", True)],
    }
    out = compute_summary(canonical, classifications)
    rec = out["report_view"]["observed_cashflow"]["reconciliations"][0]
    assert rec["status"] == "out_of_balance"
    assert rec["opening_balance_nzd"] == 100.0
    assert rec["reported_closing_balance_nzd"] == 50.0
    assert rec["expected_closing_balance_nzd"] == 80.0
    assert rec["difference_nzd"] == 30.0
    assert out["accounts"][0]["closing_balance"] == 50.0
    assert any(e["type"] == "reconciliation" for e in out["report_view"]["exceptions"])


def test_reconciliation_null_opening_is_not_assessable():
    canonical = {
        "assessment_date": ASSESSMENT,
        "accounts": [
            {
                "account_id": "a1",
                "account_label": "ANZ 9999",
                "institution": "ANZ",
                "opening_balance": None,
                "closing_balance": 10.0,
                "period_start": "2026-06-01",
                "period_end": "2026-06-30",
                "source_file": "FAKE.pdf",
                "is_statement": True,
            }
        ],
        "transactions": [
            _txn("o1", "2026-06-02", "COUNTDOWN", 20.0, "outflow", "COUNTDOWN"),
        ],
    }
    classifications = {
        "assessment_date": ASSESSMENT,
        "classifications": [_cls("o1", "food_grocery_clothing_personal_care", True)],
    }
    out = compute_summary(canonical, classifications)
    rec = out["report_view"]["observed_cashflow"]["reconciliations"][0]
    assert rec["status"] == "not_assessable"
    assert rec["difference_nzd"] is None
    assert any(e["type"] == "reconciliation" for e in out["report_view"]["exceptions"])


def test_observed_totals_are_independent_of_monthly_equivalents():
    canonical = {
        "assessment_date": ASSESSMENT,
        "accounts": [],
        "transactions": [
            _txn("s1", "2026-06-03", "SALARY ACME", 4820, "inflow", "ACME"),
            _txn("g1", "2026-06-04", "COUNTDOWN", 92.4, "outflow", "COUNTDOWN"),
            _txn("x1", "2026-06-05", "INTERNAL XFER", 500, "outflow", "XFER"),
        ],
    }
    classifications = {
        "assessment_date": ASSESSMENT,
        "classifications": [
            _cls("s1", "salary_wages", False, "fortnightly"),
            _cls("g1", "food_grocery_clothing_personal_care", True),
            _cls("x1", "internal_transfer", False),
        ],
    }
    out = compute_summary(canonical, classifications)
    cash = out["report_view"]["observed_cashflow"]
    assert cash["total_inflows_nzd"] == 4820.0
    assert cash["total_outflows_nzd"] == 592.4
    assert cash["net_movement_nzd"] == round(4820.0 - 592.4, 2)
    assert cash["observation_months"] > 0
    breakdown = out["report_view"]["category_breakdown"]
    assert breakdown["denominator_policy"] == "observed_household_outflows"
    assert breakdown["denominator_nzd"] == 92.4
    food = next(r for r in breakdown["rows"] if r["category"] == "food_grocery_clothing_personal_care")
    assert food["observed_total_nzd"] == 92.4
    assert food["percent_of_denominator"] == 100.0
    assert food["policy_bucket"] == "essential"
    monthly = out["income"][0]["monthly_equivalent"]
    assert monthly != cash["total_inflows_nzd"]
    assert out["report_view"]["servicing"]["assessable_income_monthly_nzd"] == monthly


def test_report_accounts_are_masked_existing_accounts_are_not():
    canonical = {
        "assessment_date": ASSESSMENT,
        "accounts": [
            {
                "account_id": "a1",
                "account_label": "Card ending 4567",
                "institution": "Westpac",
                "opening_balance": 0,
                "closing_balance": 0,
                "period_start": "2026-06-01",
                "period_end": "2026-06-30",
                "source_file": "FAKE.pdf",
                "is_statement": True,
            }
        ],
        "applicant": {
            "full_name": "A Tester",
            "address": "1 Secret Lane",
            "ird": "123-456-789",
        },
        "transactions": [],
    }
    out = compute_summary(canonical, {"assessment_date": ASSESSMENT, "classifications": []})
    assert out["accounts"][0]["account_label"] == "Card ending 4567"
    assert out["report_view"]["meta"]["accounts"][0]["masked_account"] == "••••4567"
    assert out["applicant"]["address"] == "1 Secret Lane"


def test_savings_giving_monthly_is_not_silently_zeroed():
    """Part1 labels have '(NOT in recommended)'; join must use category id."""
    canonical = {
        "assessment_date": ASSESSMENT,
        "accounts": [
            {
                "account_id": "a1",
                "account_label": "Westpac 12345678",
                "institution": "Westpac",
                "opening_balance": 0,
                "closing_balance": 0,
                "period_start": "2026-06-01",
                "period_end": "2026-07-31",
                "source_file": "FAKE.pdf",
                "is_statement": True,
            }
        ],
        "transactions": [
            _txn("k1", "2026-07-14", "KIWISAVER IRD", 180, "outflow", "KIWISAVER IRD"),
            _txn("d1", "2026-06-24", "DONATION RED CROSS", 20, "outflow", "RED CROSS"),
        ],
    }
    classifications = {
        "assessment_date": ASSESSMENT,
        "classifications": [
            _cls("k1", "kiwisaver_savings_investments", True, "monthly"),
            _cls("d1", "donations_tithings", True, "monthly"),
        ],
    }
    out = compute_summary(canonical, classifications)
    ks_part1 = next(x for x in out["part1"] if str(x["category"]).startswith("KiwiSaver"))
    don_part1 = next(x for x in out["part1"] if str(x["category"]).startswith("Donations"))
    assert ks_part1["monthly_equivalent"] == 180
    assert don_part1["monthly_equivalent"] == 20
    savings_part1 = next(x for x in out["part1"] if x["category"] == "TOTAL SAVINGS AND GIVING")
    assert savings_part1["monthly_equivalent"] == 200

    rows = out["report_view"]["category_breakdown"]["rows"]
    ks = next(r for r in rows if r["category"] == "kiwisaver_savings_investments")
    don = next(r for r in rows if r["category"] == "donations_tithings")
    assert ks["monthly_equivalent_nzd"] == 180
    assert don["monthly_equivalent_nzd"] == 20
    assert ks["policy_bucket"] == "savings_giving"
    assert don["policy_bucket"] == "savings_giving"
    assert out["report_view"]["servicing"]["savings_giving_monthly_nzd"] == 200


def test_generated_report_view_matches_t04_schema():
    canonical = {
        "assessment_date": ASSESSMENT,
        "accounts": [
            {
                "account_id": "a1",
                "account_label": "Westpac 12345678",
                "institution": "Westpac",
                "opening_balance": 100.0,
                "closing_balance": 80.0,
                "period_start": "2026-06-01",
                "period_end": "2026-06-30",
                "source_file": "FAKE.pdf",
                "is_statement": True,
            }
        ],
        "transactions": [
            _txn("o1", "2026-06-02", "COUNTDOWN", 20.0, "outflow", "COUNTDOWN"),
        ],
    }
    classifications = {
        "assessment_date": ASSESSMENT,
        "classifications": [_cls("o1", "food_grocery_clothing_personal_care", True)],
    }
    view = compute_summary(canonical, classifications)["report_view"]
    assert set(view) == {
        "meta",
        "observed_cashflow",
        "servicing",
        "category_breakdown",
        "income_sources",
        "recurring_commitments",
        "risk_flags",
        "manual_review",
        "ledger",
        "exceptions",
    }
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
    if jsonschema is not None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(view)
        return
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        handle.write(json.dumps(view))
        generated = handle.name
    script = (
        f"$s = Get-Content -Raw -LiteralPath '{SCHEMA}'; "
        f"$j = Get-Content -Raw -LiteralPath '{generated}'; "
        "$ok = $j | Test-Json -Schema $s; if (-not $ok) { exit 1 }"
    )
    completed = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
    )
    Path(generated).unlink(missing_ok=True)
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_line_level_passthrough_review_lanes_subtypes_and_income_regularity():
    canonical = {
        "assessment_date": ASSESSMENT,
        "accounts": [{
            "account_id": "a1", "account_label": "ANZ 12345678", "institution": "ANZ",
            "opening_balance": 1000, "closing_balance": 1000,
            "period_start": "2026-06-01", "period_end": "2026-07-31",
            "source_file": "FAKE.pdf", "is_statement": True,
        }],
        "transactions": [
            _txn("u1", "2026-06-05", "MERCURY MONTHLY", 90, "outflow", "raw utility"),
            _txn("c1", "2026-06-06", "PERSON TRANSFER", 40, "outflow", "raw person"),
            _txn("m1", "2026-06-07", "MANUAL ITEM", 30, "outflow", "raw manual"),
            _txn("b1", "2026-06-08", "SHOP PURCHASE", 20, "outflow", "raw shop"),
            _txn("s1", "2026-06-30", "ACME SALARY MONTHLY", 3000, "inflow", "raw salary"),
            _txn("s2", "2026-07-31", "ACME SALARY MONTHLY", 3000, "inflow", "raw salary"),
            _txn("i1", "2026-07-10", "DIVIDEND", 50, "inflow", "raw dividend"),
        ],
    }
    classifications = {"assessment_date": ASSESSMENT, "classifications": [
        _cls("u1", "utilities", True, "monthly", confidence=0.73,
             merchant_normalized="Mercury Energy", utility_type="power"),
        _cls("c1", "unclear", False, confidence=0.31, reason="ambiguous person transfer"),
        _cls("m1", "underwriter_manual", False, confidence=0.55, reason="policy decision"),
        _cls("b1", "food_grocery_clothing_personal_care", True, confidence=0.88,
             is_business="review", business_reason="possible business purchase"),
        _cls("s1", "salary_wages", False, "monthly", merchant_normalized="ACME PAYROLL",
             income_type="salary_wages"),
        _cls("s2", "salary_wages", False, "monthly", merchant_normalized="ACME PAYROLL",
             income_type="salary_wages"),
        _cls("i1", "investment_income", False, "unknown", merchant_normalized="Dividend Co",
             income_type="investment_income"),
    ]}
    out = compute_summary(canonical, classifications)
    by_id = {row["transaction_id"]: row for row in out["part2"]}

    assert by_id["u1"]["merchant"] == "MERCURY ENERGY"
    assert by_id["u1"]["confidence"] == 0.73
    assert by_id["u1"]["subcategory"] == "power"
    assert _closed_subcategory({"category": "utilities", "utility_type": "model free text"}) is None
    assert by_id["c1"]["review_type"] == "unclear" and by_id["c1"]["needs_review"]
    assert by_id["m1"]["review_type"] == "underwriter_manual" and by_id["m1"]["needs_review"]
    assert by_id["b1"]["review_type"] == "business_review" and by_id["b1"]["needs_review"]

    income = {row["type"]: row for row in out["income"]}
    assert income["salary_wages"]["regularity"] == "regular"
    assert income["investment_income"]["frequency"] == "one_off"
    assert income["investment_income"]["regularity"] == "insufficient_observations"
    assert _income_regularity("unknown", 3) == "not_assessable"

    view = out["report_view"]
    assert next(row for row in view["ledger"] if row["transaction_id"] == "u1")["subcategory"] == "power"
    assert len(view["manual_review"]["unclear"]) == 1
    assert len(view["manual_review"]["underwriter_manual"]) == 1
    assert len(view["manual_review"]["business_review"]) == 1
    assert next(row for row in view["income_sources"] if row["income_type"] == "salary_wages")["regularity"] == "regular"
    import jsonschema
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(view)


if __name__ == "__main__":
    tests = [
        test_category_policy_covers_exactly_15_living_ids,
        test_cash_withdrawal_is_never_discretionary,
        test_mask_account_keeps_last_four_digits,
        test_reconciliation_unbalanced_does_not_rewrite_closing,
        test_reconciliation_null_opening_is_not_assessable,
        test_observed_totals_are_independent_of_monthly_equivalents,
        test_report_accounts_are_masked_existing_accounts_are_not,
        test_savings_giving_monthly_is_not_silently_zeroed,
        test_generated_report_view_matches_t04_schema,
        test_line_level_passthrough_review_lanes_subtypes_and_income_regularity,
    ]
    for fn in tests:
        fn()
        print("ok", fn.__name__)
    print("ALL PASS")
