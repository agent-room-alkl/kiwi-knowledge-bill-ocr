# -*- coding: utf-8 -*-
"""Seed function_app/merchant_memory.json from a run an underwriter accepted.

    python pipeline/build_merchant_memory.py CANONICAL.json SUMMARY.json \
        [--out function_app/merchant_memory.json] [--label "2026-09-17 accepted run"]

CANONICAL is the batch extract_and_normalize stored for the run (it carries
merchant_normalized, direction and source_file per transaction); SUMMARY is
the summary compute_summary stored for the same run (its part2 carries the
classification each row ended up with). Both live in the vikas-batches
container.

Only rows the model actually classified are learned, and never `unclear`.
A merchant that was put in two different categories within the run is left
out rather than guessed.

Only reusable public brand knowledge is written out - see `_is_public_brand`.
Nothing about the applicant is kept: no payer names, no inflows, no statement
filenames. Ordinary/sample brands remain as an interim fallback; after the
agent has been shown to recognise one reliably, that entry can be removed.
Who paid the applicant is recognised at classification time from the shape
of the name, by compute_summary.payer_classification, so it works on a binder
this file has never seen.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "function_app"))

from compute_summary import (  # noqa: E402
    GLOBAL_MEMORY_CATEGORIES,
    INCOME_TYPES,
    INSURANCE_TYPES,
    UTILITY_TYPES,
    merchant_join_key,
)
from extract_normalize import (  # noqa: E402
    _CARD_PAN_RE,
    _ORIG_DATE_RE,
    looks_like_payer_name,
    normalize_merchant,
)

# subtype_breakdowns labels written by the engine before the enums settled.
_LEGACY_SUBTYPES = {
    "mobile": "phone_mobile",
    "mobile_broadband": "internet",
    "broadband": "internet",
    "life": "life_personal_risk",
}


def _single_subtype(summary: dict, block: str, allowed: frozenset) -> str | None:
    """The subtype for a category only when the run saw exactly one."""
    rows = (summary.get("subtype_breakdowns") or {}).get(block) or []
    subtypes = {_LEGACY_SUBTYPES.get(r.get("subtype"), r.get("subtype")) for r in rows}
    if len(subtypes) == 1:
        (only,) = subtypes
        return only if only in allowed else None
    return None


def _public_descriptor(description: str) -> str:
    """A descriptor with the cardholder's own details taken out.

    Descriptors are stored raw so the loader can re-key them under whatever
    the normaliser does on the day it runs. Raw turned out to include the
    card the applicant paid with - 28 of them read like `ACE99 BAKERY
    483561 ****** 7996 Orig date 01/08/2026`, and a BIN with the last four
    digits belongs to one person, not to the bakery. normalize_merchant
    strips both of these before keying anyway, so nothing is lost by
    removing them here as well.
    """
    text = _CARD_PAN_RE.sub(" ", description)
    text = re.sub(_ORIG_DATE_RE.pattern, "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def _is_public_brand(
    key: str,
    direction: str,
    category: str,
) -> bool:
    """True for merchant knowledge that is safe to reuse across applicants.

    Memory used to keep everything the accepted run classified, pinning the
    applicant-specific part to the statement files it came from. That made
    it a file about one applicant: 94 of its 234 entries were keyed by the
    names of people who had paid them, and the pinned filenames carried the
    account number. It also did not generalise - the next applicant has
    different payers, so none of those entries could ever match again.

    Public outflow brands remain as an interim fallback. Payer names and all
    inflows are excluded, and what is left needs no file pinning, which is why
    no entry carries source_files any more.

    A brand may still be reusable when this applicant used it for business,
    but that applicant-specific judgement is not. The builder keeps the
    merchant category and rewrites business=yes to review + conservative
    living-expense inclusion below.
    """
    return (
        direction == "outflow"
        and category in GLOBAL_MEMORY_CATEGORIES
        and not looks_like_payer_name(key)
    )


def _schema_categories() -> frozenset:
    """Categories the classification schema accepts today.

    An older run can carry names the taxonomy has since retired
    (`education_childcare`, `bank_fees`); replaying those would put an
    invalid category into a live report, so they are dropped, not mapped.
    """
    schema = json.loads((ROOT / "schemas" / "classification.schema.json").read_text(encoding="utf-8"))
    return frozenset(schema["$defs"]["category"]["enum"])


def build(canonical: dict, summary: dict, label: str) -> dict:
    allowed = _schema_categories()
    txns = {t["transaction_id"]: t for t in canonical.get("transactions") or []}
    utility_type = _single_subtype(summary, "utilities", UTILITY_TYPES)
    insurance_type = _single_subtype(summary, "insurance", INSURANCE_TYPES)

    groups: dict[tuple[str, str], list[tuple[dict, dict]]] = defaultdict(list)
    for row in summary.get("part2") or []:
        if not row.get("classified") or row.get("category") in {None, "unclear"}:
            continue
        txn = txns.get(row.get("transaction_id"))
        if txn is None or txn.get("direction") not in {"inflow", "outflow"}:
            continue
        # Group under today's normaliser, not the merchant_normalized frozen
        # into the old batch: two spellings that now fold together must be
        # checked for agreement here, or they would collide at load time.
        description = str(txn.get("description") or "")
        key = merchant_join_key(normalize_merchant(description)) or merchant_join_key(description)
        if key:
            groups[(key, txn["direction"])].append((row, txn))

    entries, conflicts, retired, private = [], [], [], []
    for (key, direction), members in sorted(groups.items()):
        decisions = {
            (r["category"], str(r.get("is_business") or "no").lower()) for r, _ in members
        }
        if len(decisions) != 1:
            conflicts.append({"key": key, "direction": direction, "seen": sorted(decisions)})
            continue
        (category, is_business) = next(iter(decisions))
        if category not in allowed:
            retired.append({"key": key, "direction": direction, "category": category})
            continue
        if not _is_public_brand(key, direction, category):
            private.append({"key": key, "direction": direction, "category": category})
            continue
        first = members[0][0]
        applicant_business = is_business == "yes"
        entry = {
            "key": key,
            "direction": direction,
            "category": category,
            "include_in_living_expenses": (
                True if applicant_business else bool(first.get("include"))
            ),
            "is_business": "review" if applicant_business else is_business,
            "reason": (
                f"{category} brand; business use needs current-applicant review"
                if applicant_business
                else str(first.get("reason") or "").strip() or category
            ),
            "rows_seen": len(members),
            # Raw descriptors, so the loader can re-key them with whatever
            # the normaliser does on the day it runs.
            "descriptors": sorted(
                {_public_descriptor(str(t.get("description") or "")) for _, t in members} - {""}
            ),
        }
        if category == "utilities" and utility_type:
            entry["utility_type"] = utility_type
        if category == "insurance" and insurance_type:
            entry["insurance_type"] = insurance_type
        if category in INCOME_TYPES:
            entry["income_type"] = category
        entries.append(entry)

    return {
        "version": 1,
        "seeded_from": {
            "label": label,
            "assessment_date": summary.get("assessment_date"),
            "part2_rows": len(summary.get("part2") or []),
        },
        "entries": entries,
        # Skipped candidates are counts, not lists: listing them would put
        # sample-derived merchant/payer text back into the reviewed config.
        "conflicts_skipped_count": len(conflicts),
        "retired_categories_skipped_count": len(retired),
        "applicant_specific_skipped_count": len(private),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("canonical")
    ap.add_argument("summary")
    ap.add_argument("--out", default=str(ROOT / "function_app" / "merchant_memory.json"))
    ap.add_argument("--label", default="accepted run")
    args = ap.parse_args()
    canonical = json.loads(Path(args.canonical).read_text(encoding="utf-8"))
    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    memory = build(canonical, summary, args.label)
    Path(args.out).write_text(
        json.dumps(memory, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        f"{len(memory['entries'])} reusable public brands remembered; "
        f"{memory['applicant_specific_skipped_count']} skipped as applicant-specific, "
        f"{memory['conflicts_skipped_count']} skipped as conflicting, "
        f"{memory['retired_categories_skipped_count']} skipped for a retired category -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
