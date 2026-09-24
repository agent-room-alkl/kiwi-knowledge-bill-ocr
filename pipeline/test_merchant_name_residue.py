# -*- coding: utf-8 -*-
"""Merchant names must not reach the report as punctuation rubble.

`normalize_merchant` strips store numbers (`\\d{2,}`) and suburb words to get
`Pak N Save Wairau Road Northshore NZL` down to `PAK N SAVE`. On a Kiwibank
POS line those same rules eat the trailing timestamp and leave the separators
behind: `ATM W/D Wairau Park A-20:49` reached an underwriter's report as
`ATM W/D PARK A- :`, which names no shop at all.

These tests pin the cleanup AND pin that it did not change which rows group
together - the merchant key drives Part 5 top-10 and the "appears >= 3 times"
list, so a grouping change here silently moves reported figures.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "function_app"))

from extract_normalize import normalize_merchant  # noqa: E402


def test_stripped_timestamp_leaves_no_punctuation_rubble():
    cases = {
        "ATM W/D Wairau Park A-20:49": "ATM W/D PARK",
        "POS W/D DE HE TANG CH-12:44": "DE HE TANG CH",
        "POS W/D COCO FRESH TE-14:22": "COCO FRESH TE",
        "POS W/D PotXpress Nor-16:26": "POTXPRESS NOR",
        "POS W/D SWEET TALK CA-13:30": "SWEET TALK CA",
        "POS W/D THE HAMPER DE-16:10": "THE HAMPER DE",
    }
    for descriptor, expected in cases.items():
        got = normalize_merchant(descriptor)
        assert got == expected, f"{descriptor!r} -> {got!r}, wanted {expected!r}"
        # The actual bug signature: a separator with nothing beside it.
        assert not got.endswith(("-", ":", "/")), got
        assert " :" not in got and "- " not in got, got
    print("ok test_stripped_timestamp_leaves_no_punctuation_rubble")


def test_the_taxonomy_example_still_holds():
    """schemas/taxonomy.md documents this exact collapse. Do not break it."""
    assert normalize_merchant("Pak N Save Wairau Road Northshore NZL") == "PAK N SAVE"
    assert normalize_merchant("Pak N Save Glenfield Auckland NZL") == "PAK N SAVE"
    print("ok test_the_taxonomy_example_still_holds")


def test_ordinary_names_are_not_trimmed():
    """The cleanup must not start eating real trailing words."""
    for descriptor, expected in {
        "SMALES FARM PARKING AUCKLAND": "SMALES FARM PARKING",
        "Direct Debit -PARTNERS LIFE LIMITED": "PARTNERS LIFE LIMITED",
        "Farro Fresh Smales FarmAuckland": "FARRO FRESH SMALES FARMAUCKLAND",
    }.items():
        got = normalize_merchant(descriptor)
        assert got == expected, f"{descriptor!r} -> {got!r}, wanted {expected!r}"
    print("ok test_ordinary_names_are_not_trimmed")


def test_grouping_is_unchanged_across_times_at_the_same_shop():
    """Part 5 keys on this. Same shop, different minute = still one merchant."""
    keys = {
        normalize_merchant(d)
        for d in (
            "POS W/D SWEET TALK CA-13:30",
            "POS W/D SWEET TALK CA-16:20",
            "POS W/D SWEET TALK CA-09:05",
        )
    }
    assert len(keys) == 1, keys
    print("ok test_grouping_is_unchanged_across_times_at_the_same_shop")


def test_different_shops_do_not_collapse_into_one():
    """Cleaning must not over-merge - that would move money between merchants."""
    a = normalize_merchant("POS W/D SWEET TALK CA-13:30")
    b = normalize_merchant("POS W/D PANDA MART PA-13:38")
    c = normalize_merchant("POS W/D DE HE TANG CH-12:44")
    assert len({a, b, c}) == 3, (a, b, c)
    print("ok test_different_shops_do_not_collapse_into_one")


def test_a_name_that_is_only_rubble_does_not_become_empty_noise():
    """Degenerate input should not produce a lone separator as a merchant."""
    for junk in ("-", " - : ", "12:44", "POS W/D -20:49"):
        got = normalize_merchant(junk)
        assert got.strip(" -:/") == got, f"{junk!r} -> {got!r}"
    print("ok test_a_name_that_is_only_rubble_does_not_become_empty_noise")


if __name__ == "__main__":
    test_stripped_timestamp_leaves_no_punctuation_rubble()
    test_the_taxonomy_example_still_holds()
    test_ordinary_names_are_not_trimmed()
    test_grouping_is_unchanged_across_times_at_the_same_shop()
    test_different_shops_do_not_collapse_into_one()
    test_a_name_that_is_only_rubble_does_not_become_empty_noise()
    print("ALL PASS")
