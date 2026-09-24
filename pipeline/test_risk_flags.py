# -*- coding: utf-8 -*-
"""Risk flags, and who is allowed to raise each one.

Split by what can be proven. A dishonour fee is a fee because the bank
printed the word on the line, and a $600 withdrawal is $600 whoever took
it - code decides those and must not defer to the model. Whether a shop is
a casino is not in the narrative, so the model answers that one, through a
closed enum, and its answer lands as `review` rather than as fact.

Every row these produce is shown to a loan underwriter as a flag against a
real applicant, so the tests below are mostly about NOT flagging.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "function_app"))

from report_view_fields import CASH_WITHDRAWAL_THRESHOLD_NZD, _risk_rows  # noqa: E402


def _row(desc, amount=10.0, direction="outflow", tid="t1", date="2026-06-01", **extra):
    row = {
        "transaction_id": tid,
        "date": date,
        "description": desc,
        "amount": amount,
        "direction": direction,
    }
    row.update(extra)
    return row


def _ids(rows):
    return [r["rule_id"] for r in rows]


def test_fees_are_found_in_the_statement_text_not_guessed():
    rows = _risk_rows(
        [
            _row("DISHONOUR FEE", 15.0, tid="a"),
            _row("UNARRANGED OVERDRAFT FEE", 9.0, tid="b"),
            _row("LATE PAYMENT FEE", 12.0, tid="c"),
        ]
    )
    assert set(_ids(rows)) == {"dishonour_fee", "overdraft_fee", "late_payment_fee"}
    # A fee is established by the document, so it is not a soft "review".
    assert all(r["severity"] == "high" for r in rows), rows
    print("ok test_fees_are_found_in_the_statement_text_not_guessed")


def test_ordinary_spending_is_not_flagged():
    """The expensive failure is a false flag, so pin the negative case hard."""
    rows = _risk_rows(
        [
            _row("PAK N SAVE WAIRAU", 210.55),
            _row("Direct Debit -PARTNERS LIFE LIMITED", 242.42),
            _row("PAY Barfoot & Thompson Limited", 2880.00),
            _row("Direct Credit ATOM DATA NZ LIMITED", 3500.00, direction="inflow"),
            _row("SMALES FARM PARKING AUCKLAND", 5.13),
        ]
    )
    assert rows == [], rows
    print("ok test_ordinary_spending_is_not_flagged")


def test_large_cash_is_review_not_high_because_cash_proves_nothing():
    rows = _risk_rows([_row("ATM W/D Wairau Park A-20:49", 600.00)])
    assert _ids(rows) == ["cash_withdrawal_over_500"], rows
    assert rows[0]["severity"] == "review", rows[0]
    assert "no counterparty" in rows[0]["reason"]
    print("ok test_large_cash_is_review_not_high_because_cash_proves_nothing")


def test_cash_threshold_is_a_boundary_not_a_vibe():
    assert _risk_rows([_row("ATM W/D LOCAL", CASH_WITHDRAWAL_THRESHOLD_NZD)]) == []
    assert _ids(_risk_rows([_row("ATM W/D LOCAL", CASH_WITHDRAWAL_THRESHOLD_NZD + 0.01)])) == [
        "cash_withdrawal_over_500"
    ]
    print("ok test_cash_threshold_is_a_boundary_not_a_vibe")


def test_a_large_card_purchase_is_not_a_cash_withdrawal():
    """$900 of furniture is not cash. Only withdrawals count."""
    assert _risk_rows([_row("BIG FURNITURE STORE AUCKLAND", 900.0)]) == []
    print("ok test_a_large_card_purchase_is_not_a_cash_withdrawal")


def test_pos_wd_at_a_named_merchant_is_a_purchase_not_cash():
    """Kiwibank prints card purchases as `POS W/D <merchant>`.

    Matching a bare `W/D` flagged a $612 invoice at a named wholesaler as an
    unexplained cash withdrawal - a false flag on a real applicant's file.
    """
    for descriptor in (
        "POS W/D GILMOURS NOR WHOLESALE",
        "POS W/D SWEET TALK CA-13:30",
        "POS W/D CLAUDE.AI SUBSCRIPTION ANTHROPIC.COMCAUS",
    ):
        assert _risk_rows([_row(descriptor, 612.0)]) == [], descriptor
    print("ok test_pos_wd_at_a_named_merchant_is_a_purchase_not_cash")


def test_real_cash_still_flags():
    """The fix above must not silence the case the rule exists for."""
    for descriptor in ("ATM W/D Wairau Park A-20:49", "CASH WITHDRAWAL BRANCH"):
        assert _ids(_risk_rows([_row(descriptor, 600.0)])) == [
            "cash_withdrawal_over_500"
        ], descriptor
    print("ok test_real_cash_still_flags")


def test_risk_and_living_expense_rules_share_one_cash_pattern():
    """Two patterns for one idea drift apart; assert they are the same object."""
    from report_view_fields import CASH_WITHDRAWAL_RE, _CASH_RE

    assert _CASH_RE is CASH_WITHDRAWAL_RE
    print("ok test_risk_and_living_expense_rules_share_one_cash_pattern")


def test_large_cash_INflow_is_not_flagged():
    """Money arriving is not an unexplained spend."""
    assert _risk_rows([_row("ATM DEPOSIT", 900.0, direction="inflow")]) == []
    print("ok test_large_cash_INflow_is_not_flagged")


def test_balance_lines_are_never_flagged():
    assert _risk_rows([_row("OPENING BALANCE", 0.0, direction="info")]) == []
    print("ok test_balance_lines_are_never_flagged")


def test_model_may_raise_only_the_three_merchant_nature_flags():
    rows = _risk_rows(
        [
            _row("SKYCITY AUCKLAND", 120.0, tid="g", risk_flag="gambling"),
            _row("QUICK CASH LOANS", 80.0, tid="p", risk_flag="payday_high_cost_lending"),
            _row("AFTERPAY LATE", 10.0, tid="b", risk_flag="bnpl_arrears"),
        ]
    )
    assert set(_ids(rows)) == {"gambling", "payday_high_cost_lending", "bnpl_arrears"}
    # The model is not a document. Its opinion is never `high`.
    assert all(r["severity"] == "review" for r in rows), rows
    print("ok test_model_may_raise_only_the_three_merchant_nature_flags")


def test_model_cannot_raise_a_fee_or_cash_flag():
    """Otherwise the model double-counts what code already established."""
    rows = _risk_rows(
        [
            _row("SOME SHOP", 10.0, tid="x", risk_flag="dishonour_fee"),
            _row("SOME SHOP", 10.0, tid="y", risk_flag="cash_withdrawal_over_500"),
        ]
    )
    assert rows == [], rows
    print("ok test_model_cannot_raise_a_fee_or_cash_flag")


def test_invented_flag_values_are_dropped_not_rendered():
    rows = _risk_rows(
        [
            _row("SOME SHOP", 10.0, tid="x", risk_flag="looks_dodgy"),
            _row("SOME SHOP", 10.0, tid="y", risk_flag=""),
            _row("SOME SHOP", 10.0, tid="z", risk_flag=None),
        ]
    )
    assert rows == [], rows
    print("ok test_invented_flag_values_are_dropped_not_rendered")


def test_one_row_can_trip_two_rules_and_reports_both():
    rows = _risk_rows([_row("ATM W/D CASINO DISHONOUR FEE", 600.0, tid="m")])
    assert set(_ids(rows)) == {"dishonour_fee", "cash_withdrawal_over_500"}
    assert all(r["transaction_id"] == "m" for r in rows)
    print("ok test_one_row_can_trip_two_rules_and_reports_both")


def test_high_severity_sorts_above_review():
    rows = _risk_rows(
        [
            _row("ATM W/D LOCAL", 600.0, tid="cash", date="2026-06-01"),
            _row("DISHONOUR FEE", 15.0, tid="fee", date="2026-07-01"),
        ]
    )
    assert rows[0]["rule_id"] == "dishonour_fee", _ids(rows)
    print("ok test_high_severity_sorts_above_review")


def test_rows_validate_against_the_T04_contract():
    """rule_id and severity are closed enums in schemas/report-view.schema.json."""
    schema = json.load(
        open(os.path.join(ROOT, "schemas", "report-view.schema.json"), encoding="utf-8")
    )
    allowed_rules = set(schema["$defs"]["riskRuleId"]["enum"])
    allowed_sev = set(schema["$defs"]["riskSeverity"]["enum"])
    required = set(schema["$defs"]["riskFlag"]["required"])

    rows = _risk_rows(
        [
            _row("DISHONOUR FEE", 15.0, tid="a"),
            _row("ATM W/D LOCAL", 600.0, tid="b"),
            _row("SKYCITY", 50.0, tid="c", risk_flag="gambling"),
        ]
    )
    assert rows
    for r in rows:
        assert r["rule_id"] in allowed_rules, r
        assert r["severity"] in allowed_sev, r
        assert required <= set(r), (required - set(r), r)
    print("ok test_rows_validate_against_the_T04_contract")


if __name__ == "__main__":
    test_fees_are_found_in_the_statement_text_not_guessed()
    test_ordinary_spending_is_not_flagged()
    test_large_cash_is_review_not_high_because_cash_proves_nothing()
    test_cash_threshold_is_a_boundary_not_a_vibe()
    test_a_large_card_purchase_is_not_a_cash_withdrawal()
    test_pos_wd_at_a_named_merchant_is_a_purchase_not_cash()
    test_real_cash_still_flags()
    test_risk_and_living_expense_rules_share_one_cash_pattern()
    test_large_cash_INflow_is_not_flagged()
    test_balance_lines_are_never_flagged()
    test_model_may_raise_only_the_three_merchant_nature_flags()
    test_model_cannot_raise_a_fee_or_cash_flag()
    test_invented_flag_values_are_dropped_not_rendered()
    test_one_row_can_trip_two_rules_and_reports_both()
    test_high_severity_sorts_above_review()
    test_rows_validate_against_the_T04_contract()
    print("ALL PASS")
