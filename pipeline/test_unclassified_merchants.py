# -*- coding: utf-8 -*-
"""The join-miss rows have to come back with names attached.

`join_miss_rows` is a count. After the HTTP layer started dropping `part2`
so Foundry could ingest the response, a count was all the agent got: it
knew 91 rows had missed but not which merchants, so the repair pass had
nothing to re-classify. These tests pin the name list that fixes that, and
pin that it stays small enough to survive the slimming.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "function_app"))

from compute_summary import (  # noqa: E402
    UNCLASSIFIED_MERCHANT_CAP,
    compute_summary as _compute_summary,
    unclassified_merchants,
)


def compute_summary(canonical, classifications):
    """These tests pin the repair list itself. Merchant memory would fill the
    very rows they need to see missing (it knows Kogan Mobile), so it is off
    here; test_merchant_memory.py covers it."""
    return _compute_summary(canonical, {**classifications, "use_merchant_memory": False})


def _txn(tid, desc, amount, direction, date="2026-06-01"):
    return {
        "transaction_id": tid,
        "account_id": "a1",
        "date": date,
        "description": desc,
        "amount": amount,
        "direction": direction,
        "source_file": "s.pdf",
    }


def _canonical(txns):
    return {
        "assessment_date": "2026-09-21",
        "accounts": [
            {
                "account_id": "a1",
                "institution": "ANZ",
                "account_type": "everyday",
                "period_start": "2026-05-20",
                "period_end": "2026-08-19",
                "source_file": "s.pdf",
            }
        ],
        "transactions": txns,
    }


def test_unclassified_rows_come_back_with_merchant_names():
    """The whole point: a count is not actionable, a name list is."""
    canonical = _canonical(
        [
            _txn("t1", "Kogan Mobile YKYAYTQC Auckland", 11.90, "outflow"),
            _txn("t2", "Kogan Mobile 7WRVMQDR Auckland", 4.90, "outflow"),
            _txn("t3", "PAK N SAVE WAIRAU", 82.10, "outflow"),
        ]
    )
    # Only PAK N SAVE gets classified; the two Kogan rows miss the join.
    classifications = {
        "assessment_date": "2026-09-21",
        "classifications": [
            {
                "transaction_id": "t3",
                "category": "food_grocery_clothing_personal_care",
                "include_in_living_expenses": True,
                "confidence": 0.9,
                "reason": "supermarket",
            }
        ],
    }
    summary = compute_summary(canonical, classifications)
    audit = summary["audit"]

    assert audit["join_miss_rows"] == 2, audit["join_miss_rows"]

    names = audit["unclassified_merchants"]
    # The count alone was the bug. Assert we now ship the names too.
    assert names, "join_miss_rows > 0 but no merchant list to repair from"
    merchants = {entry["merchant"] for entry in names}
    assert any("KOGAN" in m.upper() for m in merchants), merchants
    # The row that WAS classified must not appear - otherwise a repair pass
    # re-classifies work already done and we are back to resending the world.
    assert not any("PAK N SAVE" in m.upper() for m in merchants), merchants
    print("ok test_unclassified_rows_come_back_with_merchant_names")


def test_repeated_merchant_collapses_to_one_entry_with_a_row_count():
    """91 rows must not become 91 entries, or we have re-created part2."""
    # Spread across dates: same-day identical rows are merged upstream, so
    # stacking them on one date would be testing the de-duplicator instead.
    txns = [
        _txn(
            f"t{i}",
            "NYX*HOOP33 LIMITED Auckland",
            2.80,
            "outflow",
            date=f"2026-06-{i + 1:02d}",
        )
        for i in range(12)
    ]
    summary = compute_summary(
        _canonical(txns), {"assessment_date": "2026-09-21", "classifications": []}
    )
    names = summary["audit"]["unclassified_merchants"]
    hoop = [e for e in names if "HOOP33" in e["merchant"].upper()]
    assert len(hoop) == 1, hoop
    assert hoop[0]["rows"] == 12, hoop[0]
    assert summary["audit"]["join_miss_rows"] == 12
    print("ok test_repeated_merchant_collapses_to_one_entry_with_a_row_count")


def test_direction_is_carried_because_it_changes_the_answer():
    """Same person's name: inflow is side-business takings, outflow is not.

    The inflow no longer reaches the worklist at all - payer_classification
    answers it from the shape of the name - so what this pins now is that the
    outflow is NOT answered the same way and is still asked about. Direction
    deciding the answer is the point either way.
    """
    summary = compute_summary(
        _canonical(
            [
                _txn("t1", "ZHANG,XIAOXIA BILL PAYMENT", 40.00, "inflow"),
                _txn("t2", "ZHANG,XIAOXIA BILL PAYMENT", 40.00, "outflow"),
            ]
        ),
        {"assessment_date": "2026-09-21", "classifications": []},
    )
    by_id = {r["transaction_id"]: r for r in summary["part2"]}
    assert by_id["t1"]["category"] == "business_receipts", by_id["t1"]
    assert by_id["t2"]["category"] == "unclear", by_id["t2"]
    names = summary["audit"]["unclassified_merchants"]
    directions = {e["direction"] for e in names if "ZHANG" in e["merchant"].upper()}
    assert directions == {"outflow"}, directions
    print("ok test_direction_is_carried_because_it_changes_the_answer")


def test_worklist_still_carries_both_directions_for_a_business():
    """A merchant the payer rule does not touch is asked about either way."""
    summary = compute_summary(
        _canonical(
            [
                _txn("t1", "NYX*HOOP33 LIMITED Auckland", 2.80, "inflow"),
                _txn("t2", "NYX*HOOP33 LIMITED Auckland", 2.80, "outflow"),
            ]
        ),
        {"assessment_date": "2026-09-21", "classifications": []},
    )
    names = summary["audit"]["unclassified_merchants"]
    directions = {e["direction"] for e in names if "HOOP33" in e["merchant"].upper()}
    assert directions == {"inflow", "outflow"}, directions
    print("ok test_worklist_still_carries_both_directions_for_a_business")


def test_info_rows_are_not_asked_about():
    """Balance lines are not transactions; 9f2d008 already settled that."""
    summary = compute_summary(
        _canonical(
            [
                _txn("t1", "OPENING BALANCE", 0.0, "info"),
                _txn("t2", "Wanyunet ltd", 40.00, "outflow"),
            ]
        ),
        {"assessment_date": "2026-09-21", "classifications": []},
    )
    names = summary["audit"]["unclassified_merchants"]
    assert not any("BALANCE" in e["merchant"].upper() for e in names), names
    assert summary["audit"]["join_miss_rows"] == 1
    print("ok test_info_rows_are_not_asked_about")


def test_list_is_capped_and_says_so_while_the_count_stays_true():
    """The list exists to fit in the tool channel. It must not grow unbounded."""
    txns = [
        _txn(f"t{i}", f"DISTINCT MERCHANT {i} AUCKLAND", 5.0 + i, "outflow")
        for i in range(UNCLASSIFIED_MERCHANT_CAP + 25)
    ]
    summary = compute_summary(
        _canonical(txns), {"assessment_date": "2026-09-21", "classifications": []}
    )
    audit = summary["audit"]
    assert len(audit["unclassified_merchants"]) == UNCLASSIFIED_MERCHANT_CAP
    assert audit["unclassified_merchants_truncated"] is True
    # Truncating the list must never quietly shrink the real number.
    assert audit["join_miss_rows"] == UNCLASSIFIED_MERCHANT_CAP + 25
    print("ok test_list_is_capped_and_says_so_while_the_count_stays_true")


def test_payload_stays_small_at_real_scale():
    """The reason part2 was dropped was size. Prove we did not undo that."""
    # 91 distinct unclassified merchants, the real number from Robin's run.
    txns = [
        _txn(f"t{i}", f"SOME MERCHANT NAME {i} SUBURB AUCKLAND NZL", 12.34, "outflow")
        for i in range(91)
    ]
    summary = compute_summary(
        _canonical(txns), {"assessment_date": "2026-09-21", "classifications": []}
    )
    names = summary["audit"]["unclassified_merchants"]
    size = len(json.dumps(names, separators=(",", ":")).encode("utf-8"))
    assert len(names) == 91, len(names)
    # part2 for 471 rows was ~335KB. The name list must stay in the low KBs.
    assert size < 12_000, f"repair list is {size} bytes, too big for the channel"
    print(f"ok test_payload_stays_small_at_real_scale ({size} bytes for 91 merchants)")


def test_helper_is_pure_and_handles_an_empty_join():
    assert unclassified_merchants([]) == []
    assert unclassified_merchants([{"classified": True}]) == []
    print("ok test_helper_is_pure_and_handles_an_empty_join")


if __name__ == "__main__":
    test_unclassified_rows_come_back_with_merchant_names()
    test_repeated_merchant_collapses_to_one_entry_with_a_row_count()
    test_direction_is_carried_because_it_changes_the_answer()
    test_worklist_still_carries_both_directions_for_a_business()
    test_info_rows_are_not_asked_about()
    test_list_is_capped_and_says_so_while_the_count_stays_true()
    test_payload_stays_small_at_real_scale()
    test_helper_is_pure_and_handles_an_empty_join()
    print("ALL PASS")
