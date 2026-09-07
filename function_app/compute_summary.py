# -*- coding: utf-8 -*-
"""Servicing calc engine. LLM classifies; this module owns every total."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from statistics import median
from typing import Any

from extract_normalize import collapse_merchant, descriptor_core

RECOMMENDED = frozenset(
    {
        "transport",
        "utilities",
        "insurance",
        "food_grocery_clothing_personal_care",
        "recreation_entertainment",
        "monthly_subscriptions",
        "education",
        "childcare_child_support",
        "rent_board_paid",
        "medical",
        "extracurricular",
        "other",
    }
)
SAVINGS_GIVING = frozenset({"kiwisaver_savings_investments", "donations_tithings"})
INCOME = frozenset(
    {
        "salary_wages",
        "benefit",
        "child_support_received",
        "rental_income",
        "investment_income",
        "other_income",
        "income_credit",
    }
)
EXCLUSIONS = frozenset(
    {
        "internal_transfer",
        "credit_card_repayment",
        "loan_repayment",
        "mortgage_repayment",
        "interest_charge",
        "redraw",
        "reimbursement",
        "underwriter_manual",
        "unclear",
        "one_off",
    }
)

PART1_ROWS = [
    ("transport", "Transport"),
    ("utilities", "Utilities"),
    ("insurance", "Insurance (combined)"),
    ("food_grocery_clothing_personal_care", "Food / grocery / clothing / personal care"),
    ("recreation_entertainment", "Recreation and entertainment"),
    ("monthly_subscriptions", "Monthly subscriptions"),
    ("education", "Education"),
    ("kiwisaver_savings_investments", "KiwiSaver and savings (NOT in recommended)"),
    ("childcare_child_support", "Childcare and child support"),
    ("donations_tithings", "Donations / tithings (NOT in recommended)"),
    ("rent_board_paid", "Rent / board paid"),
    ("medical", "Medical"),
    ("extracurricular", "Extracurricular"),
    ("other", "Other"),
]


def parse_date(value: str) -> date:
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _months_between(start: date, end: date) -> float:
    return max(((end - start).days + 1) / 30.436875, 1.0)


def _resolve_account_id(row: dict[str, Any], accounts: list[dict[str, Any]]) -> str | None:
    """Use the row's account_id, or a unique source_file match. Never guess by date."""
    aid = row.get("account_id")
    if aid:
        return str(aid)
    src = row.get("source_file")
    if not src:
        return None
    matches = [
        str(a["account_id"])
        for a in accounts
        if a.get("source_file") == src and a.get("account_id")
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _stream_observation(
    rows: list[dict[str, Any]],
    account_by_id: dict[str, dict[str, Any]],
    accounts: list[dict[str, Any]],
    fallback_months: float,
) -> tuple[float, str, str | None]:
    """Window of the account(s) this stream actually appears in.

    Returns (months, basis_clause, account_id). A spanning stream names every
    window; it does not silently pick one. Unattributed streams keep the
    household fallback and say so — they are not assigned an account.
    """
    ids: list[str] = []
    for row in rows:
        aid = _resolve_account_id(row, accounts)
        if aid:
            ids.append(aid)
    unique = list(dict.fromkeys(ids))

    windows: list[tuple[date, date]] = []
    labels: list[str] = []
    for aid in unique:
        acct = account_by_id.get(aid) or {}
        if not (acct.get("period_start") and acct.get("period_end")):
            continue
        start = parse_date(acct["period_start"])
        end = parse_date(acct["period_end"])
        windows.append((start, end))
        inst = acct.get("institution") or acct.get("account_label") or aid
        days = (end - start).days + 1
        labels.append(f"{inst} {days}d")

    if not windows:
        acct_id = unique[0] if len(unique) == 1 else (",".join(unique) if unique else None)
        return fallback_months, " (account not attributed)", acct_id

    start = min(w[0] for w in windows)
    end = max(w[1] for w in windows)
    months = _months_between(start, end)
    if len(windows) == 1:
        return months, f" ({labels[0]})", unique[0]
    return months, f" (spans {', '.join(labels)})", ",".join(unique)


def _business_flag(raw: Any) -> str:
    """Read the model's is_business field. Never infer from a merchant name."""
    val = str(raw or "no").strip().lower()
    if val in {"yes", "review"}:
        return val
    return "no"


def _stream_business_flag(rows: list[dict[str, Any]]) -> str:
    flags = {_business_flag(r.get("is_business")) for r in rows}
    if "yes" in flags:
        return "yes"
    if "review" in flags:
        return "review"
    return "no"


def _amount_clusters(amounts: list[float]) -> list[list[float]]:
    pts = sorted(abs(float(a)) for a in amounts)
    if not pts:
        return []
    groups: list[list[float]] = []
    cur = [pts[0]]
    for amount in pts[1:]:
        ref = cur[-1]
        if abs(amount - ref) <= max(2.0, 0.05 * max(abs(amount), abs(ref))):
            cur.append(amount)
        else:
            groups.append(cur)
            cur = [amount]
    groups.append(cur)
    return groups


def dominant_cluster_amount(amounts: list[float]) -> float:
    """Median of the amount cluster with the largest total.

    A mixed median of $2,880 rent plus $54 water/rates lands on $1,800 and
    reports neither number. Clustering (5% or $2) keeps the repeating charge.

    A cluster of one is not a rhythm. Eight grocery shops from $28 to $222
    used to pick $222 as typical, then weekly × 52/12 turned $645 of food
    into $963 a month.
    """
    groups = _amount_clusters(amounts)
    if not groups:
        return 0.0
    pts = [a for group in groups for a in group]
    best = max(groups, key=lambda group: (sum(group), len(group)))
    if len(best) == 1 and len(pts) >= 3:
        return float(median(pts))
    return float(median(best))


def dominant_cluster_size(amounts: list[float]) -> int:
    groups = _amount_clusters(amounts)
    if not groups:
        return 0
    best = max(groups, key=lambda group: (sum(group), len(group)))
    return len(best)


def mark_extract_duplicates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop a second extraction of the same charge; keep genuine repeats.

    Same date + merchant + amount, raw descriptions equal only after stripping
    bank prefixes/suffixes → one charge read twice. Keep the most common raw
    wording and mark the rest. Byte-identical raw descriptions are real
    repeat postings and must keep summing (AGENT-ROOM 3×8.44).
    """
    groups: dict[tuple, list[int]] = defaultdict(list)
    out = [dict(row) for row in rows]
    for i, row in enumerate(out):
        if row.get("direction") == "info":
            continue
        key = (
            str(row.get("date"))[:10],
            row.get("merchant_normalized"),
            round(abs(float(row.get("amount") or 0)), 2),
        )
        groups[key].append(i)
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        by_raw: dict[str, list[int]] = defaultdict(list)
        for i in idxs:
            by_raw[str(out[i].get("description") or "")].append(i)
        if len(by_raw) == 1:
            continue
        cores = {raw: descriptor_core(raw) for raw in by_raw}
        if len(set(cores.values())) != 1:
            continue
        keep_raw = max(by_raw.items(), key=lambda kv: (len(kv[1]), -len(kv[0])))[0]
        for raw, ixs in by_raw.items():
            if raw == keep_raw:
                continue
            for i in ixs:
                out[i]["extract_duplicate"] = True
                out[i]["include"] = False
    return out


def merge_same_day(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sum same merchant+category+direction on the same calendar day."""
    buckets: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    leftovers: list[dict[str, Any]] = []
    for row in rows:
        if row.get("direction") == "info":
            continue
        if row.get("extract_duplicate"):
            leftovers.append(dict(row, same_day_merged=0))
            continue
        buckets[
            (str(row.get("date"))[:10], row.get("merchant_normalized"), row.get("category"), row.get("direction"))
        ].append(row)
    merged: list[dict[str, Any]] = []
    seen_info = False
    for row in rows:
        if row.get("direction") == "info":
            merged.append(dict(row, same_day_merged=1))
            seen_info = True
    merged.extend(leftovers)
    for group in buckets.values():
        head = dict(group[0])
        if len(group) == 1:
            head["same_day_merged"] = 1
            merged.append(head)
            continue
        head["amount"] = round(sum(abs(float(item["amount"])) for item in group), 2)
        head["same_day_merged"] = len(group)
        extra = len(group) - 1
        desc = head.get("description") or ""
        if extra and "[+" not in desc:
            head["description"] = f"{desc}  [+{extra} same-day rows merged]"
        merged.append(head)
    return merged if seen_info or merged else rows


def monthly_equivalent(amount: float, frequency: str) -> float:
    amount = abs(float(amount))
    if frequency == "weekly":
        return amount * 52 / 12
    if frequency == "fortnightly":
        return amount * 26 / 12
    if frequency == "monthly":
        return amount
    if frequency == "quarterly":
        return amount / 3
    if frequency == "annual":
        return amount / 12
    return amount


NOMINAL_GAP_DAYS = {
    "weekly": 7.0,
    "fortnightly": 14.0,
    "monthly": 30.436875,
    "quarterly": 91.31,
    "annual": 365.2425,
}

# A hint is accepted when at least this share of the postings the cadence
# implies actually appear in the window. Half is deliberately generous: a
# genuine monthly bill can miss a month in a three-month binder, but four
# grocery visits can never be weekly.
HINT_MIN_COVERAGE = 0.5


def hint_is_supported(hint: str, observations: int, observation_months: float) -> bool:
    """Does the number of postings support the cadence the model claimed?

    The model is not allowed to set an amount, and setting the multiplier is
    setting the amount. A `weekly` claim over 92 days implies about 13 postings;
    honouring it on four turned $800 of groceries into $1,384 a month.
    """
    gap = NOMINAL_GAP_DAYS.get(hint)
    if not gap:
        return False
    if observations <= 1:
        # One sighting is not evidence of a rhythm, but it is not evidence
        # against a slow one either: a single power bill in a three-month window
        # is still a monthly power bill, and refusing the hint zeroes a real
        # cost. Rejecting it here once turned a $214.50 Meridian bill into $0.
        # So honour monthly-or-slower, where the monthly figure can never exceed
        # the amount actually seen.
        #
        # Weekly and fortnightly are the opposite case. `weekly` over 92 days
        # predicts about 13 postings; seeing one contradicts the claim, and
        # honouring it multiplies a sighting by 4.33 into money that was never
        # on the statement. One $92.40 grocery shop became $400.40 a month.
        return gap >= 28.0
    implied = (observation_months * 30.436875) / gap
    if implied <= 1:
        return True  # the window is too short to expect more than one
    return observations >= implied * HINT_MIN_COVERAGE


def detect_frequency(dates: list[date]) -> str:
    """Infer a payment cadence from when a merchant was paid.

    Only claims a cadence when the gaps actually agree with each other. Three
    rent payments 26 days and then 4 days apart are not fortnightly - they are
    two statements whose periods overlap, and the 4-day gap is an artefact of
    merging accounts, not a real payment rhythm. Taking the median of
    inconsistent gaps turns that artefact into a confident wrong answer: a
    $2,400 rent became $5,200 a month, more than the applicant earned.

    When the gaps disagree, say `irregular`. The caller then normalises the
    observed spend over the observation window instead of multiplying up a
    cadence nobody can see.
    """
    uniq = sorted(set(dates))
    if len(uniq) < 2:
        return "unknown"
    gaps = [(b - a).days for a, b in zip(uniq, uniq[1:]) if (b - a).days > 0]
    if not gaps:
        return "unknown"

    # One gap is one data point, not a rhythm. Two fuel stops 18 days apart
    # are not a fortnightly commitment, but a single 18-day gap lands inside
    # the fortnightly band and multiplies the spend by 26/12 anyway. Require at
    # least two gaps before claiming any cadence from dates.
    if len(gaps) < 2:
        return "unknown"

    # Consistency gate. One outlying gap is enough to disqualify a cadence
    # claim, because the wrong cadence is worse than an honest "irregular".
    if max(gaps) > 2 * min(gaps):
        return "irregular"

    g = median(gaps)
    if 5 <= g <= 9:
        return "weekly"
    if 12 <= g <= 18:
        return "fortnightly"
    if 25 <= g <= 35:
        return "monthly"
    if 80 <= g <= 100:
        return "quarterly"
    if 330 <= g <= 400:
        return "annual"
    return "irregular"


def effective_include(category: str, direction: str, model_include: bool) -> bool:
    if direction != "outflow":
        return False
    if category in EXCLUSIONS or category in INCOME or category in SAVINGS_GIVING:
        return False
    if category == "rent_board_paid":
        return True
    if category in RECOMMENDED:
        return True
    return bool(model_include) and category in RECOMMENDED


def _index_classifications(
    batch: dict[str, Any], txns: list[dict[str, Any]] | None = None
) -> dict[str, dict[str, Any]]:
    """Map each transaction to its classification.

    Two shapes are accepted, and both end up keyed by transaction_id here:

    - `{transaction_id, category, ...}` classifies one row.
    - `{merchant, category, ...}` classifies every row of that merchant.

    The second exists because the first does not scale. A real binder is 611
    rows; asking a model to emit 611 objects burned 94k tokens and 494 seconds
    and then it declined, correctly, rather than guess. Those 611 rows are 238
    merchants, and a shop does not change category between visits - so the
    merchant is the right unit of judgement, and one decision covering sixteen
    Fu Market visits is more consistent than sixteen separate ones.

    A per-row classification still wins over a merchant-level one for the same
    row: the specific instruction beats the general.
    """
    out: dict[str, dict[str, Any]] = {}

    by_merchant: dict[str, list[str]] = defaultdict(list)
    for txn in txns or []:
        key = str(txn.get("merchant_normalized") or "").upper().strip()
        if key:
            by_merchant[key].append(txn["transaction_id"])

    rows = batch.get("classifications") or []
    for row in rows:
        merchant = str(row.get("merchant") or "").upper().strip()
        if merchant and not row.get("transaction_id"):
            for txn_id in by_merchant.get(merchant, ()):
                out[txn_id] = row
    for row in rows:
        if row.get("transaction_id"):
            out[row["transaction_id"]] = row
    return out


def _liability_rows(
    accounts: list[dict[str, Any]], joined: list[dict[str, Any]],
    calculations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    """Build evidenced debt facilities; never turn an everyday account into debt."""
    result: list[dict[str, Any]] = []
    account_by_id = {a.get("account_id"): a for a in accounts}

    for account in accounts:
        if account.get("account_type") != "credit_card":
            continue
        repayments = [
            r for r in joined
            if r.get("account_id") == account.get("account_id")
            and r.get("direction") == "inflow"
            and (r.get("category") == "credit_card_repayment" or "PAYMENT" in r.get("description", "").upper())
        ]
        repayment_amount = median([abs(r["amount"]) for r in repayments]) if repayments else None
        repayment_frequency = detect_frequency([parse_date(r["date"]) for r in repayments]) if repayments else "Not observed"
        result.append(
            {
                "institution": account.get("institution"),
                "facility_type": "Credit card",
                "account_label": account.get("account_label") or "Not provided in binder",
                "credit_limit": account.get("credit_limit"),
                "current_balance": account.get("closing_balance"),
                "observed_repayment": round(repayment_amount, 2) if repayment_amount is not None else None,
                "frequency": repayment_frequency,
                "evidence": account.get("source_file"),
            }
        )

    debt_categories = {
        "mortgage_repayment": "Home loan",
        "loan_repayment": "Personal loan / HP / BNPL",
        "credit_card_repayment": "Credit card repayment (facility not otherwise identified)",
    }
    seen = {(r["facility_type"], r.get("institution"), r.get("account_label")) for r in result}
    for calc in calculations:
        category = calc.get("category")
        if category not in debt_categories:
            continue
        source_account = account_by_id.get(calc.get("account_id"), {})
        if category == "credit_card_repayment" and any(
            a.get("account_type") == "credit_card" for a in accounts
        ):
            continue
        key = (debt_categories[category], calc.get("merchant"), source_account.get("account_label"))
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "institution": calc.get("merchant") or source_account.get("institution"),
                "facility_type": debt_categories[category],
                "account_label": source_account.get("account_label") or "Not provided in binder",
                "credit_limit": None,
                "current_balance": None,
                "observed_repayment": calc.get("average_amount"),
                "frequency": calc.get("assessed_frequency"),
                "evidence": ", ".join(calc.get("dates_observed") or []),
            }
        )

    return result, ("identified" if result else "no liability evidence identified")


