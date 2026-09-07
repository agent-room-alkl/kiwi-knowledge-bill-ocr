# -*- coding: utf-8 -*-
"""Contract tests for Foundry classification instructions (T-06)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = [
    ROOT / "foundry" / "agent-instructions.md",
    ROOT / "foundry" / "prompt-foundry-v2.md",
    ROOT / "foundry" / "PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt",
]


def test_side_business_receipts_are_not_salary_or_living():
    for path in PROMPTS:
        text = path.read_text(encoding="utf-8")
        assert "salary_wages" in text, path.name
        assert "side-business gross receipts" in text, path.name
        assert "business_receipts" in text, path.name
        assert "Never `unclear`" in text or "Never `unclear`" in text.replace("**", ""), path.name
        assert "not net profit" in text, path.name
        assert "`other_income`" in text and "Never" in text, path.name
        assert "Part 1.4" in text, path.name
        assert "join-miss" in text, path.name
        assert "wholesale stock / COGS" in text or "wholesale stock / COGS" in text.replace("`", ""), path.name
        assert "foreign currency conversion line item" in text, path.name
        assert "transaction_id" in text, path.name
        # Mapping must not send bun/egg inflows into INCOME.
        # The mapping moved off `unclear` deliberately: see
        # test_business_receipts_are_their_own_category_not_unclear.
        assert "category `business_receipts`" in text or "Classify: `business_receipts`" in text, path.name


def test_xlsx_prompt_has_the_same_side_business_rules():
    text = (ROOT / "foundry" / "prompt-foundry-xlsx-now.md").read_text(encoding="utf-8")
    assert "side-business gross receipts, not net profit" in text
    assert "Never `salary_wages`" in text or "never `salary_wages`" in text
    assert "`business_receipts`" in text
    assert "Never `unclear`" in text
    assert "`other_income`" in text
    assert "Part 1.4 Income" in text
    assert "join-miss" in text
    assert "USD @ conversion rate" in text


def test_selfcheck_ignores_side_business_turnover_when_judging_empty_income():
    """C8 must not pass on turnover alone.

    The engine reports side-business receipts as an income row so an
    underwriter can see them. If C8 keeps reading "income is non-empty", a
    binder whose salary never got classified sails through on bun money.
    """
    for name in ("PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt", "prompt-foundry-v2.md"):
        text = (ROOT / "foundry" / name).read_text(encoding="utf-8")
        assert "side_business_gross_not_assessable" in text, name
        assert "audit.assessable_income_monthly" in text, name
        assert "turnover alone" in text, name


def test_c9_reads_join_misses_not_the_length_of_the_classifications_array():
    """The old C9 failed every correct run.

    Merchant-level classification is what the same file asks for two pages
    earlier, so the classifications array is shorter than the transaction
    list by design. C9 has to count rows that resolved to nothing.
    """
    for name in ("PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt", "prompt-foundry-v2.md"):
        text = (ROOT / "foundry" / name).read_text(encoding="utf-8")
        assert "audit.join_miss_rows" in text, name
        assert "classification count ≠ canonical transaction count" not in text, name
        assert "one merchant entry covers every row" in text, name


def test_c9_warns_and_still_renders_instead_of_blocking():
    """A file with unclassified rows still gets a workbook.

    Three runs in a row ended with a list of merchants and no workbook, and
    the third exhausted the agent's context window resending the whole
    classification set. Unclassified rows are already reported - unclear with
    a reason, counted in audit.join_miss_rows, split out in Part 5 - so the
    underwriter is better served by the workbook plus the count than by
    nothing at all. One repair pass, then render.
    """
    for name in ("PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt", "prompt-foundry-v2.md"):
        text = (ROOT / "foundry" / name).read_text(encoding="utf-8")
        assert "C8 is repairable" in text, name
        assert "C9 does not stop the render" in text, name
        assert "render" in text and "anyway" in text, name
        assert "Never" in text and "treat C9 as SELFCHECK_FAILED" in text, name
        assert "exhausts your context window" in text, name


def test_repair_passes_send_only_the_new_entries():
    """The retry loop must not resend the whole classification set.

    That is what exhausted the agent's context window on a 238-merchant
    binder. The server now accumulates per batch, so a repair pass carries
    only what it just decided.
    """
    for name in ("PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt", "prompt-foundry-v2.md"):
        text = (ROOT / "foundry" / name).read_text(encoding="utf-8")
        assert "merge_classifications" in text, name
        assert "only the entries you just" in text, name
        assert "exhausts your context window" in text, name

    import json
    spec = json.loads((ROOT / "foundry" / "openapi-servicing.json").read_text(encoding="utf-8"))
    props = spec["paths"]["/compute_summary"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert props["merge_classifications"]["type"] == "boolean"
    assert "Requires batch_id" in props["merge_classifications"]["description"]


if __name__ == "__main__":
    test_side_business_receipts_are_not_salary_or_living()
    print("ok test_side_business_receipts_are_not_salary_or_living")
    test_xlsx_prompt_has_the_same_side_business_rules()
    print("ok test_xlsx_prompt_has_the_same_side_business_rules")
    test_selfcheck_ignores_side_business_turnover_when_judging_empty_income()
    print("ok test_selfcheck_ignores_side_business_turnover_when_judging_empty_income")
    test_c9_reads_join_misses_not_the_length_of_the_classifications_array()
    print("ok test_c9_reads_join_misses_not_the_length_of_the_classifications_array")
    test_c9_warns_and_still_renders_instead_of_blocking()
    print("ok test_c9_warns_and_still_renders_instead_of_blocking")
    test_repair_passes_send_only_the_new_entries()
    print("ok test_repair_passes_send_only_the_new_entries")
    print("ALL PASS")
