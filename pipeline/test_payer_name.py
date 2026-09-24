# -*- coding: utf-8 -*-
"""Who paid the applicant is read from the name, not remembered by name.

The 2026-09-24 emergency fix put 94 of one applicant's payers into
merchant_memory.json by name. It worked for that binder and could never work
for another: the next applicant's side business is paid by different people.
So the names came out and `looks_like_payer_name` went in, and these tests
pin the two things that make it usable on a statement nobody has seen.

Recall, because a payer the rule misses lands back in `unclear` and an
underwriter has to categorise it by hand - the volume that made this
worth fixing.

Precision, because a merchant the rule mistakes for a person is counted as
side-business revenue. That is the expensive direction: it inflates income on
a lending assessment and quietly removes a living expense. `BIKES TAKA` and
`AT INFRINGEMENTS` are two capitalised words, exactly like a name, and the
only reason they are not read as people is that they carry none of the three
markers a bank prints around a real payer.
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "function_app"))

from extract_normalize import looks_like_payer_name  # noqa: E402

# Shapes taken from the 2026-08-19 ANZ and 2026-Aug-20 Kiwibank statements.
# Surnames are real surnames but these are shapes, not the applicant's actual
# payers - the point is the format, and the file they came from is the reason
# no list of them ships in the repo any more.
PAYERS = (
    "ZHANG,MENG",
    "ZHAO,LILI Bun Lili",
    "DENG,XIAOWEI BILL PAYMENT",
    "CHEN,CHENG BILL PAYMENT",
    "YANG,SICONG 41 nigel",
    "ZHANG, YIHUA 52C",
    "MRS J XIE 1",
    "MISS F LI emily",
    "MR Y LU AND qq qq qq",
    "MRS YI LIU Yi Yi",
    "MS Y LU 808",
    "C ZHANG",
    "WANG S ZHOU & Steven",
    "Q YU BILL PAYMENT",
)

NOT_PAYERS = (
    # Two capitalised words, no marker: the case the marker test exists for.
    "BIKES TAKA",
    "AT INFRINGEMENTS",
    "GOLDEN APPLE",
    "FU MARKET",
    "SHAKE OUT TAKAPUNA",
    # A trailing letter is the debit/credit indicator, not an initial.
    "Costco Whs Auckland C",
    "PAK N SAVE W",
    "WOOLWORTHS N",
    "PAPER PLUS S",
    "Lucky Bliss Tea C",
    # Z Energy forecourts, where `Z` would otherwise read as an initial.
    "Z LAKESIDE",
    "Z Lakeside Takapuna",
    # Named entities.
    "ATOM DATA NZ LIMITED",
    "IWG NEW ZEALAND",
    "BARFOOT & THOMPSON LIMITED",
    "WAIRAU INTERMEDIATE BOARD",
    "INLAND REVENUE",
    # A card processor's star prefix means the tail is a trading name.
    "SMZ*W S FOODSTUFF LTDb2Auckland",
    "NYX*HOOP33 LIMITED Auckland",
    # Brands and card rails.
    "ANTHROPIC / CLAUDE",
    "CURSOR.COM",
    "DIDI_NZ",
    "AGENT-ROOM.COM",
    "PAYPAL *SHENDUQRWEA",
    "",
    "   ",
)


def test_statement_payer_formats_are_recognised():
    missed = [p for p in PAYERS if not looks_like_payer_name(p)]
    assert not missed, missed
    print(f"ok test_statement_payer_formats_are_recognised ({len(PAYERS)} shapes)")


def test_merchants_are_not_mistaken_for_people():
    wrong = [m for m in NOT_PAYERS if looks_like_payer_name(m)]
    assert not wrong, wrong
    print(f"ok test_merchants_are_not_mistaken_for_people ({len(NOT_PAYERS)} names)")


def test_a_marker_is_required_so_a_bare_pair_of_words_is_not_a_person():
    """The deliberate miss, stated as a test so it is not 'fixed' by accident.

    `Steven Wang` is a person and reads as one to a human. Nothing in the text
    separates it from `Golden Apple`, so accepting it means accepting every
    two-word shop name as side-business revenue. It stays unrecognised, the
    row stays `unclear`, and an underwriter looks at it.
    """
    assert not looks_like_payer_name("Golden Apple")
    assert not looks_like_payer_name("Steven Wang")
    assert looks_like_payer_name("WANG,STEVEN")
    assert looks_like_payer_name("MR STEVEN WANG")
    assert looks_like_payer_name("S WANG")
    print("ok test_a_marker_is_required_so_a_bare_pair_of_words_is_not_a_person")


def test_a_payer_reference_is_not_part_of_the_name():
    """`52C` is what the payer typed, so it is stripped before testing."""
    assert looks_like_payer_name("ZHANG, YIHUA 52C")
    assert looks_like_payer_name("YANG,SICONG 41 nigel")
    # A descriptor that is mostly digits is not a name with a reference on it.
    assert not looks_like_payer_name("483561 7996")
    assert not looks_like_payer_name("4029357733 HK")
    print("ok test_a_payer_reference_is_not_part_of_the_name")


def test_the_predicate_is_pure_and_survives_junk():
    for value in (None, "", "   ", 0, 12.5, "x", "-", "A B", "A" * 200):
        looks_like_payer_name(value)
    assert looks_like_payer_name("ZHANG,MENG") is True
    assert looks_like_payer_name("FU MARKET") is False
    print("ok test_the_predicate_is_pure_and_survives_junk")


def test_no_payer_name_regex_carries_a_stray_control_character():
    """A literal backspace once made the whole merchant filter dead code.

    `\\b` written into a non-raw string is chr(8), and `re` matched it as a
    backspace the statement never contains, so `_NOT_A_PAYER` silently
    stopped rejecting anything - the tests still passed because the other
    checks happened to cover the same names. Byte-level, because the defect
    is invisible in a terminal.
    """
    source = open(
        os.path.join(ROOT, "function_app", "extract_normalize.py"), "rb"
    ).read()
    stray = sorted({b for b in source if b < 9 or b in (11, 12) or 14 <= b < 32})
    assert not stray, stray
    print("ok test_no_payer_name_regex_carries_a_stray_control_character")


def test_the_shipped_memory_holds_no_name_the_rule_would_recognise():
    """Belt and braces: approved merchant exceptions cannot be payer names."""
    path = os.path.join(ROOT, "function_app", "merchant_memory.json")
    raw = json.load(open(path, encoding="utf-8"))
    named = [
        e["key"] for e in raw["entries"] if looks_like_payer_name(e["key"])
    ]
    assert not named, named
    blob = json.dumps(raw, ensure_ascii=False)
    assert not re.search(r"\b(?:MR|MRS|MS|MISS)\s+[A-Z]", blob, re.I)
    print("ok test_the_shipped_memory_holds_no_name_the_rule_would_recognise")


if __name__ == "__main__":
    test_statement_payer_formats_are_recognised()
    test_merchants_are_not_mistaken_for_people()
    test_a_marker_is_required_so_a_bare_pair_of_words_is_not_a_person()
    test_a_payer_reference_is_not_part_of_the_name()
    test_the_predicate_is_pure_and_survives_junk()
    test_no_payer_name_regex_carries_a_stray_control_character()
    test_the_shipped_memory_holds_no_name_the_rule_would_recognise()
    print("ALL PASS")
