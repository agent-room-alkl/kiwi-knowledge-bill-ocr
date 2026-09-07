# -*- coding: utf-8 -*-
"""Unit tests for compute_summary. FAKE fixture semantics, no live PDF parse."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.compute_summary import compute_summary, evidence_gaps, monthly_equivalent

ASSESSMENT = "2026-08-31"


def _txn(i, date, desc, amount, direction, merchant=None):
    return {
        "transaction_id": i,
        "account_id": "a1",
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


def test_fortnightly_salary():
    canonical = {
        "assessment_date": ASSESSMENT,
        "accounts": [],
        "transactions": [
            _txn("s1", "2026-06-03", "SALARY ACME NZ LTD", 4820, "inflow", "ACME NZ LTD"),
            _txn("s2", "2026-06-28", "SALARY ACME NZ LTD", 4820, "inflow", "ACME NZ LTD"),
            _txn("s3", "2026-07-02", "SALARY ACME NZ LTD", 4820, "inflow", "ACME NZ LTD"),
            _txn("s4", "2026-07-30", "SALARY ACME NZ LTD", 4820, "inflow", "ACME NZ LTD"),
        ],
    }
    classifications = {
        "assessment_date": ASSESSMENT,
        "classifications": [
            _cls("s1", "salary_wages", False, "fortnightly"),
            _cls("s2", "salary_wages", False, "fortnightly"),
            _cls("s3", "salary_wages", False, "fortnightly"),
            _cls("s4", "salary_wages", False, "fortnightly"),
        ],
    }
    out = compute_summary(canonical, classifications)
    expected = round(4820 * 26 / 12, 2)
    got = out["income"][0]["monthly_equivalent"]
    assert got == expected, f"salary monthly {got} != {expected} (must not be 4820 or 9640)"
    assert expected != 9640
    merchants = [m["merchant"] for m in out["part5"]["top_merchants"]]
    assert not any("ACME" in m for m in merchants)


def test_rent_forced_into_recommended_even_if_model_says_no():
    canonical = {
        "assessment_date": ASSESSMENT,
        "accounts": [],
        "transactions": [
            _txn("r1", "2026-06-04", "RENT A. LANDLORD", 2400, "outflow", "RENT LANDLORD"),
            _txn("r2", "2026-07-04", "RENT A. LANDLORD", 2400, "outflow", "RENT LANDLORD"),
        ],
    }
    classifications = {
        "assessment_date": ASSESSMENT,
        "classifications": [
            _cls("r1", "rent_board_paid", False, "monthly"),
            _cls("r2", "rent_board_paid", False, "monthly"),
        ],
    }
    out = compute_summary(canonical, classifications)
    rent = out["audit"]["rent_monthly"]
    assert rent == 2400, f"rent monthly {rent} != 2400"
    assert out["recommended_monthly_living"] >= 2400
    part2 = [x for x in out["part2"] if x["category"] == "rent_board_paid"]
    assert all(x["include"] == "Yes" for x in part2)


def test_posrej_is_zero_and_not_grocery():
    canonical = {
        "assessment_date": ASSESSMENT,
        "accounts": [],
        "transactions": [
            _txn("p0", "2026-06-06", "POSREJ COUNTDOWN KARORI", 0, "info", "COUNTDOWN"),
            _txn("p1", "2026-06-06", "COUNTDOWN KARORI", 92.4, "outflow", "COUNTDOWN"),
        ],
    }
    classifications = {
        "assessment_date": ASSESSMENT,
        "classifications": [
            _cls("p0", "food_grocery_clothing_personal_care", True),
            _cls("p1", "food_grocery_clothing_personal_care", True),
        ],
    }
    out = compute_summary(canonical, classifications)
    assert out["audit"]["info_rows_zeroed"] == 1
    food = next(x for x in out["part1"] if x["category"].startswith("Food"))
    assert food["monthly_equivalent"] < 500, f"POSREJ must not inflate food: {food}"


def test_monthly_formula():
    assert round(monthly_equivalent(4820, "fortnightly"), 2) == round(4820 * 26 / 12, 2)
    assert monthly_equivalent(100, "weekly") == 100 * 52 / 12
    assert monthly_equivalent(1200, "annual") == 100


def test_kiwisaver_listed_not_recommended():
    canonical = {
        "assessment_date": ASSESSMENT,
        "accounts": [],
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
    ks = next(x for x in out["part1"] if x["category"].startswith("KiwiSaver"))
    don = next(x for x in out["part1"] if x["category"].startswith("Donations"))
    assert ks["monthly_equivalent"] == 180
    assert don["monthly_equivalent"] == 20
    assert out["recommended_monthly_living"] == 0


def test_inconsistent_gaps_are_not_a_cadence():
    """26 days then 4 days is two overlapping statements, not fortnightly.

    Reading the median of inconsistent gaps as a cadence turned a $2,400 rent
    into $5,200 a month - more than the applicant earned.
    """
    from pipeline.compute_summary import detect_frequency
    from datetime import date
    assert detect_frequency([date(2026, 6, 4), date(2026, 6, 30), date(2026, 7, 4)]) == "irregular"
    # a real cadence still reads as one
    assert detect_frequency([date(2026, 5, 4), date(2026, 6, 4), date(2026, 7, 4)]) == "monthly"
    assert detect_frequency([date(2026, 6, 1), date(2026, 6, 15), date(2026, 6, 29)]) == "fortnightly"


def test_irregular_uses_the_observation_window():
    """Three rents inside one month, seen through a three-month binder.

    Dividing by the merchant's own 30-day span gives $7,200/month. Dividing by
    the window we can actually see gives $2,408, which is what the binder says.
    """
    txns, cls = [], []
    for i, d in enumerate(["2026-06-04", "2026-06-30", "2026-07-04"]):
        tid = f"rent{i}"
        txns.append({"transaction_id": tid, "account_id": "a", "date": d,
                     "description": "RENT A. LANDLORD", "amount": 2400.0,
                     "direction": "outflow", "source_file": "x.pdf"})
        cls.append({"transaction_id": tid, "category": "rent_board_paid",
                    "include_in_living_expenses": True, "confidence": 0.9, "reason": "t"})
    # widen the observable window with an unrelated early row
    txns.append({"transaction_id": "z", "account_id": "a", "date": "2026-05-02",
                 "description": "UBER EATS", "amount": 34.5, "direction": "outflow",
                 "source_file": "y.pdf"})
    cls.append({"transaction_id": "z", "category": "recreation_entertainment",
                "include_in_living_expenses": True, "confidence": 0.9, "reason": "t"})
    # The binder covers three statement months, even though the last rent
    # posting is on 4 July. The window comes from the periods, not the postings.
    accounts = [{"account_id": "a", "institution": "ANZ", "account_type": "everyday",
                 "period_start": "2026-05-01", "period_end": "2026-07-31",
                 "source_file": "x.pdf"}]
    s = compute_summary({"assessment_date": "2026-09-01", "accounts": accounts, "transactions": txns},
                        {"assessment_date": "2026-09-01", "classifications": cls})
    rent = next(r["monthly_equivalent"] for r in s["part1"] if r["category"] == "Rent / board paid")
    # 3 x 2400 over 92 days = 3.0227 months -> about 2382, not the 7200 that
    # dividing by the merchant's own 30-day span used to produce.
    assert 2300 <= rent <= 2450, f"rent normalised to {rent}, expected about 2382"


def test_model_cadence_hint_must_survive_a_count_check():
    """The model may suggest a cadence; it may not assert one the dates deny.

    A run labelled `Pak N Save` and `Gull` weekly on 4 and 2 visits in three
    months. x52/12 turned $800 of groceries into $1,384 a month and $191 of
    fuel into $358, putting recommended living at 93% of income instead of 56%.
    The model is never allowed to set an amount, and setting the multiplier is
    setting the amount.

    A weekly claim over a 92-day window implies about 13 postings. Four is not
    weekly. Accept a hint only when the count is at least half of what the
    cadence implies; otherwise normalise the observed spend over the window.
    """
    accounts = [{"account_id": "a", "institution": "ANZ", "account_type": "everyday",
                 "period_start": "2026-05-01", "period_end": "2026-07-31",
                 "source_file": "x.pdf"}]
    txns, cls = [], []

    def add(tid, date, desc, amount, category, hint):
        txns.append({"transaction_id": tid, "account_id": "a", "date": date,
                     "description": desc, "amount": amount, "direction": "outflow",
                     "source_file": "x.pdf"})
        cls.append({"transaction_id": tid, "category": category,
                    "include_in_living_expenses": True, "confidence": 0.9,
                    "reason": "t", "suggested_frequency": hint})

    # 4 grocery visits in 92 days, the model says weekly
    for i, (d, a) in enumerate([("2026-06-12", 54.20), ("2026-07-05", 186.40),
                                ("2026-07-12", 142.10), ("2026-07-22", 171.80)]):
        add(f"g{i}", d, "Pak N Save Wairau Road", a,
            "food_grocery_clothing_personal_care", "weekly")
    # 2 fuel stops in 92 days, the model says weekly
    for i, (d, a) in enumerate([("2026-06-22", 71.40), ("2026-07-10", 89.20)]):
        add(f"f{i}", d, "Gull Albany", a, "transport", "weekly")
    # a genuinely monthly subscription, seen twice - the hint should survive
    for i, (d, a) in enumerate([("2026-06-11", 25.99), ("2026-07-07", 25.99)]):
        add(f"n{i}", d, "NETFLIX.COM", a, "monthly_subscriptions", "monthly")
    # a cadence printed on the statement, seen once - the document wins
    add("w0", "2026-07-16", "WATERCARE QUARTERLY", 186.00, "utilities", "quarterly")

    for c in cls:
        if c["category"] == "utilities":
            c["utility_type"] = "water"
    out = compute_summary({"assessment_date": "2026-09-01", "accounts": accounts,
                           "transactions": txns},
                          {"assessment_date": "2026-09-01", "classifications": cls})
    part1 = {r["category"]: r["monthly_equivalent"] for r in out["part1"]}

    food = part1["Food / grocery / clothing / personal care"]
    assert 175 <= food <= 195, f"groceries {food}, expected about 183 (554.50/3.02), not the 680 a weekly multiple gives"
    transport = part1["Transport"]
    assert 45 <= transport <= 70, f"transport {transport}, expected about 53 (160.6/3.02)"
    subs = part1["Monthly subscriptions"]
    assert 25 <= subs <= 27, f"subscriptions {subs}, a real monthly hint must survive"
    utilities = part1["Utilities"]
    assert 61 <= utilities <= 63, f"utilities {utilities}, printed QUARTERLY must survive (186/3)"
    water = next(x for x in out["part2_calculations"] if x["category"] == "utilities")
    assert water["assessed_frequency"] == "quarterly"
    assert set(water) >= {
        "merchant", "dates_observed", "average_amount",
        "assessed_frequency", "calculated_monthly_impact",
    }
    assert out["subtype_breakdowns"]["utilities"][0]["subtype"] == "water"
    top = out["part5"]["top_merchants"]
    assert top, "annualised top merchants must be present"
    assert "annual_spend" in top[0] and "spend" not in top[0]
    assert "category" in top[0] and "calculation_basis" in top[0]
    assert out["part4"] == []
    assert out["liability_evidence_status"] == "no liability evidence identified"
    assert out["part5"]["underwriter_notes"]


def test_credit_card_is_a_part4_facility():
    canonical = {
        "assessment_date": ASSESSMENT,
        "accounts": [
            {
                "account_id": "card1",
                "account_label": "Card ending 4567",
                "institution": "Westpac",
                "account_type": "credit_card",
                "credit_limit": 6000.0,
                "closing_balance": 388.4,
                "period_start": "2026-06-08",
                "period_end": "2026-07-07",
                "source_file": "westpac.pdf",
                "is_statement": True,
            }
        ],
        "transactions": [
            _txn("c1", "2026-06-18", "THE WAREHOUSE", 89.9, "outflow", "THE WAREHOUSE"),
            {
                **_txn("c2", "2026-07-05", "PAYMENT THANK YOU", 200.0, "inflow", "PAYMENT"),
                "account_id": "card1",
            },
        ],
    }
    canonical["transactions"][0]["account_id"] = "card1"
    classifications = {
        "assessment_date": ASSESSMENT,
        "classifications": [
            _cls("c1", "food_grocery_clothing_personal_care", True),
            _cls("c2", "credit_card_repayment", False),
        ],
    }
    out = compute_summary(canonical, classifications)
    assert out["part4"], out["part4"]
    card = out["part4"][0]
    assert card["facility_type"] == "Credit card"
    assert card["account_label"] == "Card ending 4567"
    assert card["credit_limit"] == 6000.0
    assert out["liability_evidence_status"] == "identified"


def test_a_one_off_receipt_is_not_monthly_income():
    """A tax refund is not a salary.

    Real file: a single IRD credit of $4,217.53 was reported as $4,217.53 a
    month of income, on top of a $3,459 salary - the applicant appeared to earn
    122% more than they do. The expense side already treats `one_off` as $0 a
    month, so the two sides were asymmetric in the direction that makes an
    applicant look more affordable than they are.
    """
    canonical = {
        "assessment_date": "2026-09-02",
        "accounts": [{"account_id": "a1", "period_start": "2026-05-20",
                      "period_end": "2026-08-19", "account_type": "everyday"}],
        "transactions": [
            {"transaction_id": "s1", "account_id": "a1", "date": "2026-06-10",
             "description": "DIRECT CREDIT ACME", "merchant_normalized": "ACME",
             "amount": 3459.26, "direction": "inflow"},
            {"transaction_id": "s2", "account_id": "a1", "date": "2026-07-10",
             "description": "DIRECT CREDIT ACME", "merchant_normalized": "ACME",
             "amount": 3459.26, "direction": "inflow"},
            {"transaction_id": "s3", "account_id": "a1", "date": "2026-08-10",
             "description": "DIRECT CREDIT ACME", "merchant_normalized": "ACME",
             "amount": 3459.26, "direction": "inflow"},
            {"transaction_id": "r1", "account_id": "a1", "date": "2026-06-08",
             "description": "DIRECT CREDIT I.R.D.", "merchant_normalized": "IRD",
             "amount": 4217.53, "direction": "inflow"},
        ],
    }
    cls = {"assessment_date": "2026-09-02", "classifications": [
        {"transaction_id": t, "category": "salary_wages",
         "include_in_living_expenses": False, "confidence": 0.9, "reason": "salary"}
        for t in ("s1", "s2", "s3")
    ] + [{"transaction_id": "r1", "category": "other_income",
          "include_in_living_expenses": False, "confidence": 0.9, "reason": "tax refund"}]}
    out = compute_summary(canonical, cls)
    by = {r["source"]: r for r in out["income"]}
    assert by["IRD"]["frequency"] == "one_off", by["IRD"]["frequency"]
    assert by["IRD"]["monthly_equivalent"] == 0.0, (
        f"a one-off receipt was counted as {by['IRD']['monthly_equivalent']}/month")
    assert by["ACME"]["monthly_equivalent"] > 3000, by["ACME"]["monthly_equivalent"]
    total = sum(r["monthly_equivalent"] for r in out["income"])
    assert 3400 < total < 3600, f"monthly income should be the salary alone, got {total}"


def test_mixed_amounts_use_dominant_cluster_not_median():
    """$2,880 rent plus ancillary Barfoot charges must not median to $1,800."""
    txns, cls = [], []
    amounts = [54.31, 2880, 76.03, 2880, 2880, 70.59, 2880, 720]
    dates = ["2026-05-26", "2026-06-07", "2026-06-25", "2026-07-06",
             "2026-07-11", "2026-07-24", "2026-07-26", "2026-07-28"]
    for i, (d, amt) in enumerate(zip(dates, amounts)):
        txns.append(_txn(f"b{i}", d, "PAY Barfoot & Thompson Limited", amt, "outflow", "BARFOOT"))
        cls.append(_cls(f"b{i}", "rent_board_paid", True, "monthly"))
    out = compute_summary(
        {"assessment_date": "2026-09-02", "accounts": [
            {"account_id": "a1", "period_start": "2026-05-20", "period_end": "2026-08-19"}
        ], "transactions": txns},
        {"assessment_date": "2026-09-02", "classifications": cls},
    )
    rent = out["audit"]["rent_monthly"]
    assert abs(rent - 1800) > 1, f"mixed median leaked: {rent}"
    assert abs(rent - 4116) > 50, f"extras monthlyised into run-rate: {rent}"
    # The repeating charge is the rent. Four postings in 3.02 months could be a
    # fortnightly tenancy, an arrears catch-up or a second property, and those
    # do not service the same way - so the cadence becomes a question on Part 5
    # rather than a $3,811 nobody can source.
    assert rent == 2880, f"rent must stay the repeating amount, got {rent}"
    cadence_notes = [
        n for n in out["part5"]["underwriter_notes"] if n["topic"] == "Rent cadence"
    ]
    assert cadence_notes, "irregular rent cadence must land a Part5 note"
    note = cadence_notes[0]
    assert note["requires_signoff"] is True
    assert "4 times in 3.02 months" in note["note"], note["note"]
    assert "3811" in note["note"], "the cadence reading must be shown, not hidden"
    assert "4115" in note["note"] or "4116" in note["note"], "the run-rate must be shown too"
    assert "2880" in note["note"], "the reported figure must be named"
    assert "Confirm the contracted rent" in note["note"], note["note"]


def test_same_day_salary_rows_merge_before_typical():
    txns = [
        _txn("a1", "2026-06-11", "Direct Credit ATOM DATA NZ LIMITED", 362.75, "inflow", "ATOM DATA NZ LIMITED"),
        _txn("a2", "2026-06-11", "Direct Credit ATOM DATA NZ LIMITED", 1.00, "inflow", "ATOM DATA NZ LIMITED"),
        _txn("a3", "2026-06-11", "Direct Credit ATOM DATA NZ LIMITED", 8515.98, "inflow", "ATOM DATA NZ LIMITED"),
        _txn("a4", "2026-07-10", "Direct Credit ATOM DATA NZ LIMITED", 8882.37, "inflow", "ATOM DATA NZ LIMITED"),
        _txn("a5", "2026-08-10", "Direct Credit ATOM DATA NZ LIMITED", 3418.51, "inflow", "ATOM DATA NZ LIMITED"),
        _txn("a6", "2026-05-26", "Direct Credit ATOM DATA NZ LIMITED", 3500.00, "inflow", "ATOM DATA NZ LIMITED"),
    ]
    cls = [_cls(t["transaction_id"], "salary_wages", False, "monthly") for t in txns]
    out = compute_summary(
        {"assessment_date": "2026-09-02", "accounts": [
            {"account_id": "a1", "period_start": "2026-05-20", "period_end": "2026-08-19"}
        ], "transactions": txns},
        {"assessment_date": "2026-09-02", "classifications": cls},
    )
    salary = out["income"][0]["monthly_equivalent"]
    assert salary != 3459.26, salary
    assert salary < 8500, f"jumbo $8881 monthly from two big months: {salary}"
    atom_rows = [r for r in out["part2"] if "ATOM" in r["description"].upper()]
    assert len(atom_rows) == 4, [r["date"] for r in atom_rows]
    june = next(r for r in atom_rows if str(r["date"]).startswith("2026-06-11"))
    assert abs(float(june["amount"]) - 8879.73) < 0.02, june["amount"]


def test_anthropic_descriptors_collapse_and_business_is_excluded():
    txns = [
        _txn("c1", "2026-05-25", "POS W/D CLAUDE.AI SUBSCRIPTION ANTHROPIC.COMCAUS", 203.7, "outflow", "CLAUDE.AI"),
        _txn("c2", "2026-06-25", "POS W/D ANTHROPIC* CLAUDE SUB ANTHROPIC.COMCAUS", 203.7, "outflow", "ANTHROPIC"),
        _txn("i1", "2026-06-15", "IWG NEW ZEALAND MANAGEMAUCKLAND", 616.4, "outflow", "IWG NEW ZEALAND"),
        _txn("i2", "2026-07-15", "IWG NEW ZEALAND MANAGEMAUCKLAND", 616.4, "outflow", "IWG NEW ZEALAND"),
        _txn("s1", "2026-07-16", "SP BLUE SPORT AUCKLAND", 749.99, "outflow", "SP BLUE SPORT"),
    ]
    cls = [
        _cls("c1", "monthly_subscriptions", True, "monthly",
             is_business="yes", business_reason="developer SaaS"),
        _cls("c2", "monthly_subscriptions", True, "monthly",
             is_business="yes", business_reason="developer SaaS"),
        _cls("i1", "other", True, "monthly",
             is_business="yes", business_reason="premises lease"),
        _cls("i2", "other", True, "monthly",
             is_business="yes", business_reason="premises lease"),
        _cls("s1", "recreation_entertainment", True, "unknown"),
    ]
    out = compute_summary(
        {"assessment_date": "2026-09-02", "accounts": [
            {"account_id": "a1", "period_start": "2026-05-20", "period_end": "2026-08-19",
             "account_label": "kb", "institution": "Kiwibank"}
        ], "transactions": txns},
        {"assessment_date": "2026-09-02", "classifications": cls},
    )
    merchants = {c["merchant"] for c in out["part2_calculations"]}
    assert "ANTHROPIC / CLAUDE" in merchants
    assert out["recommended_monthly_living"] == 0, out["recommended_monthly_living"]
    assert out["business_monthly"] > 0
    rec = next(x["monthly_equivalent"] for x in out["part1"] if x["category"].startswith("Recreation"))
    assert rec == 0, rec
    assert any("BLUE SPORT" in (p["description"] or "") for p in out["part3"])
    p2 = out["part2"][0]
    assert "source_file" in p2 and "exclusion_reason" in p2 and "needs_review" in p2


def test_pos_wd_prefix_does_not_split_a_merchant():
    txns = [
        _txn("m1", "2026-07-18", "MICROSOFT*STORE MSBILL.INFO", 37.68, "outflow", "MICROSOFT*STORE MSBILL.INFO"),
        _txn("m2", "2026-08-19", "POS W/D MICROSOFT*STORE MSBILL.INFO SG", 37.68, "outflow", "POS W/D MICROSOFT*STORE MSBILL.INFO SG"),
        _txn("m3", "2026-08-12", "MICROSOFT#G177359695 MSBILL.INFO", 14.34, "outflow", "MICROSOFT#G177359695 MSBILL.INFO"),
        _txn("m4", "2026-08-12", "POS W/D MICROSOFT#G177359695 MSBILL.INFO SG", 15.88, "outflow", "POS W/D MICROSOFT#G177359695 MSBILL.INFO SG"),
    ]
    cls = [_cls(t["transaction_id"], "monthly_subscriptions", True, "monthly") for t in txns]
    out = compute_summary(
        {"assessment_date": "2026-09-02", "accounts": [
            {"account_id": "a1", "period_start": "2026-05-20", "period_end": "2026-08-19"}
        ], "transactions": txns},
        {"assessment_date": "2026-09-02", "classifications": cls},
    )
    keys = sorted({c["merchant"] for c in out["part2_calculations"] if "MICROSOFT" in c["merchant"]})
    assert len(keys) == 2, keys
    assert not any(k.startswith("POS ") for k in keys), keys


def test_unmarked_known_brand_is_not_auto_excluded():
    """Without is_business=yes the engine must not exclude a named brand."""
    txns = [
        _txn("i1", "2026-06-15", "IWG NEW ZEALAND MANAGEMAUCKLAND", 616.4, "outflow", "IWG NEW ZEALAND"),
        _txn("i2", "2026-07-15", "IWG NEW ZEALAND MANAGEMAUCKLAND", 616.4, "outflow", "IWG NEW ZEALAND"),
    ]
    cls = [
        _cls("i1", "other", True, "monthly"),
        _cls("i2", "other", True, "monthly"),
    ]
    out = compute_summary(
        {"assessment_date": "2026-09-02", "accounts": [
            {"account_id": "a1", "period_start": "2026-05-20", "period_end": "2026-08-19"}
        ], "transactions": txns},
        {"assessment_date": "2026-09-02", "classifications": cls},
    )
    assert out["business_monthly"] == 0, out["business_monthly"]
    assert out["recommended_monthly_living"] == 616.4, out["recommended_monthly_living"]


def test_is_business_field_excludes_unlisted_trades():
    """A different trade, none of whose names are in any list, still splits."""
    txns = [
        _txn("b1", "2026-06-10", "BUILDERS MERCHANT TIMBER YARD", 890.0, "outflow", "BUILDERS MERCHANT"),
        _txn("b2", "2026-07-10", "BUILDERS MERCHANT TIMBER YARD", 890.0, "outflow", "BUILDERS MERCHANT"),
        _txn("f1", "2026-06-12", "FREIGHT LINE DEPOT", 210.0, "outflow", "FREIGHT LINE"),
        _txn("f2", "2026-07-12", "FREIGHT LINE DEPOT", 210.0, "outflow", "FREIGHT LINE"),
        _txn("s1", "2026-06-18", "SALON SUPPLY WHOLESALE", 145.0, "outflow", "SALON SUPPLY"),
        _txn("s2", "2026-07-18", "SALON SUPPLY WHOLESALE", 145.0, "outflow", "SALON SUPPLY"),
        _txn("g1", "2026-06-20", "PAK N SAVE GLENFIELD", 180.0, "outflow", "PAK N SAVE"),
        _txn("g2", "2026-07-20", "PAK N SAVE GLENFIELD", 180.0, "outflow", "PAK N SAVE"),
        _txn("w1", "2026-06-22", "TRADE WHOLESALER LTD", 320.0, "outflow", "TRADE WHOLESALER"),
        _txn("w2", "2026-07-22", "TRADE WHOLESALER LTD", 320.0, "outflow", "TRADE WHOLESALER"),
    ]
    cls = [
        _cls("b1", "other", True, "monthly", is_business="yes", business_reason="trade materials"),
        _cls("b2", "other", True, "monthly", is_business="yes", business_reason="trade materials"),
        _cls("f1", "other", True, "monthly", is_business="yes", business_reason="freight for goods"),
        _cls("f2", "other", True, "monthly", is_business="yes", business_reason="freight for goods"),
        _cls("s1", "other", True, "monthly", is_business="yes", business_reason="trade-specific supplies"),
        _cls("s2", "other", True, "monthly", is_business="yes", business_reason="trade-specific supplies"),
        _cls("g1", "food_grocery_clothing_personal_care", True, "monthly", is_business="no"),
        _cls("g2", "food_grocery_clothing_personal_care", True, "monthly", is_business="no"),
        _cls("w1", "food_grocery_clothing_personal_care", True, "monthly",
             is_business="review", business_reason="wholesale, no other business signal"),
        _cls("w2", "food_grocery_clothing_personal_care", True, "monthly",
             is_business="review", business_reason="wholesale, no other business signal"),
    ]
    out = compute_summary(
        {"assessment_date": "2026-09-02", "accounts": [
            {"account_id": "a1", "period_start": "2026-05-20", "period_end": "2026-08-19"}
        ], "transactions": txns},
        {"assessment_date": "2026-09-02", "classifications": cls},
    )
    by_merchant = {c["merchant"]: c for c in out["part2_calculations"]}
    assert by_merchant["BUILDERS MERCHANT"]["is_business"] == "yes"
    assert by_merchant["FREIGHT LINE"]["is_business"] == "yes"
    assert by_merchant["SALON SUPPLY"]["is_business"] == "yes"
    assert by_merchant["PAK N SAVE"]["is_business"] == "no"
    assert by_merchant["TRADE WHOLESALER"]["is_business"] == "review"
    assert out["business_monthly"] == 890 + 210 + 145, out["business_monthly"]
    # Household grocery + review wholesale stay in recommended living.
    assert out["recommended_monthly_living"] == 180 + 320, out["recommended_monthly_living"]
    review_rows = [r for r in out["part2"] if "TRADE WHOLESALER" in (r["description"] or "")]
    assert review_rows
    assert all(r["include"] == "Yes" and r["needs_review"] is True for r in review_rows)
    biz_rows = [r for r in out["part2"] if "BUILDERS MERCHANT" in (r["description"] or "")]
    assert all(r["include"] == "No" for r in biz_rows)


def test_irregular_uses_the_account_window_not_the_household():
    """ANZ-only spend is divided by 61 days, not the Kiwibank 92-day span."""
    accounts = [
        {"account_id": "anz", "institution": "ANZ", "account_type": "everyday",
         "period_start": "2026-06-20", "period_end": "2026-08-19",
         "source_file": "ANZ-0619.pdf"},
        {"account_id": "kb", "institution": "Kiwibank", "account_type": "everyday",
         "period_start": "2026-05-20", "period_end": "2026-08-19",
         "source_file": "KB-0619.pdf"},
    ]
    txns = [
        _txn("a1", "2026-07-04", "ANZ ONLY CAFE", 300.0, "outflow", "ANZ ONLY CAFE"),
        _txn("a2", "2026-08-04", "ANZ ONLY CAFE", 300.0, "outflow", "ANZ ONLY CAFE"),
        _txn("k1", "2026-05-25", "KB ONLY SHOP", 150.0, "outflow", "KB ONLY SHOP"),
        _txn("k2", "2026-07-25", "KB ONLY SHOP", 150.0, "outflow", "KB ONLY SHOP"),
        _txn("b1", "2026-05-22", "BOTH BANKS FUEL", 80.0, "outflow", "BOTH BANKS FUEL"),
        _txn("b2", "2026-07-22", "BOTH BANKS FUEL", 80.0, "outflow", "BOTH BANKS FUEL"),
    ]
    txns[0]["account_id"] = txns[1]["account_id"] = "anz"
    txns[0]["source_file"] = txns[1]["source_file"] = "ANZ-0619.pdf"
    txns[2]["account_id"] = txns[3]["account_id"] = "kb"
    txns[2]["source_file"] = txns[3]["source_file"] = "KB-0619.pdf"
    txns[4]["account_id"] = "kb"
    txns[4]["source_file"] = "KB-0619.pdf"
    txns[5]["account_id"] = "anz"
    txns[5]["source_file"] = "ANZ-0619.pdf"
    cls = [
        _cls("a1", "recreation_entertainment", True, "unknown"),
        _cls("a2", "recreation_entertainment", True, "unknown"),
        _cls("k1", "food_grocery_clothing_personal_care", True, "unknown"),
        _cls("k2", "food_grocery_clothing_personal_care", True, "unknown"),
        _cls("b1", "transport", True, "unknown"),
        _cls("b2", "transport", True, "unknown"),
    ]
    out = compute_summary(
        {"assessment_date": "2026-09-02", "accounts": accounts, "transactions": txns},
        {"assessment_date": "2026-09-02", "classifications": cls},
    )
    by_merch = {c["merchant"]: c for c in out["part2_calculations"]}

    anz = by_merch["ANZ ONLY CAFE"]
    assert anz["account_id"] == "anz", anz["account_id"]
    assert "2.00 months" in anz["calculation_basis"], anz["calculation_basis"]
    assert "ANZ 61d" in anz["calculation_basis"], anz["calculation_basis"]
    assert "3.02" not in anz["calculation_basis"], anz["calculation_basis"]
    # 600 / 2.00 = 300, not 600/3.02 ≈ 198
    assert abs(anz["calculated_monthly_impact"] - 300.0) < 1.0, anz["calculated_monthly_impact"]

    kb = by_merch["KB ONLY SHOP"]
    assert kb["account_id"] == "kb"
    assert "3.02 months" in kb["calculation_basis"], kb["calculation_basis"]
    assert "Kiwibank 92d" in kb["calculation_basis"], kb["calculation_basis"]

    both = by_merch["BOTH BANKS FUEL"]
    assert "spans" in both["calculation_basis"], both["calculation_basis"]
    assert "ANZ" in both["calculation_basis"] and "Kiwibank" in both["calculation_basis"]
    assert "," in str(both["account_id"]), both["account_id"]
    bare = [
        c for c in out["part2_calculations"]
        if c["assessed_frequency"] == "irregular"
        and c["calculation_basis"].rstrip().endswith("/ 3.02 months")
    ]
    assert bare == [], [c["merchant"] for c in bare]


def test_missing_is_business_is_a_visible_warning_not_a_clean_zero():
    """Absent is_business must not look like 'no business spend'."""
    accounts = [{"account_id": "a1", "period_start": "2026-05-20", "period_end": "2026-08-19"}]
    txns = [
        _txn("x1", "2026-06-15", "PLACEMAKERS TRADE", 500.0, "outflow", "PLACEMAKERS"),
        _txn("x2", "2026-07-15", "PLACEMAKERS TRADE", 500.0, "outflow", "PLACEMAKERS"),
    ]
    without = compute_summary(
        {"assessment_date": "2026-09-02", "accounts": accounts, "transactions": txns},
        {"assessment_date": "2026-09-02", "classifications": [
            _cls("x1", "other", True, "monthly"),
            _cls("x2", "other", True, "monthly"),
        ]},
    )
    assert without["audit"]["business_classification_missing"] is True
    assert without["audit"]["is_business_classifications"] == 0
    assert without["business_monthly"] == 0
    topics = [n["topic"] for n in without["part5"]["underwriter_notes"]]
    assert topics[0] == "Business classification missing"
    assert "not assessed" in without["part5"]["underwriter_notes"][0]["note"].lower()

    with_field = compute_summary(
        {"assessment_date": "2026-09-02", "accounts": accounts, "transactions": txns},
        {"assessment_date": "2026-09-02", "classifications": [
            _cls("x1", "other", True, "monthly", is_business="yes", business_reason="trade materials"),
            _cls("x2", "other", True, "monthly", is_business="yes", business_reason="trade materials"),
        ]},
    )
    assert with_field["audit"]["business_classification_missing"] is False
    assert with_field["audit"]["is_business_classifications"] == 2
    assert with_field["business_monthly"] == 500
    assert "Business classification missing" not in [
        n["topic"] for n in with_field["part5"]["underwriter_notes"]
    ]


def test_extract_duplicate_is_dropped_genuine_repeats_sum():
    """Prefix-only twin is one charge; byte-identical raws are real repeats."""
    accounts = [{"account_id": "a1", "period_start": "2026-05-20", "period_end": "2026-08-19"}]
    txns = [
        _txn("m1", "2026-08-19", "MICROSOFT*STORE MSBILL.INFO", 37.68, "outflow", "MICROSOFT*STORE MSBILL.INFO"),
        _txn("m2", "2026-08-19", "POS W/D MICROSOFT*STORE MSBILL.INFO SG", 37.68, "outflow", "POS W/D MICROSOFT*STORE MSBILL.INFO SG"),
        _txn("a1", "2026-05-31", "AGENT-ROOM.COM", 8.44, "outflow", "AGENT-ROOM.COM"),
        _txn("a2", "2026-05-31", "AGENT-ROOM.COM", 8.44, "outflow", "AGENT-ROOM.COM"),
        _txn("a3", "2026-05-31", "AGENT-ROOM.COM", 8.44, "outflow", "AGENT-ROOM.COM"),
        _txn("a4", "2026-07-01", "AGENT-ROOM.COM", 8.88, "outflow", "AGENT-ROOM.COM"),
        _txn("a5", "2026-07-01", "AGENT-ROOM.COM", 8.88, "outflow", "AGENT-ROOM.COM"),
    ]
    cls = [_cls(t["transaction_id"], "monthly_subscriptions", True, "monthly") for t in txns]
    # Model marks one Microsoft row as the duplicate; engine used to override that No.
    cls[1]["include_in_living_expenses"] = False
    out = compute_summary(
        {"assessment_date": "2026-09-02", "accounts": accounts, "transactions": txns},
        {"assessment_date": "2026-09-02", "classifications": cls},
    )
    ms = [c for c in out["part2_calculations"] if "MICROSOFT*STORE" in c["merchant"]]
    assert len(ms) == 1, [c["merchant"] for c in ms]
    assert abs(ms[0]["calculated_monthly_impact"] - 37.68) < 0.02, ms[0]
    assert abs(ms[0]["dominant_amount"] - 37.68) < 0.02
    dropped = [r for r in out["part2"] if "duplicate extraction" in (r.get("exclusion_reason") or "")]
    assert dropped, out["part2"]
    may = next(
        r for r in out["part2"]
        if str(r["date"]).startswith("2026-05-31") and "AGENT-ROOM" in (r["description"] or "")
    )
    jul = next(
        r for r in out["part2"]
        if str(r["date"]).startswith("2026-07-01") and "AGENT-ROOM" in (r["description"] or "")
    )
    assert abs(float(may["amount"]) - 25.32) < 0.02, may
    assert abs(float(jul["amount"]) - 17.76) < 0.02, jul
    rec_ms = [r for r in out["part2"] if "MICROSOFT*STORE" in (r.get("description") or "") and r["include"] == "Yes"]
    assert len(rec_ms) == 1, rec_ms


def test_variable_grocery_is_not_weeklyised_from_one_outlier():
    """FU MARKET $28–$222 must not become $963/month via weekly × $222."""
    amounts = [109.9, 49.15, 60.41, 33.88, 45.89, 222.2, 27.92, 95.36]
    dates = ["2026-06-29", "2026-07-06", "2026-07-13", "2026-07-20",
             "2026-07-27", "2026-08-03", "2026-08-10", "2026-08-17"]
    txns, cls = [], []
    for i, (d, amt) in enumerate(zip(dates, amounts)):
        txns.append(_txn(f"f{i}", d, "FU MARKET", amt, "outflow", "FU MARKET"))
        cls.append(_cls(f"f{i}", "food_grocery_clothing_personal_care", True, "weekly"))
    out = compute_summary(
        {"assessment_date": "2026-09-04", "accounts": [
            {"account_id": "a1", "period_start": "2026-05-20", "period_end": "2026-08-19"}
        ], "transactions": txns},
        {"assessment_date": "2026-09-04", "classifications": cls},
    )
    food = next(r["monthly_equivalent"] for r in out["part1"]
                if r["category"] == "Food / grocery / clothing / personal care")
    assert food < 500, f"weekly outlier monthlyised grocery to {food}"
    calc = next(c for c in out["part2_calculations"] if c["merchant"] == "FU MARKET")
    assert calc["assessed_frequency"] != "weekly" or calc["dominant_amount"] < 150


def test_part2_exposes_direction_and_unclear_split():
    txns = [
        _txn("in1", "2026-07-02", "Direct Credit MISS Y ZHANG", 40, "inflow", "MISS Y ZHANG"),
        _txn("out1", "2026-07-03", "PAY Xiuyuan zhang", 30, "outflow", "XIUYUAN ZHANG"),
        _txn("rent1", "2026-07-04", "PAY Barfoot", 2880, "outflow", "BARFOOT"),
    ]
    cls = [
        _cls("in1", "unclear", False),
        _cls("out1", "unclear", False),
        _cls("rent1", "rent_board_paid", True, "monthly"),
    ]
    out = compute_summary(
        {"assessment_date": "2026-09-02", "accounts": [
            {"account_id": "a1", "period_start": "2026-07-01", "period_end": "2026-07-31"}
        ], "transactions": txns},
        {"assessment_date": "2026-09-02", "classifications": cls},
    )
    by_id = {r["transaction_id"]: r for r in out["part2"]}
    assert by_id["in1"]["direction"] == "inflow"
    assert by_id["out1"]["direction"] == "outflow"
    rent = next(r["monthly_equivalent"] for r in out["part1"] if r["category"] == "Rent / board paid")
    assert rent == 2880
    note = next(n for n in out["part5"]["underwriter_notes"] if n["topic"] == "Unclear by direction")
    assert "1 inflow $40.00" in note["note"]
    assert "1 outflow $30.00" in note["note"]


def test_unclear_reason_is_not_literal_and_sources_split():
    txns = [
        _txn("miss", "2026-07-02", "UNKNOWN MERCHANT XYZ", 12, "outflow", "UNKNOWN MERCHANT XYZ"),
        _txn("low", "2026-07-03", "PAY Xiuyuan zhang", 30, "outflow", "XIUYUAN ZHANG"),
        _txn("rent1", "2026-07-04", "PAY Barfoot", 2880, "outflow", "BARFOOT"),
    ]
    cls = [
        _cls("low", "unclear", False, reason="person-name P2P, confidence 0.31"),
        _cls("rent1", "rent_board_paid", True, "monthly"),
    ]
    out = compute_summary(
        {"assessment_date": "2026-09-02", "accounts": [
            {"account_id": "a1", "period_start": "2026-07-01", "period_end": "2026-07-31"}
        ], "transactions": txns},
        {"assessment_date": "2026-09-02", "classifications": cls},
    )
    by_id = {r["transaction_id"]: r for r in out["part2"]}
    assert by_id["miss"]["classified"] is False
    assert by_id["miss"]["exclusion_reason"] == "no classification joined"
    assert by_id["low"]["classified"] is True
    assert by_id["low"]["reason"] == "person-name P2P, confidence 0.31"
    assert by_id["low"]["exclusion_reason"] == "person-name P2P, confidence 0.31"
    assert by_id["low"]["exclusion_reason"] != "unclear"
    rent = next(r["monthly_equivalent"] for r in out["part1"] if r["category"] == "Rent / board paid")
    assert rent == 2880
    note = next(n for n in out["part5"]["underwriter_notes"] if n["topic"] == "Unclear sources")
    assert "1 join-miss" in note["note"]
    assert "1 model unclear" in note["note"]


def _gap_topics(out):
    return [g["topic"] for g in out["part5"]["evidence_gaps"]]


def _rent_only_binder(extra_txns=None, extra_cls=None, applicant=None, accounts=None):
    """Two months of rent and nothing else, plus whatever the caller adds.

    The rent is the control: it is the one figure every gap test asserts stays
    put, because a detection-only check that quietly moved rent would be the
    exact failure these tests exist to catch.
    """
    txns = [
        _txn("r1", "2026-06-04", "RENT A. LANDLORD", 2400, "outflow", "RENT LANDLORD"),
        _txn("r2", "2026-07-04", "RENT A. LANDLORD", 2400, "outflow", "RENT LANDLORD"),
    ]
    cls = [
        _cls("r1", "rent_board_paid", False, "monthly"),
        _cls("r2", "rent_board_paid", False, "monthly"),
    ]
    canonical = {
        "assessment_date": ASSESSMENT,
        "accounts": accounts if accounts is not None else [
            {"account_id": "a1", "institution": "ANZ",
             "period_start": "2026-06-01", "period_end": "2026-07-31", "days_covered": 61}
        ],
        "transactions": txns + list(extra_txns or []),
    }
    if applicant is not None:
        canonical["applicant"] = applicant
    return canonical, {
        "assessment_date": ASSESSMENT,
        "classifications": cls + list(extra_cls or []),
    }


def test_evidence_gaps_five_families_do_not_move_money():
    """All five gap families fire at once and not one cent moves."""

    control_out = compute_summary(*_rent_only_binder())

    # (a) names ASB, which has no statement here. (b) a school payment while
    # Dependants is unrecorded. (c) NZTA with no vehicle insurer anywhere.
    # (d) no energy retailer in the whole file. (e) a Wise transfer out, over
    # the threshold, inside the window before the assessment date.
    extra_txns = [
        _txn("g1", "2026-06-10", "TFR TO ASB 12-3456-0000001-00", 300, "outflow", "ASB TRANSFER"),
        _txn("g2", "2026-06-12", "WAIRAU INTERMEDIATE SCHOOL", 180, "outflow", "WAIRAU INTERMEDIATE SCHOOL"),
        _txn("g3", "2026-06-14", "NZ TRANSPORT AGENCY REGO", 113.94, "outflow", "NZ TRANSPORT AGENCY"),
        _txn("g4", "2026-08-20", "WISE NZ TRANSFER", 3000, "outflow", "WISE"),
    ]
    extra_cls = [
        _cls("g1", "unclear", False, "one_off"),
        _cls("g2", "unclear", False, "one_off"),
        _cls("g3", "unclear", False, "one_off"),
        _cls("g4", "unclear", False, "one_off"),
    ]
    out = compute_summary(*_rent_only_binder(extra_txns, extra_cls))
    topics = _gap_topics(out)

    assert len(topics) == 5, f"expected all five gap families, got {topics}"
    assert any(t.startswith("Account outside binder") and "ASB" in t for t in topics), topics
    assert "Dependants not recorded" in topics, topics
    assert "Vehicle costs without vehicle insurance" in topics, topics
    assert "No power or gas in the file" in topics, topics
    assert "Large offshore transfer before assessment" in topics, topics

    # The whole point of T-04: detection only.
    assert out["audit"]["rent_monthly"] == 2400, out["audit"]["rent_monthly"]
    assert out["audit"]["rent_monthly"] == control_out["audit"]["rent_monthly"]
    assert out["recommended_monthly_living"] == control_out["recommended_monthly_living"], (
        f"gaps moved recommended {control_out['recommended_monthly_living']} "
        f"-> {out['recommended_monthly_living']}"
    )
    # Every Part 1 line is untouched. The one row that legitimately differs is
    # TOTAL ONE-OFF EXCLUDED, which is a raw sum of the rows the caller added -
    # and its value proves the gap-triggering spend landed in the excluded
    # bucket rather than in anybody's living expenses.
    def _part1(summary):
        return {
            r["category"]: r["monthly_equivalent"]
            for r in summary["part1"]
            if r["category"] != "TOTAL ONE-OFF EXCLUDED"
        }
    assert _part1(out) == _part1(control_out), (
        f"gaps changed Part 1: {_part1(control_out)} -> {_part1(out)}"
    )
    one_off = next(
        r["monthly_equivalent"] for r in out["part1"]
        if r["category"] == "TOTAL ONE-OFF EXCLUDED"
    )
    assert one_off == round(300 + 180 + 113.94 + 3000, 2), one_off

    note = next(n for n in out["part5"]["underwriter_notes"] if n["topic"] == "Evidence gaps")
    assert note["requires_signoff"] is True
    assert "5 evidence gap(s)" in note["note"], note["note"]


def test_evidence_gap_skips_banks_already_in_the_binder():
    """A transfer naming a bank whose statement IS here is not a gap."""

    extra_txns = [_txn("b1", "2026-06-10", "TFR TO ANZ 06-0081-0097480-00", 300, "outflow", "ANZ TRANSFER")]
    extra_cls = [_cls("b1", "unclear", False, "one_off")]
    out = compute_summary(*_rent_only_binder(extra_txns, extra_cls))
    topics = _gap_topics(out)
    assert not any("ANZ" in t for t in topics), f"ANZ is in the binder, not a gap: {topics}"


def test_evidence_gaps_stay_quiet_when_the_binder_answers_them():
    """Dependants recorded, vehicle insured, power paid, no offshore transfer."""

    extra_txns = [
        _txn("e1", "2026-06-05", "MERIDIAN ENERGY", 180.4, "outflow", "MERIDIAN ENERGY"),
        _txn("e2", "2026-07-05", "MERIDIAN ENERGY", 180.4, "outflow", "MERIDIAN ENERGY"),
        _txn("v1", "2026-06-14", "NZ TRANSPORT AGENCY REGO", 113.94, "outflow", "NZ TRANSPORT AGENCY"),
        _txn("i1", "2026-06-06", "AA INSURANCE", 62.1, "outflow", "AA INSURANCE"),
        _txn("i2", "2026-07-06", "AA INSURANCE", 62.1, "outflow", "AA INSURANCE"),
    ]
    extra_cls = [
        _cls("e1", "utilities", True, "monthly", subtype="power"),
        _cls("e2", "utilities", True, "monthly", subtype="power"),
        _cls("v1", "transport", True, "one_off"),
        _cls("i1", "insurance", True, "monthly", subtype="vehicle"),
        _cls("i2", "insurance", True, "monthly", subtype="vehicle"),
    ]
    applicant = {
        "Full Name(s)": "Alex Taylor",
        "Age(s)": "41",
        "Dependants": "2",
        "Address and living situation": "12 Example Street, Wellington 6011 (Renting)",
    }
    out = compute_summary(*_rent_only_binder(extra_txns, extra_cls, applicant=applicant))
    topics = _gap_topics(out)
    assert topics == [], f"clean binder should report no gaps, got {topics}"
    note = next(n for n in out["part5"]["underwriter_notes"] if n["topic"] == "Evidence gaps")
    assert note["requires_signoff"] is False
    assert "No evidence gaps" in note["note"], note["note"]


def test_evidence_gaps_survive_a_malformed_transaction_date():
    """An unreadable date drops that row from the check, it does not raise.

    Called against evidence_gaps directly: the surrounding engine has its own
    date handling, and this asserts only that the gap checks are not the thing
    that turns a bad row into a failed assessment.
    """

    rows = [
        {"date": "not-a-date", "description": "WISE NZ TRANSFER", "merchant_normalized": "WISE",
         "amount": 3000, "direction": "outflow"},
        {"date": "2026-08-20", "description": "WISE NZ TRANSFER", "merchant_normalized": "WISE",
         "amount": 3000, "direction": "outflow"},
    ]
    accounts = [{"account_id": "a1", "institution": "ANZ", "days_covered": 61}]
    applicant = {"Dependants": "2"}
    gaps = evidence_gaps(rows, accounts, applicant, ASSESSMENT, {"vehicle": 62.1}, {"power": 180.4})
    topics = [g["topic"] for g in gaps]
    assert "Large offshore transfer before assessment" in topics, topics
    offshore = next(g for g in gaps if g["topic"] == "Large offshore transfer before assessment")
    assert "3000.00" in offshore["evidence"], offshore["evidence"]
    assert "not-a-date" not in offshore["evidence"], offshore["evidence"]
    assert "1 remittance(s)" in offshore["note"], offshore["note"]


def test_evidence_gaps_note_appears_exactly_once():
    """One finding, one line.

    The merge that brought T-04's gap checks onto the T-02 branch left the
    Evidence gaps underwriter note being appended twice, so Part 5 showed the
    same sign-off item in two places. An underwriter reading two identical
    lines has to work out whether they are two findings.
    """

    out = compute_summary(*_rent_only_binder())
    topics = [n["topic"] for n in out["part5"]["underwriter_notes"]]
    assert topics.count("Evidence gaps") == 1, topics


def test_many_small_credits_from_many_payers_are_flagged_as_possible_trading():
    """Trading receipts are named as turnover, and no money moves.

    Shape-based on purpose: the check counts payers and ticket sizes rather
    than deciding which descriptions are personal names. Applied to this
    applicant's file that distinction matters - a name heuristic put a
    coworking provider and a currency-conversion line in the person bucket.
    """

    txns, cls = [], []
    for i in range(14):
        txns.append(_txn(f"c{i}", f"2026-06-{(i % 27) + 1:02d}", f"PAYER {i} bun", 40 + i, "inflow", f"PAYER {i}"))
        cls.append(_cls(f"c{i}", "unclear", False, "one_off"))
    out = compute_summary(*_rent_only_binder(txns, cls))
    gaps = {g["topic"]: g for g in out["part5"]["evidence_gaps"]}
    topic = "Unassessed receipts - possible trading income"
    assert topic in gaps, list(gaps)
    note = gaps[topic]["note"]
    assert "14 credit(s)" in note, note
    assert "14 different payers" in note, note
    assert "turnover and not profit" in note, note

    control = compute_summary(*_rent_only_binder())
    assert out["audit"]["rent_monthly"] == control["audit"]["rent_monthly"] == 2400
    assert out["recommended_monthly_living"] == control["recommended_monthly_living"]
    assert not any(r["category"] == "Other" and r["monthly_equivalent"] for r in out["part1"])


def test_one_regular_payer_is_not_a_business():
    """Board from a single flatmate must not read as trading receipts."""

    txns, cls = [], []
    for i in range(12):
        txns.append(_txn(f"b{i}", f"2026-06-{(i % 27) + 1:02d}", "A FLATMATE", 200, "inflow", "A FLATMATE"))
        cls.append(_cls(f"b{i}", "unclear", False, "weekly"))
    out = compute_summary(*_rent_only_binder(txns, cls))
    topics = [g["topic"] for g in out["part5"]["evidence_gaps"]]
    assert "Unassessed receipts - possible trading income" not in topics, topics


def test_zero_business_rows_with_unresolved_ones_is_not_a_clean_zero():
    """0 business spend must not read the same as 'we could not decide'."""

    txns = [
        _txn("w1", "2026-06-10", "SOME SUPPLIER", 300, "outflow", "SOME SUPPLIER"),
        _txn("w2", "2026-07-10", "SOME SUPPLIER", 300, "outflow", "SOME SUPPLIER"),
    ]
    cls = [
        _cls("w1", "monthly_subscriptions", True, "monthly", is_business="review"),
        _cls("w2", "monthly_subscriptions", True, "monthly", is_business="no"),
    ]
    out = compute_summary(*_rent_only_binder(txns, cls))
    assert out["business_monthly"] == 0
    note = next(
        (n for n in out["part5"]["underwriter_notes"] if n["topic"] == "Business spend not resolved"),
        None,
    )
    assert note is not None, [n["topic"] for n in out["part5"]["underwriter_notes"]]
    assert note["requires_signoff"] is True
    assert "1 row(s) came back unresolved" in note["note"], note["note"]
    assert "undecided, not absent" in note["note"], note["note"]

    # Every row decided and none of them business: that IS a clean zero.
    clean_cls = [
        _cls("w1", "monthly_subscriptions", True, "monthly", is_business="no"),
        _cls("w2", "monthly_subscriptions", True, "monthly", is_business="no"),
    ]
    clean = compute_summary(*_rent_only_binder(txns, clean_cls))
    assert not any(
        n["topic"] == "Business spend not resolved" for n in clean["part5"]["underwriter_notes"]
    )


def test_trading_turnover_uses_the_span_not_the_sum_of_statement_days():
    """Overlapping statements must not stretch the window and shrink the rate.

    ANZ 61 days sitting inside Kiwibank 92 days is a three-month file, not a
    five-month one. Summing days_covered divided this applicant's turnover by
    5.03 instead of 3.02 and reported 1,310/month for what is 2,180/month -
    an error that made the side business look smaller than it is.
    """

    accounts = [
        {"account_id": "a1", "institution": "Kiwibank", "period_start": "2026-05-20",
         "period_end": "2026-08-19", "days_covered": 92},
        {"account_id": "a2", "institution": "ANZ", "period_start": "2026-06-20",
         "period_end": "2026-08-19", "days_covered": 61},
    ]
    txns, cls = [], []
    for i in range(12):
        txns.append(_txn(f"c{i}", f"2026-06-{(i % 27) + 1:02d}", f"PAYER {i}", 100, "inflow", f"PAYER {i}"))
        cls.append(_cls(f"c{i}", "unclear", False, "one_off"))
    out = compute_summary(*_rent_only_binder(txns, cls, accounts=accounts))
    gap = next(g for g in out["part5"]["evidence_gaps"]
               if g["topic"] == "Unassessed receipts - possible trading income")
    # 1,200 over the 92-day span is 397.00/month; over a summed 153 days it
    # would read 238.75 and understate the business by a third.
    assert "397.00/month" in gap["note"], gap["note"]
    assert "238" not in gap["note"], gap["note"]


def test_business_receipts_do_not_silence_the_unresolved_spend_note():
    """Tagging income as business must not count as assessing business spend.

    The classifier marks side-business receipts is_business=yes. Counting
    those would make the file look as though business spend had been
    assessed, and the note would go quiet on exactly the binder that needs
    it - a side business whose costs are still sitting in living expenses.
    """

    txns, cls = [], []
    for i in range(12):
        txns.append(_txn(f"c{i}", f"2026-06-{(i % 27) + 1:02d}", f"PAYER {i} bun", 100, "inflow", f"PAYER {i}"))
        cls.append(_cls(f"c{i}", "unclear", False, "one_off", is_business="yes"))
    txns.append(_txn("s1", "2026-06-15", "IWG NEW ZEALAND", 616.4, "outflow", "IWG NEW ZEALAND"))
    cls.append(_cls("s1", "monthly_subscriptions", True, "monthly", is_business="review"))

    out = compute_summary(*_rent_only_binder(txns, cls))
    note = next(
        (n for n in out["part5"]["underwriter_notes"] if n["topic"] == "Business spend not resolved"),
        None,
    )
    assert note is not None, [n["topic"] for n in out["part5"]["underwriter_notes"]]
    assert "1 row(s) came back unresolved" in note["note"], note["note"]
    assert out["business_monthly"] == 0


if __name__ == "__main__":
    tests = [
        test_monthly_formula,
        test_fortnightly_salary,
        test_rent_forced_into_recommended_even_if_model_says_no,
        test_posrej_is_zero_and_not_grocery,
        test_kiwisaver_listed_not_recommended,
        test_inconsistent_gaps_are_not_a_cadence,
        test_irregular_uses_the_observation_window,
        test_model_cadence_hint_must_survive_a_count_check,
        test_credit_card_is_a_part4_facility,
        test_a_one_off_receipt_is_not_monthly_income,
        test_mixed_amounts_use_dominant_cluster_not_median,
        test_same_day_salary_rows_merge_before_typical,
        test_anthropic_descriptors_collapse_and_business_is_excluded,
        test_pos_wd_prefix_does_not_split_a_merchant,
        test_unmarked_known_brand_is_not_auto_excluded,
        test_is_business_field_excludes_unlisted_trades,
        test_irregular_uses_the_account_window_not_the_household,
        test_missing_is_business_is_a_visible_warning_not_a_clean_zero,
        test_extract_duplicate_is_dropped_genuine_repeats_sum,
        test_variable_grocery_is_not_weeklyised_from_one_outlier,
        test_part2_exposes_direction_and_unclear_split,
        test_unclear_reason_is_not_literal_and_sources_split,
        test_evidence_gaps_five_families_do_not_move_money,
        test_evidence_gap_skips_banks_already_in_the_binder,
        test_evidence_gaps_stay_quiet_when_the_binder_answers_them,
        test_evidence_gaps_survive_a_malformed_transaction_date,
        test_evidence_gaps_note_appears_exactly_once,
        test_many_small_credits_from_many_payers_are_flagged_as_possible_trading,
        test_one_regular_payer_is_not_a_business,
        test_trading_turnover_uses_the_span_not_the_sum_of_statement_days,
        test_zero_business_rows_with_unresolved_ones_is_not_a_clean_zero,
        test_business_receipts_do_not_silence_the_unresolved_spend_note,
    ]
    for fn in tests:
        fn()
        print("ok", fn.__name__)
    print("ALL PASS")
