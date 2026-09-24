# -*- coding: utf-8 -*-
"""Merchant memory: what the model skips falls back to an accepted run.

On 2026-09-24 the Foundry model handed back 67 of 238 merchants and the
report came out 356/471 unclear. These tests pin the fallback that fixes
that, and the guards that keep it from overreaching: the model always wins,
applicant-specific entries never cross binders, and a stale normaliser key
cannot switch the memory off.
"""

from __future__ import annotations

import json
import re
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "function_app"))
# Appended, not prepended: pipeline/ has its own compute_summary.py shim, and
# it must not shadow the module that ships.
sys.path.append(HERE)

import compute_summary as cs  # noqa: E402
from build_merchant_memory import build  # noqa: E402

FILE_A = "applicant-a.pdf"
FILE_B = "applicant-b.pdf"


def _txn(tid, desc, amount, direction, source_file=FILE_A, date="2026-06-01"):
    return {
        "transaction_id": tid,
        "account_id": "a1",
        "date": date,
        "description": desc,
        "merchant_normalized": cs.normalize_merchant(desc),
        "amount": amount,
        "direction": direction,
        "source_file": source_file,
    }


def _canonical(txns):
    return {
        "assessment_date": "2026-09-24",
        "accounts": [
            {
                "account_id": "a1",
                "institution": "ANZ",
                "account_type": "everyday",
                "period_start": "2026-05-20",
                "period_end": "2026-08-19",
                "source_file": FILE_A,
            }
        ],
        "transactions": txns,
    }


