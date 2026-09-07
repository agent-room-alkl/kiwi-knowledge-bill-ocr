"""Offline tests for the normalize layer of extract_and_normalize.

No Azure credentials and no network. The layouts below are hand-built to match
what prebuilt-layout returns for the four fixtures in fixtures/samples/, with
the amounts copied verbatim from the PDFs.

Every assertion here corresponds to a bug that has actually shipped:
the salary read as `4`, the declined POSREJ row booked as $3,522 of groceries,
the balance column mistaken for the amount, and `03 Sept` given the wrong year.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "function_app"))

from extract_normalize import (  # noqa: E402
    ExtractionError,
    normalize,
    normalize_merchant,
    parse_money,
    parse_period,
    resolve_date,
    _applicant_evidence,
    _looks_like_person_name,
)

ASSESSMENT = "2026-09-01"
FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  PASS  {label}: {got!r}")
    else:
        FAILURES.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  FAIL  {label}: got {got!r}, want {want!r}")


def check_true(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {label}")
    else:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")
        print(f"  FAIL  {label} {detail}")


# ---------------------------------------------------------------- fixtures --

ANZ = {
    "source_file": "ANZ-everyday-FAKE-2026-07.pdf",
    "lines": [
        "ANZ (synthetic) Everyday Account Statement",
        "Account 01-0123-0456789-00   Alex Taylor   12 Example Street, Wellington 6011",
        "Statement period: 1 July 2026 – 31 July 2026",
        "Opening balance: $2,410.22    Closing balance: $3,186.47",
        "Applicant living situation (binder note): Renting. Age: Not provided in binder.",
    ],
    "tables": [
        {
            "page_number": 1,
            "rows": [
                ["Date", "Description", "Withdrawals", "Deposits", "Balance"],
                ["01 Jul 2026", "Opening balance", "", "", "2,410.22"],
                ["02 Jul 2026", "SALARY ACME NZ LTD", "", "4,820.00", "7,230.22"],
                ["04 Jul 2026", "RENT A. LANDLORD 12 EX ST", "2,400.00", "", "4,330.22"],
                ["05 Jul 2026", "Pak N Save Wairau Road Northshore NZL", "186.40", "", "4,143.82"],
                ["18 Jul 2026", "AA INSURANCE MOTOR ANNUAL", "1,200.00", "", "2,042.03"],
                ["31 Jul 2026", "Closing balance", "", "", "3,186.47"],
            ],
        }
    ],
}

KIWIBANK = {
    "source_file": "Kiwibank-everyday-FAKE-2026-06.pdf",
    "lines": [
        "Kiwibank (synthetic) Everyday Statement",
        "Statement period: 1 June 2026 – 30 June 2026",
        "Opening $1,102.00   Closing $1,548.10",
        "POSREJ = declined in-store; balance unchanged (Kiwibank help).",
    ],
    "tables": [
        {
            "page_number": 1,
            "rows": [
                ["Date", "Description", "Withdrawals", "Deposits", "Balance"],
                ["03 Jun 2026", "SALARY ACME LTD", "", "4,820.00", "5,922.00"],
                # Declined: no money column, only the unchanged running balance.
                ["06 Jun 2026", "POSREJ COUNTDOWN KARORI", "", "", "3,522.00"],
                ["10 Jun 2026", "RENT A. LANDLORD", "2,400.00", "", "3,522.00"],
            ],
        }
    ],
}

WESTPAC = {
    "source_file": "Westpac-mastercard-FAKE-2026-07.pdf",
    "lines": [
        "WESTPAC (SYNTHETIC) MASTERCARD STATEMENT",
        "Card •••• 4567   Alex Taylor   Credit limit $6,000.00",
        "Statement period: 8 June 2026 – 7 July 2026    Payment due: 1 August 2026",
        "Credit limit $6,000.00",
    ],
    "tables": [
        {
            "page_number": 1,
            "rows": [
                ["Date", "Process date", "Description", "Amount"],
                ["18 June", "19 June", "The Warehouse Glenfield Auckland NZL", "89.90"],
                ["22 June", "23 June", "Gull Albany Auckland NZL", "71.40"],
                ["05 July", "06 July", "PAYMENT THANK YOU", "200.00 CR"],
                ["03 July", "04 July", "Interest Purchases", "6.30"],
                # Balance-carrying, despite starting with "Interest".
                ["03 July", "04 July", "Interest Brought Forward", "23.40"],
                # The specimen dates its opening balance outside the period.
                ["03 Sept", "04 Sept", "Opening Balance", "47.24 CR"],
            ],
        }
    ],
}

ASB = {
    "source_file": "ASB-visa-FAKE-2026-05.pdf",
    "lines": [
        "ASB (synthetic) Visa Statement",
        "Card  2211   Alex Taylor   Limit $4,000.00",
        "Statement period: 1 May 2026 – 31 May 2026    Due: 25 June 2026",
        "Opening $210.00    Purchases $388.40    Payments $210.00    Closing $388.40",
    ],
    "tables": [
        {
            "page_number": 1,
            "rows": [
                ["Date", "Description", "Amount"],
                # Signed negative, and the wording is PAYMENT FROM - not
                # PAYMENT THANK YOU. Both signals must reach "inflow".
                ["02 May 2026", "PAYMENT FROM ASB 12-3456-7890123-00", "-210.00"],
                ["05 May 2026", "UBER EATS AUCKLAND", "34.50"],
                ["18 May 2026", "AIR NZ INTL SYDNEY  (one-off travel)", "289.00"],
            ],
        }
    ],
}

# A December -> January period, to prove the year rolls forward.
NEW_YEAR = {
    "source_file": "synthetic-newyear.pdf",
    "lines": [
        "BNZ (synthetic) Visa statement",
        "Statement period: 8 December 2025 – 7 January 2026",
        "Credit limit $3,000.00",
    ],
    "tables": [
        {
            "page_number": 1,
            "rows": [
                ["Date", "Description", "Amount"],
                ["20 Dec", "COUNTDOWN NEWMARKET", "88.20"],
                ["03 Jan", "SPOTIFY", "17.99"],
            ],
        }
    ],
}


def by_desc(txns, needle):
    return next(t for t in txns if needle.upper() in t["description"].upper())


# -------------------------------------------------------------------- tests --

print("== helpers ==")
check("parse_money 4,820.00", parse_money("4,820.00"), 4820.0)
check("parse_money $6,000.00", parse_money("$6,000.00"), 6000.0)
check("parse_money blank", parse_money(""), None)
try:
    parse_money("4,.00")
    check_true("parse_money rejects mangled '4,.00'", False, "no error raised")
except ExtractionError:
    check_true("parse_money rejects mangled '4,.00'", True)
try:
    parse_money("(cid:127)(cid:127) 2211")
    check_true("parse_money rejects '(cid:' text", False, "no error raised")
except ExtractionError:
    check_true("parse_money rejects '(cid:' text", True)

check(
    "parse_period ANZ",
    parse_period(ANZ["lines"]),
    (__import__("datetime").date(2026, 7, 1), __import__("datetime").date(2026, 7, 31)),
)
check(
    "parse_period label on the next line",
    parse_period(["· Statement period", "20 Jun 2026 - 19 Aug 2026", "20 Jun", "Opening balance"]),
    (__import__("datetime").date(2026, 6, 20), __import__("datetime").date(2026, 8, 19)),
)
check(
    "parse_period 'to' and long month name",
    parse_period(["Statement Period:", "20 May 2026 to 19 August 2026"]),
    (__import__("datetime").date(2026, 5, 20), __import__("datetime").date(2026, 8, 19)),
)
check(
    "parse_period numeric NZ range",
    parse_period(["Statement period 20/05/2026 - 19/08/2026"]),
    (__import__("datetime").date(2026, 5, 20), __import__("datetime").date(2026, 8, 19)),
)
_split = parse_period(["Statement period", "20 Jun 2026 - 19 Aug 2026"])
check(
    "yearless '22 Jun' uses the printed period year",
    resolve_date("22 Jun", _split[0], _split[1]),
    __import__("datetime").date(2026, 6, 22),
)
_card = parse_period(["Statement Period:", "20 May 2026 to 19 August 2026"])
check(
    "yearless '20 May' uses the printed period year",
    resolve_date("20 May", _card[0], _card[1]),
    __import__("datetime").date(2026, 5, 20),
)
check("normalize_merchant supermarket", normalize_merchant("Pak N Save Wairau Road Northshore NZL"), "PAK N SAVE")
check(
    "normalize_merchant two suburbs collapse to one key",
    normalize_merchant("Pak N Save Glenfield Auckland NZL"),
    normalize_merchant("Pak N Save New Lynn Auckland NZL"),
)

print("\n== ANZ everyday ==")
anz = normalize(ANZ, ASSESSMENT)
salary = by_desc(anz["transactions"], "SALARY")
check("salary amount is 4820, not 4", salary["amount"], 4820.0)
check("salary direction", salary["direction"], "inflow")
check("salary balance kept separate", salary["balance"], 7230.22)
check_true(
    "salary amount != its own balance",
    salary["amount"] != salary["balance"],
    f'{salary["amount"]} vs {salary["balance"]}',
)
rent = by_desc(anz["transactions"], "RENT")
check("rent amount positive", rent["amount"], 2400.0)
check("rent direction", rent["direction"], "outflow")
opening = by_desc(anz["transactions"], "Opening balance")
check("opening balance direction", opening["direction"], "info")
check("opening balance amount zeroed", opening["amount"], 0.0)
closing = by_desc(anz["transactions"], "Closing balance")
check("closing balance direction", closing["direction"], "info")
check("account type", anz["account"]["account_type"], "everyday")
check("institution", anz["account"]["institution"], "ANZ")
check("period start", anz["account"]["period_start"], "2026-07-01")
check("days covered", anz["account"]["days_covered"], 31)
check("days old vs 2026-09-01", anz["account"]["days_old"], 32)
check_true(
    "every row carries a raw_anchor",
    all(t.get("raw_anchor") for t in anz["transactions"]),
)
check_true(
    "every amount is positive",
    all(t["amount"] >= 0 for t in anz["transactions"]),
)

print("\n== Kiwibank: the POSREJ trap ==")
kb = normalize(KIWIBANK, ASSESSMENT)
posrej = by_desc(kb["transactions"], "POSREJ")
check("POSREJ amount", posrej["amount"], 0.0)
check("POSREJ direction", posrej["direction"], "info")
check("POSREJ balance still recorded", posrej["balance"], 3522.0)
check_true(
    "3522 never appears as an amount anywhere",
    all(t["amount"] != 3522.0 for t in kb["transactions"]),
)

print("\n== Westpac mastercard: card sign convention ==")
wp = normalize(WESTPAC, ASSESSMENT)
check("account type", wp["account"]["account_type"], "credit_card")
purchase = by_desc(wp["transactions"], "Warehouse")
check("card purchase is an outflow", purchase["direction"], "outflow")
check("card purchase amount", purchase["amount"], 89.90)
payment = by_desc(wp["transactions"], "PAYMENT THANK YOU")
check("card payment (CR) is an inflow", payment["direction"], "inflow")
check("card payment amount", payment["amount"], 200.0)
interest = by_desc(wp["transactions"], "Interest")
check("card interest is an outflow", interest["direction"], "outflow")
check("yearless '18 June' resolves to 2026-06-18", purchase["date"], "2026-06-18")
check("yearless '05 July' resolves to 2026-07-05", payment["date"], "2026-07-05")
check_true(
    "transaction date preferred over process date",
    purchase["date"] == "2026-06-18" and purchase.get("process_date") == "2026-06-19",
    f'date={purchase["date"]} process={purchase.get("process_date")}',
)
check("credit limit captured on the account", wp["account"].get("credit_limit"), 6000.0)

print("\n== December -> January year roll ==")
ny = normalize(NEW_YEAR, ASSESSMENT)
check("20 Dec stays in 2025", by_desc(ny["transactions"], "COUNTDOWN")["date"], "2025-12-20")
check("03 Jan rolls to 2026", by_desc(ny["transactions"], "SPOTIFY")["date"], "2026-01-03")

print("\n== unreadable file fails cleanly, never invents rows ==")
try:
    normalize({"source_file": "empty.pdf", "lines": ["nothing here"], "tables": []}, ASSESSMENT)
    check_true("empty layout raises ExtractionError", False, "no error raised")
except ExtractionError as exc:
    check_true("empty layout raises ExtractionError", True)
    print(f"        -> {exc}")

print("\n== ASB visa: signed payment (Cursor blocker 1) ==")
asb = normalize(ASB, ASSESSMENT)
pay = by_desc(asb["transactions"], "PAYMENT FROM ASB")
check("card payment amount is positive", pay["amount"], 210.0)
check("PAYMENT FROM ... -210.00 is an inflow", pay["direction"], "inflow")
eats = by_desc(asb["transactions"], "UBER EATS")
check("card purchase stays an outflow", eats["direction"], "outflow")
check("ASB account type", asb["account"]["account_type"], "credit_card")
check_true("ASB yields transactions", len(asb["transactions"]) == 3, str(len(asb["transactions"])))

print("\n== Westpac: Interest Brought Forward (Cursor blocker 2) ==")
ibf = by_desc(wp["transactions"], "Interest Brought Forward")
check("Interest Brought Forward direction", ibf["direction"], "info")
check("Interest Brought Forward amount", ibf["amount"], 0.0)
ip = by_desc(wp["transactions"], "Interest Purchases")
check("Interest Purchases is still an outflow", ip["direction"], "outflow")
check("Interest Purchases amount", ip["amount"], 6.30)
ob = by_desc(wp["transactions"], "Opening Balance")
check("out-of-period Opening Balance is info", ob["direction"], "info")
check("out-of-period Opening Balance not dated 2026-09-03", ob["date"], "2026-06-08")

print("\n== applicant / account_label / conduct from printed text only ==")
anz = normalize(ANZ, ASSESSMENT)
check("ANZ printed name", anz["account"]["applicant"]["Full Name(s)"], "Alex Taylor")
check(
    "PROCESS DATE is not treated as a person name",
    _applicant_evidence(["PROCESS DATE", "Account 01-0123-0456789-00   Alex Taylor"])["Full Name(s)"],
    "Alex Taylor",
)
unsplitting = _applicant_evidence(
    [
        "Account 01-0123-0456789-00 Alex Taylor 12 Example Street, Wellington 6011",
        "Statement period: 8 June 2026 - 7 July 2026 Payment due: 1 August 2026",
        "Applicant living situation (binder note): Renting.",
    ]
)
check("name from an unsplitting DI line", unsplitting["Full Name(s)"], "Alex Taylor")
check(
    "synthetic fixture banner is not a person name",
    _applicant_evidence(["ANZ (synthetic) Everyday Account Statement", "SYNTHETIC TEST FIXTURE", "Alex Taylor"])["Full Name(s)"],
    "Alex Taylor",
)
check_true(
    "address is the street, not the statement-period line",
    unsplitting["Address and living situation"].startswith("12 Example Street")
    and "August" not in unsplitting["Address and living situation"]
    and "Renting" in unsplitting["Address and living situation"],
    unsplitting["Address and living situation"],
)
check("ANZ age stays unset when the statement says so", anz["account"]["applicant"]["Age(s)"], "Not provided in binder")
check_true(
    "ANZ address and living situation are printed",
    "12 Example Street" in anz["account"]["applicant"]["Address and living situation"]
    and "Renting" in anz["account"]["applicant"]["Address and living situation"],
    anz["account"]["applicant"]["Address and living situation"],
)
check("ANZ account_label is the printed number", anz["account"]["account_label"], "01-0123-0456789-00")
check("Westpac card label is masked last-4", wp["account"]["account_label"], "Card ending 4567")
kb = normalize(KIWIBANK, ASSESSMENT)
check_true(
    "POSREJ is recorded as irregular activity, not omitted",
    kb["account"]["conduct"]["irregular_activity"]["identified"] is True,
    str(kb["account"]["conduct"]["irregular_activity"]),
)
check_true(
    "clean fee check says none identified",
    kb["account"]["conduct"]["late_dishonour_unarranged_fees"]["identified"] is False,
    str(kb["account"]["conduct"]["late_dishonour_unarranged_fees"]),
)

print("\n== account type comes from the masthead, not transaction text ==")
# Found only by the first live Document Intelligence run: the ANZ everyday
# statement was typed as a credit card because a transaction line reads
# `TFR TO VISA 4567`. Cash accounts pay off cards; that does not make them one.
# Shaped the way Document Intelligence actually emitted this file on the first
# live run: header cells and ledger text both appear in page.lines.
ANZ_WITH_VISA_ROW = {
    **ANZ,
    "lines": ANZ["lines"] + [
        "Date", "Description", "Withdrawals", "Deposits", "Balance",
        "03 Jul 2026", "TFR TO VISA 4567", "500.00",
    ],
}
check(
    "everyday statement mentioning VISA in a transaction stays everyday",
    normalize(ANZ_WITH_VISA_ROW, ASSESSMENT)["account"]["account_type"],
    "everyday",
)
check("mastercard masthead still detected", normalize(WESTPAC, ASSESSMENT)["account"]["account_type"], "credit_card")
check("visa masthead still detected", normalize(ASB, ASSESSMENT)["account"]["account_type"], "credit_card")

print("\n== a posted row with an unreadable date is reported, never dropped ==")
BAD = {
    "source_file": "bad-date.pdf",
    "lines": ["Kiwibank (synthetic)", "Statement period: 1 June 2026 – 30 June 2026"],
    "tables": [{"page_number": 1, "rows": [
        ["Date", "Description", "Withdrawals", "Deposits", "Balance"],
        ["", "PAK N SAVE WAIRAU", "186.40", "", "3,000.00"],
    ]}],
}
try:
    normalize(BAD, ASSESSMENT)
    check_true("unreadable date on a posted row raises", False, "no error raised")
except ExtractionError as exc:
    check_true("unreadable date on a posted row raises", True)
    print(f"        -> {exc}")

print("\n== totals-at-end-of-page is chrome, not a posting ==")
TOTALS_PAGE = {
    "source_file": "kiwibank-realish.pdf",
    "lines": [
        "Kiwibank (synthetic)",
        "Statement period",
        "20 Jun 2026 - 19 Aug 2026",
    ],
    "tables": [{"page_number": 1, "rows": [
        ["Date", "Description", "Withdrawals", "Deposits", "Balance"],
        ["22 Jun", "COUNTDOWN ALBANY", "86.40", "", "1,200.00"],
        ["Totals at end", "of page", "86.40", "", "1,200.00"],
    ]}],
}
totals_batch = normalize(TOTALS_PAGE, ASSESSMENT)
check("totals row does not reject the file", totals_batch["account"]["is_statement"], True)
check("posted row still extracted", len([t for t in totals_batch["transactions"] if t["amount"] == 86.4]), 1)
check(
    "totals chrome is not a transaction",
    any("of page" in t["description"].lower() for t in totals_batch["transactions"]),
    False,
)

print("\n== file_urls input path (the contract an agent can actually call) ==")
import os  # noqa: E402
from extract_normalize import (  # noqa: E402
    allowed_host_suffixes, fetch_url, _normalise_url_entry,
    extract_and_normalize as run_batch,
)

check("bare URL string accepted", _normalise_url_entry("https://x/y/a.pdf"), (None, "https://x/y/a.pdf"))
check("object form accepted", _normalise_url_entry({"filename": "anz.pdf", "url": "https://x/a.pdf"}),
      ("anz.pdf", "https://x/a.pdf"))
for bad, label in [({"filename": "a.pdf"}, "object with no url"), (42, "non-string non-object")]:
    try:
        _normalise_url_entry(bad)
        check_true(f"rejects {label}", False, "no error raised")
    except ExtractionError:
        check_true(f"rejects {label}", True)
# SSRF: these URLs arrive from a model, which took them from a user message.
# Without an allowlist this function hands out the app's managed-identity token.
SSRF_CASES = [
    ("file:///etc/passwd",                                   "non-https scheme"),
    ("http://rgkiwidemo88cf.blob.core.windows.net/a.pdf",    "plain http even on an allowed host"),
    ("https://169.254.169.254/metadata/identity/oauth2/token", "IMDS metadata endpoint"),
    ("https://127.0.0.1/a.pdf",                              "loopback"),
    ("https://10.0.0.5/a.pdf",                               "private range"),
    ("https://evil.example.com/a.pdf",                       "host outside the allowlist"),
    ("https:///a.pdf",                                       "no host"),
]
for bad_url, label in SSRF_CASES:
    try:
        fetch_url(bad_url, timeout=5)
        check_true(f"blocks {label}", False, "no error raised")
    except ExtractionError:
        check_true(f"blocks {label}", True)
    except Exception as exc:  # a network error would mean the guard did not fire first
        check_true(f"blocks {label}", False, f"wrong error {type(exc).__name__}: {exc}")

check("allowlist default", allowed_host_suffixes(), (".blob.core.windows.net",))
os.environ["EXTRACT_URL_ALLOWED_HOSTS"] = "files.example.com,.blob.core.windows.net"
check("allowlist honours env override", allowed_host_suffixes(),
      ("files.example.com", ".blob.core.windows.net"))
del os.environ["EXTRACT_URL_ALLOWED_HOSTS"]

try:
    run_batch(None, ASSESSMENT, file_urls=None)
    check_true("no files and no file_urls is an error", False, "no error raised")
except ExtractionError as exc:
    check_true("no files and no file_urls is an error", True)
    print(f"        -> {exc}")

print("\n== binder input path (no URL, no credential leaves the server) ==")
from extract_normalize import validate_binder, allowed_binders  # noqa: E402

os.environ["EXTRACT_ALLOWED_BINDERS"] = "vikas-samples"
check("valid container name accepted", validate_binder("vikas-samples"), "vikas-samples")
check("uppercase is normalised", validate_binder("Vikas-Samples"), "vikas-samples")
for bad, label in [
    ("../etc",              "path traversal"),
    ("vikas/samples",       "slash"),
    ("ab",                  "too short"),
    ("a" * 64,              "too long"),
    ("vikas--samples",      "double hyphen"),
    ("-vikas",              "leading hyphen"),
    ("vikas_samples",       "underscore"),
    ("",                    "empty"),
]:
    try:
        validate_binder(bad)
        check_true(f"rejects {label}", False, f"accepted {bad!r}")
    except ExtractionError:
        check_true(f"rejects {label}", True)

# Fail-closed: a missing allowlist is a misconfiguration, not permission.
_saved = os.environ.pop("EXTRACT_ALLOWED_BINDERS", None)
try:
    allowed_binders()
    check_true("unset allowlist refuses every binder", False, "no error raised")
except ExtractionError:
    check_true("unset allowlist refuses every binder", True)
try:
    validate_binder("azure-webjobs-secrets")
    check_true("unset allowlist blocks the secrets container", False, "accepted it")
except ExtractionError:
    check_true("unset allowlist blocks the secrets container", True)
if _saved is not None:
    os.environ["EXTRACT_ALLOWED_BINDERS"] = _saved

os.environ["EXTRACT_ALLOWED_BINDERS"] = "vikas-samples,client-binders"
check("allowlist honours env", allowed_binders(), ("vikas-samples", "client-binders"))
check("allowlisted binder passes", validate_binder("vikas-samples"), "vikas-samples")
try:
    validate_binder("some-other-container")
    check_true("blocks a binder outside the allowlist", False, "no error raised")
except ExtractionError:
    check_true("blocks a binder outside the allowlist", True)
del os.environ["EXTRACT_ALLOWED_BINDERS"]

try:
    run_batch(None, ASSESSMENT, file_urls=None, binder=None)
    check_true("no binder, no urls, no files is an error", False, "no error raised")
except ExtractionError as exc:
    check_true("no binder, no urls, no files is an error", True)
    print(f"        -> {exc}")

print("\n== schema conformance ==")
REQUIRED_TXN = {"transaction_id", "account_id", "date", "description", "amount", "direction", "source_file"}
ALLOWED_TXN = REQUIRED_TXN | {"process_date", "merchant_normalized", "balance", "raw_amount_text", "raw_anchor"}
REQUIRED_ACC = {"account_id", "institution", "account_type", "period_start", "period_end", "source_file"}
ALLOWED_ACC = REQUIRED_ACC | {
    "account_label", "days_covered", "days_old", "opening_balance",
    "closing_balance", "credit_limit", "is_statement", "reject_reason",
    "applicant", "conduct",
}
DIRECTIONS = {"inflow", "outflow", "info"}
TYPES = {"everyday", "savings", "credit_card", "loan", "other"}

all_batches = [anz, kb, wp, ny, asb]
bad = []
ids = set()
for b in all_batches:
    acc = b["account"]
    if not REQUIRED_ACC <= set(acc) or not set(acc) <= ALLOWED_ACC:
        bad.append(f"account keys off for {acc['source_file']}: {sorted(set(acc) ^ ALLOWED_ACC)}")
    if acc["account_type"] not in TYPES:
        bad.append(f"bad account_type {acc['account_type']}")
    for t in b["transactions"]:
        if not REQUIRED_TXN <= set(t) or not set(t) <= ALLOWED_TXN:
            bad.append(f"txn keys off: {sorted(set(t) - ALLOWED_TXN)}")
        if t["direction"] not in DIRECTIONS:
            bad.append(f"bad direction {t['direction']}")
        if t["amount"] < 0:
            bad.append(f"negative amount {t['amount']}")
        ids.add(t["transaction_id"])

total = sum(len(b["transactions"]) for b in all_batches)
check_true("no unexpected / missing schema fields", not bad, "; ".join(bad[:3]))
check("transaction_ids are unique", len(ids), total)

print("\n" + "=" * 62)
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print(f"All checks passed. {total} transactions across {len(all_batches)} synthetic layouts.")


print("== the applicant name field must not be filled from an address ==")
# Shape taken from a real NZ statement header. Before this guard, the holder
# name came out as "LAURINA ROAD; Private Bag" on a lending assessment.
_addr_header = [
    "ANZ Bank New Zealand Limited",
    "MR A TAYLOR",
    "12 Laurina Road",
    "Private Bag 92046",
    "Auckland 1142",
]
_got = _applicant_evidence(_addr_header)["Full Name(s)"]
check_true("a street name is not offered as the account holder", "LAURINA" not in _got.upper(), _got)
check_true("a postal address is not offered either", "PRIVATE BAG" not in _got.upper(), _got)
check("an unreadable name says so rather than guessing", _got, "Not provided in binder")

for _bad in ["Laurina Road", "Private Bag", "Po Box", "Barfoot Limited", "Smales Trust"]:
    check_true(f"{_bad!r} is not a person", not _looks_like_person_name(_bad), _bad)
for _good in ["Alex Taylor", "Wei Zhang", "Mary-Jane O'Brien"]:
    check_true(f"{_good!r} still reads as a person", _looks_like_person_name(_good), _good)

# Regression: a holder name sharing one unsplit DI line with an address must
# still be found. Cutting the whole line lost it; cutting only the address span
# keeps it.
check("a holder name beside an address is still extracted",
      _applicant_evidence(["Account 01-0123-0456789-00 Alex Taylor 12 Example Street, Wellington 6011"])
      ["Full Name(s)"], "Alex Taylor")
