# -*- coding: utf-8 -*-
"""The Source column is an audit trail, so it may only claim what happened.

Vikas's skill renders this column as a clickable link when a merchant was
identified from a register, and as plain text otherwise, with the rule
"never render a link you did not actually visit". We are offline, so the
only honest answers are `pattern` (a maintained rule recognised the
descriptor) and `unresolved` (bank furniture was stripped off raw text,
which identifies nobody).

The failure these tests guard is the tempting one: making the column look
populated by calling every row `pattern`. That would tell an underwriter a
name was verified when nothing verified it.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "function_app"))

from extract_normalize import vendor_provenance  # noqa: E402


def test_a_maintained_pattern_rule_reports_pattern():
    for merchant, descriptor in (
        ("ANTHROPIC / CLAUDE", "POS W/D CLAUDE.AI SUBSCRIPTION ANTHROPIC.COMCAUS"),
        ("CURSOR.COM", "POS W/D CURSOR, AI POWERED IDE CURSOR.COM CA"),
        ("IWG NEW ZEALAND", "IWG NEW ZEALAND MANAGEMAUCKLAND"),
        ("WOOLWORTHS", "COUNTDOWN GLENFIELD"),
        ("GOOGLE ADS", "Google ADS9346458813 Auckland"),
    ):
        source, url = vendor_provenance(merchant, descriptor)
        assert source == "pattern", (merchant, source)
        assert url is None, url
    print("ok test_a_maintained_pattern_rule_reports_pattern")


def test_a_name_nobody_recognised_stays_unresolved():
    """This is the honest answer for most rows, and it must stay honest."""
    for merchant, descriptor in (
        ("SMALES FARM PARKING", "SMALES FARM PARKING AUCKLAND"),
        ("DE HE TANG CH", "POS W/D DE HE TANG CH-12:44"),
        ("PARTNERS LIFE LIMITED", "Direct Debit -PARTNERS LIFE LIMITED"),
        ("", "POS W/D PAYPAL *SHENDUQRWEA 4029357733 HK"),
    ):
        source, url = vendor_provenance(merchant, descriptor)
        assert source == "unresolved", (merchant, source)
        assert url is None, url
    print("ok test_a_name_nobody_recognised_stays_unresolved")


def test_offline_never_claims_a_register_or_a_link():
    """No row may claim companies_office / nzbn / web while we are offline."""
    forbidden = {"companies_office", "nzbn", "web", "cache", "manual"}
    samples = [
        ("ANTHROPIC / CLAUDE", "CLAUDE.AI SUBSCRIPTION"),
        ("SMALES FARM PARKING", "SMALES FARM PARKING AUCKLAND"),
        ("", ""),
        ("SOMETHING ODD", " – weird unicode 中文"),
    ]
    for merchant, descriptor in samples:
        source, url = vendor_provenance(merchant, descriptor)
        assert source not in forbidden, (merchant, source)
        # The report only renders a link when there is a URL. There is none.
        assert url is None, (merchant, url)
    print("ok test_offline_never_claims_a_register_or_a_link")


def test_every_value_is_in_the_T04_enum():
    schema = json.load(
        open(os.path.join(ROOT, "schemas", "report-view.schema.json"), encoding="utf-8")
    )
    allowed = set(schema["$defs"]["vendorSource"]["enum"])
    for merchant, descriptor in (
        ("ANTHROPIC / CLAUDE", "CLAUDE.AI"),
        ("WHO KNOWS", "SOME SHOP"),
        ("", ""),
    ):
        source, _ = vendor_provenance(merchant, descriptor)
        assert source in allowed, (source, allowed)
    print("ok test_every_value_is_in_the_T04_enum")


def test_empty_input_does_not_crash_or_over_claim():
    assert vendor_provenance("", "") == ("unresolved", None)
    assert vendor_provenance(None, None) == ("unresolved", None)
    print("ok test_empty_input_does_not_crash_or_over_claim")


def test_the_descriptor_alone_can_carry_the_match():
    """The model may hand us a merchant name the alias table misses, while
    the raw descriptor still contains the recognisable token."""
    source, _ = vendor_provenance("SUBSCRIPTION", "POS W/D CLAUDE.AI SUBSCRIPTION")
    assert source == "pattern", source
    print("ok test_the_descriptor_alone_can_carry_the_match")


if __name__ == "__main__":
    test_a_maintained_pattern_rule_reports_pattern()
    test_a_name_nobody_recognised_stays_unresolved()
    test_offline_never_claims_a_register_or_a_link()
    test_every_value_is_in_the_T04_enum()
    test_empty_input_does_not_crash_or_over_claim()
    test_the_descriptor_alone_can_carry_the_match()
    print("ALL PASS")
