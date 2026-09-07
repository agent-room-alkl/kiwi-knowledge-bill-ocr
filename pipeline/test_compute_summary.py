# -*- coding: utf-8 -*-
"""Unit tests for compute_summary. FAKE fixture semantics, no live PDF parse."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.compute_summary import compute_summary, monthly_equivalent

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
    assert 2800 <= rent <= 3000, f"expected repeating $2880 rent, not window-average $4116, got {rent}"


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
    ]
    for fn in tests:
        fn()
        print("ok", fn.__name__)
    print("ALL PASS")