class _Memory:
    """Point the engine at a throwaway memory file for one test."""

    def __init__(self, entries):
        self.entries = entries

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory()
        path = os.path.join(self.dir.name, "merchant_memory.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "entries": self.entries}, f)
        self.saved = cs.MERCHANT_MEMORY_PATH
        cs.MERCHANT_MEMORY_PATH = cs.Path(path)
        cs.load_merchant_memory.cache_clear()
        return self

    def __exit__(self, *exc):
        cs.MERCHANT_MEMORY_PATH = self.saved
        cs.load_merchant_memory.cache_clear()
        self.dir.cleanup()


DIDI = {
    "direction": "outflow", "category": "transport", "include_in_living_expenses": True,
    "is_business": "no", "reason": "ride-hail", "descriptors": ["DIDI_NZ Auckland"],
}
PAYER = {
    "direction": "inflow", "category": "business_receipts", "include_in_living_expenses": False,
    "is_business": "yes", "reason": "side-business gross receipts, not net profit",
    "income_type": "business_receipts", "descriptors": ["ZHAO,LILI Bun Lili"],
    "source_files": [FILE_A],
}
# Whether a subscription is a business expense is a judgement about one
# applicant, not about Anthropic, so an entry like this is still pinned to
# the files it was learned from. It is also not a person's name, which is
# what makes it the right fixture for testing the pin: payer_classification
# cannot answer it, so a leak would have nowhere else to come from.
PINNED_BRAND = {
    "direction": "outflow", "category": "monthly_subscriptions",
    "include_in_living_expenses": False, "is_business": "yes",
    "reason": "business tooling", "descriptors": ["ANTHROPIC ANTHROPIC.COMCA"],
    "source_files": [FILE_A],
}


def _run(txns, classifications=(), **extra):
    return cs.compute_summary(
        _canonical(list(txns)),
        {"assessment_date": "2026-09-24", "classifications": list(classifications), **extra},
    )


def _row(summary, tid):
    return next(r for r in summary["part2"] if r["transaction_id"] == tid)


def test_memory_fills_what_the_model_skipped():
    with _Memory([DIDI]):
        s = _run([_txn("t1", "DIDI_NZ Auckland", 12.55, "outflow")])
    row = _row(s, "t1")
    assert row["category"] == "transport", row
    assert row["reason"].startswith("merchant memory:"), row["reason"]
    assert s["audit"]["join_miss_rows"] == 0
    assert s["audit"]["memory_filled_rows"] == 1
    print("ok test_memory_fills_what_the_model_skipped")


def test_the_model_always_wins_over_memory():
    model = {"merchant": "DIDI_NZ", "category": "other", "include_in_living_expenses": False,
             "confidence": 0.8, "reason": "model said so"}
    with _Memory([DIDI]):
        s = _run([_txn("t1", "DIDI_NZ Auckland", 12.55, "outflow")], [model])
    row = _row(s, "t1")
    assert row["category"] == "other" and row["reason"] == "model said so", row
    assert s["audit"]["memory_filled_rows"] == 0
    print("ok test_the_model_always_wins_over_memory")


def test_applicant_specific_entries_never_cross_binders():
    """A pinned judgement is a fact about one applicant, not the merchant."""
    with _Memory([PINNED_BRAND]):
        same = _run([_txn("t1", "ANTHROPIC ANTHROPIC.COMCA", 40.0, "outflow", FILE_A)])
        other = _run([_txn("t1", "ANTHROPIC ANTHROPIC.COMCA", 40.0, "outflow", FILE_B)])
    assert _row(same, "t1")["category"] == "monthly_subscriptions", _row(same, "t1")
    assert _row(other, "t1")["category"] == "unclear", _row(other, "t1")
    assert other["audit"]["memory_filled_rows"] == 0
    print("ok test_applicant_specific_entries_never_cross_binders")


def test_a_payer_name_is_answered_on_a_binder_memory_never_saw():
    """The whole point of the rule: it does not need to have met the payer.

    The memory file used to carry 94 of this applicant's payers by name. That
    could never help the next applicant, whose payers are different people,
    so the names came out and this rule went in. Memory is empty here on
    purpose - nothing is remembered about ZHAO,LILI at all.
    """
    with _Memory([DIDI]):
        s = _run([_txn("t1", "ZHAO,LILI Bun Lili", 40.0, "inflow", FILE_B)])
    row = _row(s, "t1")
    assert row["category"] == "business_receipts", row
    assert row["is_business"] == "yes", row
    assert row["reason"].startswith("payer name:"), row["reason"]
    assert s["audit"]["memory_filled_rows"] == 0, s["audit"]
    assert s["audit"]["payer_name_filled_rows"] == 1, s["audit"]
    print("ok test_a_payer_name_is_answered_on_a_binder_memory_never_saw")


def test_the_same_name_leaving_is_not_revenue():
    """An outflow to a person is the applicant paying somebody."""
    with _Memory([DIDI]):
        s = _run([_txn("t1", "ZHAO,LILI Bun Lili", 40.0, "outflow", FILE_B)])
    row = _row(s, "t1")
    assert row["category"] == "unclear", row
    print("ok test_the_same_name_leaving_is_not_revenue")


def test_shipped_memory_file_carries_nothing_about_an_applicant():
    """The reviewed exception file must carry no applicant information."""
    from extract_normalize import looks_like_payer_name

    raw = json.load(open(os.path.join(ROOT, "function_app", "merchant_memory.json"), encoding="utf-8"))
    entries = raw["entries"]
    named = [e["key"] for e in entries if looks_like_payer_name(e["key"])]
    assert not named, named
    described = [d for e in entries for d in e.get("descriptors", []) if looks_like_payer_name(d)]
    assert not described, described
    assert not [e for e in entries if e.get("source_files")], "source_files leak statement filenames"
    assert not [e for e in entries if e["direction"] == "inflow"], "inflows are the applicant's income"
    assert not [e for e in entries if e["category"] == "business_receipts"]
    blob = json.dumps(raw, ensure_ascii=False)
    for pattern in (r"\d{4,6}\s*\*{2,}\s*\d{2,4}", r"\b\d{2}-\d{4}-\d{7}", r"\.pdf"):
        assert not re.search(pattern, blob, re.I), pattern
    print(
        "ok test_shipped_memory_file_carries_nothing_about_an_applicant "
        f"({len(entries)} approved exceptions)"
    )


def test_a_household_shop_travels_to_any_binder():
    with _Memory([DIDI]):
        s = _run([_txn("t1", "DIDI_NZ Auckland", 12.55, "outflow", FILE_B)])
    assert _row(s, "t1")["category"] == "transport"
    print("ok test_a_household_shop_travels_to_any_binder")


def test_direction_is_part_of_the_key():
    """The same name paying in is takings; paying out is not."""
    with _Memory([PAYER]):
        s = _run([_txn("t1", "ZHAO,LILI Bun Lili", 40.0, "outflow", FILE_A)])
    assert _row(s, "t1")["category"] == "unclear"
    print("ok test_direction_is_part_of_the_key")


def test_descriptors_are_rekeyed_with_todays_normaliser():
    """The 09-17 key was 'DE HE TANG CH- :'; today's normaliser drops '- :'.
    Memory stores the descriptor, so the change does not switch it off."""
    entry = {**DIDI, "category": "recreation_entertainment", "key": "DE HE TANG CH- :",
             "descriptors": ["POS W/D DE HE TANG CH-12:44"]}
    with _Memory([entry]):
        s = _run([_txn("t1", "POS W/D DE HE TANG CH-19:02", 63.0, "outflow")])
    assert _row(s, "t1")["category"] == "recreation_entertainment", _row(s, "t1")
    print("ok test_descriptors_are_rekeyed_with_todays_normaliser")


def test_two_entries_that_fold_together_and_disagree_are_dropped():
    """Both descriptors fold to 'PAK SAVE' and disagree, so that key is a
    guess and goes. An exact descriptor seen in the accepted run is still
    evidence and still matches; a new spelling that only reaches the
    ambiguous folded key is left to the model."""
    a = {**DIDI, "descriptors": ["PAK N SAVE W 483561 ****** 7996 C"]}
    b = {**DIDI, "category": "food_grocery_clothing_personal_care",
         "descriptors": ["PAK SAVE W"]}
    with _Memory([a, b]):
        s = _run([
            _txn("t1", "PAK N SAVE W 483561 ****** 7996 C", 88.0, "outflow"),
            _txn("t2", "PAK N SAVE W 483561 ****** 7996 Orig date 04/07/2026", 90.0, "outflow",
                 date="2026-07-06"),
        ])
    assert _row(s, "t1")["category"] == "transport", _row(s, "t1")
    assert _row(s, "t2")["category"] == "unclear", _row(s, "t2")
    print("ok test_two_entries_that_fold_together_and_disagree_are_dropped")


def test_memory_can_be_switched_off():
    with _Memory([DIDI]):
        s = _run([_txn("t1", "DIDI_NZ Auckland", 12.55, "outflow")], use_merchant_memory=False)
    assert _row(s, "t1")["category"] == "unclear"
    print("ok test_memory_can_be_switched_off")


def test_builder_learns_only_what_is_safe_to_replay():
    canonical = {"transactions": [
        _txn("t1", "DIDI_NZ Auckland", 12.55, "outflow"),
        _txn("t2", "ZHAO,LILI Bun Lili", 40.0, "inflow"),
        _txn("t3", "Mystery Co", 9.0, "outflow"),
        _txn("t4", "WESTLAKE GIRLS HIGH SCH", 70.0, "outflow"),
        _txn("t5", "FU MARKET", 10.0, "outflow", date="2026-06-02"),
        _txn("t6", "FU MARKET", 11.0, "outflow", date="2026-06-03"),
    ]}
    part2 = [
        {"transaction_id": "t1", "classified": True, "category": "transport", "include": True, "is_business": "no", "reason": "ride-hail"},
        {"transaction_id": "t2", "classified": True, "category": "business_receipts", "include": False, "is_business": "yes", "reason": "takings"},
        {"transaction_id": "t3", "classified": True, "category": "unclear", "include": False, "is_business": "no", "reason": "?"},
        {"transaction_id": "t4", "classified": True, "category": "education_childcare", "include": True, "is_business": "no", "reason": "school"},
        {"transaction_id": "t5", "classified": True, "category": "food_grocery_clothing_personal_care", "include": True, "is_business": "no", "reason": "grocer"},
        {"transaction_id": "t6", "classified": True, "category": "recreation_entertainment", "include": True, "is_business": "no", "reason": "cafe"},
    ]
    unapproved = build(canonical, {"part2": part2}, "test")
    assert unapproved["entries"] == [], unapproved["entries"]

    memory = build(canonical, {"part2": part2}, "test", {"DIDI_NZ"})
    by_cat = {e["category"]: e for e in memory["entries"]}
    # The payer is no longer learned at all. It used to be written out
    # pinned to FILE_A, which made the file a record of who paid this
    # applicant and helped no other binder; the rule answers it instead.
    assert set(by_cat) == {"transport"}, set(by_cat)
    assert "source_files" not in by_cat["transport"], "a shop should travel"
    assert not [e for e in memory["entries"] if e.get("source_files")], memory["entries"]
    assert memory["unapproved_or_applicant_specific_skipped"] == 1
    assert memory["approved_exception_keys"] == ["DIDI_NZ"]
    assert memory["retired_categories_skipped_count"] == 1
    assert memory["conflicts_skipped_count"] == 1  # FU MARKET, two categories
    print("ok test_builder_learns_only_what_is_safe_to_replay")


def test_shipped_memory_file_loads_and_only_uses_live_categories():
    cs.load_merchant_memory.cache_clear()
    memory = cs.load_merchant_memory()
    schema = json.load(open(os.path.join(ROOT, "schemas", "classification.schema.json"), encoding="utf-8"))
    allowed = set(schema["$defs"]["category"]["enum"]) - {"unclear"}
    # No merchant has yet been approved as a genuinely exceptional product
    # rule. Empty is safer than silently learning one applicant's shops.
    bad = {e["category"] for e in memory.values()} - allowed
    assert not bad, bad
    print(f"ok test_shipped_memory_file_loads_and_only_uses_live_categories ({len(memory)} keys)")


if __name__ == "__main__":
    test_memory_fills_what_the_model_skipped()
    test_the_model_always_wins_over_memory()
    test_applicant_specific_entries_never_cross_binders()
    test_a_payer_name_is_answered_on_a_binder_memory_never_saw()
    test_the_same_name_leaving_is_not_revenue()
    test_shipped_memory_file_carries_nothing_about_an_applicant()
    test_a_household_shop_travels_to_any_binder()
    test_direction_is_part_of_the_key()
    test_descriptors_are_rekeyed_with_todays_normaliser()
    test_two_entries_that_fold_together_and_disagree_are_dropped()
    test_memory_can_be_switched_off()
    test_builder_learns_only_what_is_safe_to_replay()
    test_shipped_memory_file_loads_and_only_uses_live_categories()
    print("ALL PASS")
