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
out rather than guessed. See compute_summary.memory_classification for how
the result is applied and why most entries are pinned to their source files.
"""

from __future__ import annotations

import argparse
import json
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
from extract_normalize import normalize_merchant  # noqa: E402

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


def _is_global(direction: str, category: str, is_business: str) -> bool:
    return (
        direction == "outflow"
        and category in GLOBAL_MEMORY_CATEGORIES
        and is_business != "yes"
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

    entries, conflicts, retired = [], [], []
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
        first = members[0][0]
        entry = {
            "key": key,
            "direction": direction,
            "category": category,
            "include_in_living_expenses": bool(first.get("include")),
            "is_business": is_business,
            "reason": str(first.get("reason") or "").strip() or category,
            "rows_seen": len(members),
            # Raw descriptors, so the loader can re-key them with whatever
            # the normaliser does on the day it runs.
            "descriptors": sorted({str(t.get("description") or "") for _, t in members} - {""}),
        }
        if category == "utilities" and utility_type:
            entry["utility_type"] = utility_type
        if category == "insurance" and insurance_type:
            entry["insurance_type"] = insurance_type
        if category in INCOME_TYPES:
            entry["income_type"] = category
        if not _is_global(direction, category, is_business):
            entry["source_files"] = sorted(
                {str(t.get("source_file") or "") for _, t in members} - {""}
            )
        entries.append(entry)

    return {
        "version": 1,
        "seeded_from": {
            "label": label,
            "assessment_date": summary.get("assessment_date"),
            "part2_rows": len(summary.get("part2") or []),
        },
        "entries": entries,
        "conflicts_skipped": conflicts,
        "retired_categories_skipped": retired,
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
    n_global = sum(1 for e in memory["entries"] if "source_files" not in e)
    print(
        f"{len(memory['entries'])} merchants remembered "
        f"({n_global} global, {len(memory['entries']) - n_global} pinned to their files); "
        f"{len(memory['conflicts_skipped'])} skipped as conflicting, "
        f"{len(memory['retired_categories_skipped'])} skipped for a retired category -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
