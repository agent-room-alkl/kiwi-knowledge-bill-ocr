# -*- coding: utf-8 -*-
"""Offline checks for the canonical batch store and truncation diagnostics.

No Azure calls: the blob layer is stubbed. What is under test is the id format,
the refusal to read anything that is not a batch, and whether a truncated
payload is reported as truncated instead of as a NoneType crash.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "function_app"))

import extract_normalize as E  # noqa: E402

FAILURES: list[str] = []


def check(label, cond, detail=""):
    if cond:
        print(f"  PASS  {label}{(': ' + str(detail)) if detail else ''}")
    else:
        FAILURES.append(label)
        print(f"  FAIL  {label}: {detail}")


def raises(label, fn, expect_substring=""):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        ok = expect_substring.lower() in str(exc).lower()
        check(label, ok, str(exc)[:110] if ok else f"wrong message: {exc}")
        return
    check(label, False, "did not raise")


print("== batch_id format ==")
good = "68b6a1f0T0c3d5e-9f2c4a7b1d8e0f36"
check("well-formed id accepted", E.validate_batch_id(good) == good, good)
check("surrounding whitespace tolerated", E.validate_batch_id(f"  {good} ") == good)

for bad, why in [
    ("../etc/passwd", "path traversal"),
    ("vikas-samples", "a container name is not a batch id"),
    ("azure-webjobs-secrets", "the secrets container is not a batch id"),
    (f"{good}/../other", "traversal appended to a valid id"),
    (f"{good}.json", "blob name rather than id"),
    ("68b6a1f0T0c3d5-9f2c4a7b1d8e0f36", "one hex digit short"),
    ("68B6A1F0T0C3D5E-9F2C4A7B1D8E0F36", "uppercase"),
    ("", "empty"),
    (None, "none"),
]:
    raises(f"rejects {why}", lambda b=bad: E.validate_batch_id(b), "not a valid id")

print("\n== a generated id validates, and ids do not collide ==")
seen = set()
for _ in range(200):
    from datetime import datetime, timezone
    import os as _os

    stamp = f"{int(datetime.now(timezone.utc).timestamp()):08x}"
    bid = f"{stamp}T{_os.urandom(3).hex()}-{_os.urandom(8).hex()}"
    E.validate_batch_id(bid)
    seen.add(bid)
check("200 generated ids all valid and distinct", len(seen) == 200, len(seen))

print("\n== store/load round trip (blob layer stubbed) ==")

# The azure SDK is not installed here on purpose: this suite must run offline.
# Only the one exception type load_batch catches is needed.
import types  # noqa: E402

if "azure.core.exceptions" not in sys.modules:
    class ResourceNotFoundError(Exception):
        pass

    _azure = types.ModuleType("azure")
    _core = types.ModuleType("azure.core")
    _exc = types.ModuleType("azure.core.exceptions")
    _exc.ResourceNotFoundError = ResourceNotFoundError
    _core.exceptions = _exc
    _azure.core = _core
    sys.modules.update(
        {"azure": _azure, "azure.core": _core, "azure.core.exceptions": _exc}
    )

STORE: dict[str, bytes] = {}


class _FakeBlob:
    def __init__(self, name):
        self.name = name

    def readall(self):
        from azure.core.exceptions import ResourceNotFoundError

        if self.name not in STORE:
            raise ResourceNotFoundError(self.name)
        return STORE[self.name]


class _FakeContainer:
    def upload_blob(self, name, data, overwrite=False):
        if name in STORE and not overwrite:
            raise AssertionError("id collision")
        STORE[name] = data

    def download_blob(self, name):
        return _FakeBlob(name)


E._batches_container = lambda: _FakeContainer()  # noqa: SLF001

batch = {
    "assessment_date": "2026-09-02",
    "transactions": [{"transaction_id": "a1", "amount": 4.5, "description": "PARKABLE"}],
    "accounts": [{"account_id": "b1", "period_start": "2026-05-20"}],
}
bid = E.store_batch(batch)
check("store returns a valid id", E.validate_batch_id(bid) == bid, bid)
check("round trip is byte-faithful", E.load_batch(bid) == batch)
check("stored under <id>.json only", list(STORE) == [f"{bid}.json"], list(STORE))

raises(
    "a missing batch is reported, not returned empty",
    lambda: E.load_batch("00000000T000000-0000000000000000"),
    "no stored batch",
)
raises("load validates the id too", lambda: E.load_batch("../etc"), "not a valid id")

print("\n== truncation diagnostics ==")
sys.path.insert(0, str(ROOT))


def _check_not_truncated(canonical, classifications):
    """Mirror of the route helper, imported without azure.functions present."""
    src = (ROOT / "function_app" / "function_app.py").read_text()
    start = src.index("def _check_not_truncated")
    end = src.index('@app.route(route="compute_summary"')
    ns: dict = {}
    exec(compile(src[start:end], "function_app.py", "exec"), ns)  # noqa: S102
    return ns["_check_not_truncated"](canonical, classifications)


good_canon = {"transactions": [{"transaction_id": "a1"}, {"transaction_id": "a2"}]}
good_cls = {"classifications": [{"transaction_id": "a1", "category": "transport"}]}
try:
    _check_not_truncated(good_canon, good_cls)
    check("a healthy payload passes", True)
except Exception as exc:  # noqa: BLE001
    check("a healthy payload passes", False, exc)

# This is robin's actual failure: seven rows then a null.
raises(
    "trailing null in transactions is called truncation",
    lambda: _check_not_truncated(
        {"transactions": [{"transaction_id": "a1"}, None]}, good_cls
    ),
    "truncated in transit",
)
raises(
    "the message names the batch_id remedy",
    lambda: _check_not_truncated(
        {"transactions": [{"transaction_id": "a1"}, None]}, good_cls
    ),
    "pass the batch_id",
)
raises(
    "null inside classifications is caught too",
    lambda: _check_not_truncated(good_canon, {"classifications": [None]}),
    "truncated in transit",
)
raises(
    "a classification naming neither row nor merchant is caught",
    lambda: _check_not_truncated(
        good_canon, {"classifications": [{"category": "transport"}]}
    ),
    "neither a transaction_id nor a merchant",
)
# Regression: the truncation guard must not reject the merchant-keyed shape it
# was written before. It demanded transaction_id on every entry, which would
# have rejected every worklist classification the moment both shipped together.
try:
    _check_not_truncated(
        good_canon, {"classifications": [{"merchant": "FU MARKET", "category": "food"}]}
    )
    check("a merchant-keyed classification is accepted", True)
except Exception as exc:  # noqa: BLE001
    check("a merchant-keyed classification is accepted", False, exc)



print("\n== classification worklist ==")
wl_batch = {
    "transactions": [
        {"transaction_id": "t1", "merchant_normalized": "FU MARKET", "amount": 20.0,
         "direction": "outflow", "date": "2026-06-27", "description": "FU MARKET 483561 ****** 7996"},
        {"transaction_id": "t2", "merchant_normalized": "FU MARKET", "amount": 40.0,
         "direction": "outflow", "date": "2026-07-04", "description": "FU MARKET 483561 ****** 7996"},
        {"transaction_id": "t3", "merchant_normalized": "OPENING BALANCE", "amount": 0.0,
         "direction": "info", "date": "2026-06-01", "description": "Opening Balance"},
        {"transaction_id": "t4", "merchant_normalized": "ACME PAY", "amount": 5000.0,
         "direction": "inflow", "date": "2026-06-15", "description": "DIRECT CREDIT ACME"},
    ]
}
wl = E.classification_worklist(wl_batch)
by = {e["merchant"]: e for e in wl}
check("info rows are not put to the model", "OPENING BALANCE" not in by, sorted(by))
check("one entry per merchant, not per row", len(wl) == 2, len(wl))
check("repeat visits collapse to one question", by["FU MARKET"]["occurrences"] == 2)
check("total spend is summed", by["FU MARKET"]["total_amount"] == 60.0)
check("median is reported", by["FU MARKET"]["median_amount"] == 30.0)
check("date span is reported", by["FU MARKET"]["first_date"] == "2026-06-27")
check("direction carried", by["ACME PAY"]["direction"] == "inflow")
check("biggest spend sorts first", wl[0]["merchant"] == "ACME PAY", wl[0]["merchant"])

print("\n== merchant-level classification fans out to every row ==")
sys.path.insert(0, str(ROOT / "function_app"))
from compute_summary import _index_classifications  # noqa: E402

txns = wl_batch["transactions"]
idx = _index_classifications(
    {"classifications": [{"merchant": "FU MARKET", "category": "food_grocery_clothing_personal_care",
                          "include_in_living_expenses": True}]},
    txns,
)
check("both Fu Market rows get the category", 
      idx.get("t1", {}).get("category") == "food_grocery_clothing_personal_care"
      and idx.get("t2", {}).get("category") == "food_grocery_clothing_personal_care")
check("an unclassified merchant stays unclassified", "t4" not in idx, sorted(idx))

idx2 = _index_classifications(
    {"classifications": [
        {"merchant": "FU MARKET", "category": "food_grocery_clothing_personal_care"},
        {"transaction_id": "t2", "category": "recreation_entertainment"},
    ]},
    txns,
)
check("a per-row classification overrides the merchant default",
      idx2["t2"]["category"] == "recreation_entertainment"
      and idx2["t1"]["category"] == "food_grocery_clothing_personal_care")

print("\n== merchant keys drop the bank's own furniture ==")
for raw, want in [
    ("FU MARKET 483561 ****** 7996 Orig date 27/06/2026", "FU MARKET"),
    ("Costco Whs Auckland 483561 ****** 7996 C", "COSTCO WHS"),
    ("Pak N Save Wairau Road Northshore NZL", "PAK N SAVE"),
]:
    got = E.normalize_merchant(raw)
    check(f"{want} key is clean", got == want, got)
check("dangling hyphen after bank prefix is stripped",
      E.normalize_merchant("Direct Debit -PARTNERS LIFE LIMITED") == "PARTNERS LIFE LIMITED")
check("the unprefixed form is the same key",
      E.normalize_merchant("PARTNERS LIFE LIMITED") == "PARTNERS LIFE LIMITED")
check("GoCardless hyphen form collapses",
      E.normalize_merchant("Direct Debit -GOCARDLESS LTD") == "GOCARDLESS LTD")
check("a real name is not over-stripped",
      E.normalize_merchant("PAYDAY LOANS LTD") == "PAYDAY LOANS LTD")



print("\n== a trimmed summary is refused, and named as trimmed ==")


def _check_summary_intact(summary):
    src = (ROOT / "function_app" / "function_app.py").read_text()
    start = src.index("def _check_summary_intact")
    end = src.index("def _xlsx_base64")
    ns: dict = {}
    exec(compile(src[start:end], "function_app.py", "exec"), ns)  # noqa: S102
    return ns["_check_summary_intact"](summary)


try:
    _check_summary_intact({"part1": [{"category": "Transport"}], "part2": [{"date": "2026-06-01"}]})
    check("a whole summary passes", True)
except Exception as exc:  # noqa: BLE001
    check("a whole summary passes", False, exc)

# Exactly what a real run sent when asked to resend the summary.
raises(
    "a placeholder string among the rows is called out",
    lambda: _check_summary_intact(
        {"part2": [{"date": "2026-05-20"}, "... trimmed for brevity in this call ..."]}
    ),
    "abbreviated instead of sent whole",
)
raises(
    "the message names summary_id as the remedy",
    lambda: _check_summary_intact({"part2": [{"date": "x"}, "..."]}),
    "pass the `summary_id`",
)
raises(
    "part2_calculations is checked too",
    lambda: _check_summary_intact({"part2_calculations": [{"merchant": "X"}, "..."]}),
    "abbreviated instead of sent whole",
)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
    raise SystemExit(1)
print(f"All checks passed. {len(STORE)} batch(es) stored, ids validated.")