def _conduct_rows(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "institution": account.get("institution"),
            "account_label": account.get("account_label") or "Not provided in binder",
            "source_file": account.get("source_file"),
            "conduct": account.get("conduct") or {
                "status": "Not returned by extractor",
            },
        }
        for account in accounts if account.get("is_statement", True)
    ]


def compute_summary(canonical: dict[str, Any], classifications: dict[str, Any]) -> dict[str, Any]:
    txns = canonical.get("transactions") or []
    by_id = _index_classifications(classifications, txns)
    accounts = canonical.get("accounts") or []
    assessment_date = canonical.get("assessment_date") or classifications.get("assessment_date")

    joined = []
    for txn in txns:
        cls = by_id.get(txn["transaction_id"], {})
        category = cls.get("category") or "unclear"
        direction = txn.get("direction") or "info"
        amount = float(txn.get("amount") or 0)
        if direction == "info":
            amount = 0.0
        include = effective_include(category, direction, bool(cls.get("include_in_living_expenses")))
        raw_merchant = cls.get("merchant_normalized") or txn.get("merchant_normalized") or txn.get("description") or ""
        merchant = collapse_merchant(str(raw_merchant), str(txn.get("description") or ""))
        business_flag = _business_flag(cls.get("is_business"))
        if business_flag == "yes":
            include = False
        resolved_account = _resolve_account_id(txn, accounts)
        joined.append(
            {
                **txn,
                "amount": amount,
                "category": category,
                "include": include,
                "model_include": bool(cls.get("include_in_living_expenses")),
                "suggested_frequency": cls.get("suggested_frequency") or "unknown",
                "merchant_normalized": merchant,
                "is_business": business_flag,
                "business_reason": str(cls.get("business_reason") or "").strip(),
                "reason": cls.get("reason") or "",
                "utility_type": cls.get("utility_type"),
                "insurance_type": cls.get("insurance_type"),
                "account_id": resolved_account or txn.get("account_id"),
            }
        )

    joined = mark_extract_duplicates(joined)
    joined = merge_same_day(joined)
    n_explicit_business = sum(
        1
        for row in (classifications.get("classifications") or [])
        if "is_business" in row and str(row.get("is_business") or "").strip() != ""
    )
    has_outflow = any(r.get("direction") == "outflow" for r in joined)
    business_classification_missing = n_explicit_business == 0 and has_outflow

    # Recurring streams: same merchant + category, use typical amount x frequency (do not sum each hit).
    streams: dict[tuple[str, str], list] = defaultdict(list)
    for row in joined:
        if row["direction"] == "info" or row.get("extract_duplicate"):
            continue
        streams[(row["category"], row["merchant_normalized"])].append(row)

    # One observation window for the whole binder, used as the denominator for
    # every irregular category so they are all normalised the same way.
    #
    # Prefer the statement periods: they are what the binder actually covers.
    # Transaction dates only bound the window from below - a statement that runs
    # to 31 July still covers July even if the last posting was on the 4th, and
    # using the last posting instead shrinks the denominator and inflates every
    # monthly figure computed from it.
    _starts = [parse_date(a["period_start"]) for a in accounts if a.get("period_start")]
    _ends = [parse_date(a["period_end"]) for a in accounts if a.get("period_end")]
    if _starts and _ends:
        observation_months = _months_between(min(_starts), max(_ends))
    else:
        _dates = [parse_date(r["date"]) for r in joined]
        observation_months = (
            _months_between(min(_dates), max(_dates)) if _dates else 1.0
        )

    category_monthly: dict[str, float] = defaultdict(float)
    income_rows = []
    line_items = []
    one_offs = []
    savings_giving = 0.0
    calculations: list[dict[str, Any]] = []
    utility_monthly: dict[str, float] = defaultdict(float)
    insurance_monthly: dict[str, float] = defaultdict(float)
    business_monthly = 0.0
    account_by_id = {a.get("account_id"): a for a in accounts}

    for (category, merchant), rows in streams.items():
        dates = [parse_date(r["date"]) for r in rows]
        stream_months, window_clause, stream_account_id = _stream_observation(
            rows, account_by_id, accounts, observation_months
        )
        hinted = rows[0].get("suggested_frequency") or "unknown"
        desc = " ".join(r.get("description", "") for r in rows).upper()
        # A cadence printed on the statement itself is the document speaking, so
        # it outranks both the model's hint and date inference.
        # Otherwise the hint is accepted only if the postings can support it.
        if ("ANNUAL" in desc or "YEARLY" in desc or "QUARTER" in desc
                or "MONTHLY" in desc or "FORTNIGHT" in desc or "WEEKLY" in desc):
            freq = (
                "annual" if ("ANNUAL" in desc or "YEARLY" in desc)
                else "quarterly" if "QUARTER" in desc
                else "fortnightly" if "FORTNIGHT" in desc
                else "weekly" if "WEEKLY" in desc
                else "monthly"
            )
        elif hinted in {"weekly", "fortnightly", "monthly", "quarterly", "annual"} and hint_is_supported(
            hinted, len(rows), stream_months
        ):
            inferred = detect_frequency(dates)
            # Veto a cadence hint only when the dates are irregular AND the
            # amounts are multi-modal. A genuine fortnightly salary seen
            # through overlapping statements (gaps 25, 4, 28) is irregular in
            # the dates but all one amount — the hint is still right. Barfoot
            # ($2,880 rent + $54 fees, gaps [12,18,11,5,13,2,2]) fails both.
            amounts = [abs(float(r["amount"])) for r in rows]
            multi_modal = len({round(a, 2) for a in amounts}) > 1 and (
                max(amounts) > 2 * min(amounts) if amounts else False
            )
            freq = "irregular" if inferred == "irregular" and multi_modal else hinted
            # Weekly cadence with wildly different ticket sizes is a shopping
            # habit, not a bill. Honouring weekly on the largest shop is how
            # FU MARKET $222 × 52/12 became $963 from $645 of actual spend.
            if (
                freq in {"weekly", "fortnightly"}
                and category in {
                    "food_grocery_clothing_personal_care",
                    "transport",
                    "recreation_entertainment",
                }
                and amounts
                and max(amounts) > 3 * min(amounts)
            ):
                freq = "irregular"
        else:
            freq = detect_frequency(dates)
            if freq == "unknown":
                # One sighting cannot establish a grocery/dining/retail rhythm.
                # Treating it as irregular used to monthlyise Blue Sport $749.99
                # and Homeware $500 over the window.
                if len(rows) < 2:
                    freq = "one_off"
                elif category in {
                    "food_grocery_clothing_personal_care",
                    "transport",
                    "recreation_entertainment",
                    "other",
                }:
                    freq = "irregular"
                else:
                    freq = "monthly"

        income_amounts = [abs(float(r["amount"])) for r in rows]
        if (
            category in INCOME
            and freq == "monthly"
            and len(income_amounts) >= 2
            and max(income_amounts) > 2 * min(income_amounts)
        ):
            # $8,882 in July next to $3,500 in May is not an $8,881 monthly salary.
            freq = "irregular"

        typical = dominant_cluster_amount([r["amount"] for r in rows])
        run_rate = sum(abs(float(r["amount"])) for r in rows) / stream_months
        business_flag = _stream_business_flag(rows)
        business = business_flag == "yes"
        if freq == "irregular":
            # Normalise over the statement window of the account(s) this
            # stream actually appears in — not the merchant's own first-to-
            # last span, and not a longer household window from another
            # account. Three rent payments inside one month on a two-month
            # ANZ statement are two months of rent, not $7,200, and not a
            # 3.02-month Kiwibank discount either.
            monthly = (
                sum(abs(r["amount"]) for r in rows if r["direction"] == "outflow")
                / stream_months
            )
            # Repeating rent of $2,880 plus catch-up/fees must not average to
            # $4,116. If the same charge posted at least twice, that amount is
            # the monthly rent; the extras stay visible on Part 2.
            if category == "rent_board_paid" and dominant_cluster_size(
                [r["amount"] for r in rows]
            ) >= 2:
                monthly = monthly_equivalent(typical, "monthly")
        elif freq == "one_off" or freq == "unknown":
            monthly = 0.0
        else:
            monthly = monthly_equivalent(typical, freq)

        dates_observed = sorted({r["date"] for r in rows})
        calculation_basis = (
            (
                f"dominant repeating amount; extras not monthlyised"
                if freq == "irregular"
                and category == "rent_board_paid"
                and dominant_cluster_size([r["amount"] for r in rows]) >= 2
                else f"observed outflows / {stream_months:.2f} months{window_clause}"
            )
            if freq == "irregular"
            else "excluded: one-off/unknown cadence"
            if freq in {"one_off", "unknown"}
            else {
                "weekly": "average amount × 52 / 12",
                "fortnightly": "average amount × 26 / 12",
                "monthly": "average amount",
                "quarterly": "average amount / 3",
                "annual": "average amount / 12",
            }[freq]
        )
        calc = {
            "merchant": merchant,
            "category": category,
            "account_id": stream_account_id,
            "dates_observed": dates_observed,
            "average_amount": round(typical, 2),
            "dominant_amount": round(typical, 2),
            "observed_run_rate": round(run_rate, 2),
            "assessed_frequency": freq,
            "calculated_monthly_impact": round(monthly, 2),
            "calculation_basis": calculation_basis,
            "include": bool(rows[0].get("include")) and not business,
            "observations": len(rows),
            "is_business": business_flag,
        }
        calculations.append(calc)

        if category == "utilities":
            subtype = next((r.get("utility_type") for r in rows if r.get("utility_type")), None) or "other"
            utility_monthly[subtype] += monthly
        if category == "insurance":
            subtype = next((r.get("insurance_type") for r in rows if r.get("insurance_type")), None) or "other"
            insurance_monthly[subtype] += monthly

        if category in INCOME and rows[0]["direction"] == "inflow":
            income_rows.append(
                {
                    "source": merchant,
                    "type": category,
                    "amount_observed": typical,
                    "frequency": freq,
                    "monthly_equivalent": round(monthly_equivalent(typical, freq if freq != "unknown" else "irregular"), 2),
                    "evidence": ", ".join(sorted({r["date"] for r in rows})),
                }
            )
            # Income must be monthlyised the same way spending is, or the two
            # sides of the assessment disagree in the applicant's favour. A
            # single IRD refund of $4,217.53 was being reported as $4,217.53 a
            # month on top of a $3,459 salary - the file read as 122% more
            # income than the statements show. Meanwhile a one-off *expense*
            # contributes $0 a month. Both errors point the same way: towards
            # lending more than the evidence supports.
            if freq in {"one_off", "unknown"}:
                # Real money, but not a monthly amount. Show it, count it as
                # nothing recurring, and say why.
                income_rows[-1]["monthly_equivalent"] = 0.0
                income_rows[-1]["basis"] = (
                    "one-off receipt: listed, not counted as recurring income"
                )
            elif freq == "irregular":
                income_rows[-1]["monthly_equivalent"] = round(
                    sum(abs(r["amount"]) for r in rows) / stream_months, 2
                )
                income_rows[-1]["basis"] = (
                    f"observed receipts / {stream_months:.2f} months{window_clause}"
                )

        if category in SAVINGS_GIVING:
            savings_giving += monthly
            category_monthly[category] += monthly
        elif category in RECOMMENDED and not business:
            category_monthly[category] += monthly
        if business and rows[0]["direction"] == "outflow":
            business_monthly += monthly
        elif category == "one_off":
            for r in rows:
                one_offs.append(
                    {
                        "date": r["date"],
                        "description": r["description"],
                        "amount": r["amount"],
                        "reason": r.get("reason") or "one_off",
                    }
                )
        if freq == "one_off" and category != "one_off" and rows[0]["direction"] == "outflow":
            for r in rows:
                one_offs.append(
                    {
                        "date": r["date"],
                        "description": r["description"],
                        "amount": r["amount"],
                        "reason": r.get("reason") or "single observation - no cadence provable",
                    }
                )

        for r in rows:
            line_include = bool(r["include"]) and not business and freq != "one_off"
            if category in INCOME or category in EXCLUSIONS or category in SAVINGS_GIVING:
                line_include = False
            exclusion = ""
            if not line_include:
                if business:
                    why = r.get("business_reason") or "business / non-household"
                    exclusion = why if why.startswith("business") else f"business / non-household: {why}"
                elif category in INCOME:
                    exclusion = "income"
                elif freq == "one_off":
                    exclusion = "single observation - no cadence provable"
                elif category in EXCLUSIONS:
                    exclusion = category
                elif category in SAVINGS_GIVING:
                    exclusion = "savings / giving - listed, not recommended"
            acct = account_by_id.get(r.get("account_id")) or {}
            line_items.append(
                {
                    "date": r["date"],
                    "description": r["description"],
                    "amount": r["amount"],
                    "frequency": freq,
                    "include": "Yes" if line_include else "No",
                    "category": category,
                    "transaction_id": r["transaction_id"],
                    "source_file": r.get("source_file"),
                    "account": acct.get("account_label") or acct.get("institution") or "Not provided in binder",
                    "exclusion_reason": exclusion,
                    "needs_review": category in {"unclear", "underwriter_manual"}
                    or business_flag in {"yes", "review"},
                    "is_business": business_flag,
                }
            )

    for r in joined:
        if not r.get("extract_duplicate"):
            continue
        acct = account_by_id.get(r.get("account_id")) or {}
        line_items.append(
            {
                "date": r["date"],
                "description": r["description"],
                "amount": r["amount"],
                "frequency": "one_off",
                "include": "No",
                "category": r.get("category"),
                "transaction_id": r["transaction_id"],
                "source_file": r.get("source_file"),
                "account": acct.get("account_label") or acct.get("institution") or "Not provided in binder",
                "exclusion_reason": "duplicate extraction (descriptions match after bank prefix/suffix strip)",
                "needs_review": True,
                "is_business": r.get("is_business") or "no",
            }
        )

    recommended = sum(category_monthly[k] for k in RECOMMENDED)
    part1 = []
    for key, label in PART1_ROWS:
        if key == "utilities":
            notes = "; ".join(f"{k}: {v:.2f}" for k, v in sorted(utility_monthly.items())) or "No utility transactions identified"
        elif key == "insurance":
            notes = "; ".join(f"{k}: {v:.2f}" for k, v in sorted(insurance_monthly.items())) or "No insurance transactions identified"
        elif key == "recreation_entertainment":
            notes = f"Observed discretionary spend normalised over {observation_months:.2f} statement months"
        elif key == "monthly_subscriptions":
            notes = "See Part 2 calculation table for merchant cadence conversions"
        else:
            notes = f"Computed in code over {observation_months:.2f} statement months"
        part1.append(
            {
                "category": label,
                "monthly_equivalent": round(category_monthly.get(key, 0.0), 2),
                "notes": notes,
            }
        )
    part1.append({"category": "TOTAL RECURRING LIVING", "monthly_equivalent": round(recommended, 2), "notes": "MODEL DRAFT"})
    part1.append({"category": "TOTAL SAVINGS AND GIVING", "monthly_equivalent": round(savings_giving, 2), "notes": "MODEL DRAFT"})
    part1.append(
        {
            "category": "TOTAL ONE-OFF EXCLUDED",
            "monthly_equivalent": round(sum(x["amount"] for x in one_offs), 2),
            "notes": "MODEL DRAFT - raw sum, not monthlyised",
        }
    )
    part1.append({"category": "RECOMMENDED MONTHLY LIVING", "monthly_equivalent": round(recommended, 2), "notes": "MODEL DRAFT"})
    part1.append(
        {
            "category": "BUSINESS EXPENSES (not in recommended)",
            "monthly_equivalent": round(business_monthly, 2),
            "notes": (
                "NOT ASSESSED: no classification set is_business — recommended living may include business spend"
                if business_classification_missing
                else "Model-flagged business spend — reported, not household living"
            ),
        }
    )

    # Part 5 merchants: annualised recurring living, computed from the same
    # monthly stream values used in Part 1 (never relabel raw observed spend).
    annualised: dict[tuple[str, str], float] = defaultdict(float)
    annual_basis: dict[tuple[str, str], list[str]] = defaultdict(list)
    hits: dict[str, int] = defaultdict(int)
    for calc in calculations:
        if calc["include"] and calc["category"] in RECOMMENDED and calc["assessed_frequency"] not in {"one_off", "unknown"}:
            key = (calc["merchant"], calc["category"])
            annualised[key] += calc["calculated_monthly_impact"] * 12
            annual_basis[key].append(calc["calculation_basis"])
    for row in joined:
        if row["direction"] != "info":
            hits[row["merchant_normalized"]] += 1
    top = sorted(annualised.items(), key=lambda kv: kv[1], reverse=True)[:10]

    part4, liability_status = _liability_rows(accounts, joined, calculations)
    account_conduct = _conduct_rows(accounts)
    conduct_flags = sum(
        1 for row in account_conduct
        for check in (row.get("conduct") or {}).values()
        if isinstance(check, dict) and check.get("identified")
    )
    discretionary = round(category_monthly.get("recreation_entertainment", 0.0), 2)
    unclear_manual = sum(1 for r in joined if r["category"] in {"unclear", "underwriter_manual"})
    extraction_errors = canonical.get("errors") or []
    underwriter_notes = [
        {"topic": "File quality", "note": f"{len(accounts)} statement records; {len(txns)} canonical rows; {len(extraction_errors)} extraction errors.", "requires_signoff": bool(extraction_errors)},
        {
            "topic": "Account conduct",
            "note": (
                "NOT ASSESSABLE from extract: no running balance / limit / fee-code fields."
                if not any(
                    isinstance((row.get("conduct") or {}).get("arrears_or_overdrawn"), dict)
                    and "identified" in ((row.get("conduct") or {}).get("arrears_or_overdrawn") or {})
                    for row in account_conduct
                )
                else f"{conduct_flags} conduct exceptions identified across accepted statements."
            ),
            "requires_signoff": True if not conduct_flags else bool(conduct_flags),
        },
        {"topic": "Liabilities", "note": f"{len(part4)} evidenced facilities; status: {liability_status}.", "requires_signoff": bool(part4)},
        {"topic": "Discretionary spend", "note": f"Recreation and entertainment monthly equivalent: {discretionary:.2f}.", "requires_signoff": discretionary > 0},
        {"topic": "Unclear/manual", "note": f"{unclear_manual} transactions require manual review or remain unclear.", "requires_signoff": unclear_manual > 0},
    ]
    if business_classification_missing:
        underwriter_notes.insert(
            0,
            {
                "topic": "Business classification missing",
                "note": (
                    "No classification in this run set is_business, so recommended "
                    "living may include business spend. This was not assessed — "
                    "not the same as finding no business spend."
                ),
                "requires_signoff": True,
            },
        )

    return {
        "assessment_date": assessment_date,
        "applicant": canonical.get("applicant") or {
            "Full Name(s)": "Not provided in binder",
            "Age(s)": "Not provided in binder",
            "Dependants": "Not provided in binder",
            "Address and living situation": "Not provided in binder",
        },
        "accounts": accounts,
        "document_index": canonical.get("document_index") or [
            {
                "institution": a.get("institution"),
                "account_label": a.get("account_label") or "Not provided in binder",
                "account_type": a.get("account_type"),
                "period_start": a.get("period_start"),
                "period_end": a.get("period_end"),
                "days_covered": a.get("days_covered"),
                "days_old": a.get("days_old"),
                "source_file": a.get("source_file"),
            } for a in accounts if a.get("is_statement", True)
        ],
        "account_conduct": account_conduct,
        "income": income_rows,
        "part1": part1,
        "part2": sorted(line_items, key=lambda r: r["date"]),
        "part2_calculations": sorted(calculations, key=lambda r: (r["category"], r["merchant"])),
        "part3": one_offs,
        "part4": part4,
        "liability_evidence_status": liability_status,
        "subtype_breakdowns": {
            "utilities": [{"subtype": k, "monthly_equivalent": round(v, 2)} for k, v in sorted(utility_monthly.items())],
            "insurance": [{"subtype": k, "monthly_equivalent": round(v, 2)} for k, v in sorted(insurance_monthly.items())],
        },
        "recommended_monthly_living": round(recommended, 2),
        "business_monthly": round(business_monthly, 2),
        "part5": {
            "top_merchants": [
                {
                    "merchant": key[0],
                    "annual_spend": round(value, 2),
                    "category": key[1],
                    "calculation_basis": "; ".join(sorted(set(annual_basis[key]))),
                }
                for key, value in top
            ],
            "high_frequency": sorted(
                [{"merchant": m, "hits": n} for m, n in hits.items() if n >= 3],
                key=lambda r: (-r["hits"], r["merchant"]),
            ),
            "underwriter_notes": underwriter_notes,
        },
        "audit": {
            "transaction_count": len(txns),
            "info_rows_zeroed": sum(1 for t in txns if t.get("direction") == "info"),
            "rent_monthly": round(category_monthly.get("rent_board_paid", 0.0), 2),
            "is_business_classifications": n_explicit_business,
            "business_classification_missing": business_classification_missing,
        },
    }
