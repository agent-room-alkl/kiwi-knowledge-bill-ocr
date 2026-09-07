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
        assert "other_income" in text, path.name
        assert "salary_wages" in text, path.name
        assert "side-business gross receipts" in text, path.name
        assert "not net profit" in text, path.name
        assert "join-miss" in text, path.name
        assert "wholesale stock / COGS" in text or "wholesale stock / COGS" in text.replace("`", ""), path.name
        assert "foreign currency conversion line item" in text, path.name
        assert "transaction_id" in text, path.name


def test_xlsx_prompt_has_the_same_side_business_rules():
    text = (ROOT / "foundry" / "prompt-foundry-xlsx-now.md").read_text(encoding="utf-8")
    assert "side-business gross receipts, not net profit" in text
    assert "Never `salary_wages`" in text or "never `salary_wages`" in text
    assert "join-miss" in text
    assert "USD @ conversion rate" in text


if __name__ == "__main__":
    test_side_business_receipts_are_not_salary_or_living()
    print("ok test_side_business_receipts_are_not_salary_or_living")
    test_xlsx_prompt_has_the_same_side_business_rules()
    print("ok test_xlsx_prompt_has_the_same_side_business_rules")
    print("ALL PASS")
