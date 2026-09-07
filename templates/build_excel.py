# -*- coding: utf-8 -*-
"""Build the lender-assessment Excel template + a gold fill from the FAKE fixtures."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

OUT = Path(__file__).resolve().parent.parent / "fixtures" / "samples"
HEAD = Font(bold=True, color="FFFFFF")
FILL = PatternFill("solid", fgColor="1F4E79")
WRAP = Alignment(wrap_text=True, vertical="top")


def style_header(ws, cols):
    for i, name in enumerate(cols, 1):
        cell = ws.cell(1, i, name)
        cell.font = HEAD
        cell.fill = FILL
        ws.column_dimensions[get_column_letter(i)].width = 22


def add_sheet(wb, title, cols, rows):
    ws = wb.create_sheet(title)
    style_header(ws, cols)
    for r, row in enumerate(rows, 2):
        for c, val in enumerate(row, 1):
            ws.cell(r, c, val)
    return ws


def write(path, filled):
    wb = Workbook()
    wb.remove(wb.active)

    add_sheet(
        wb,
        "1.1 Applicant",
        ["Field", "Value"],
        [
            ["Full Name(s)", "Alex Taylor" if filled else ""],
            ["Age(s)", "Not provided in binder"],
            ["Dependants", "Not provided in binder"],
            ["Address and living situation", "12 Example Street, Wellington 6011 - Renting" if filled else ""],
            ["Assessment date", "2026-08-31"],
        ],
    )
    add_sheet(
        wb,
        "1.2 Accounts",
        ["Institution", "Account", "Type", "Period", "Days covered", "Days old", "Source"],
        [
            ["ANZ", "01-0123-0456789-00", "everyday", "2026-07-01 to 2026-07-31", 31, 31, "ANZ-everyday-FAKE-2026-07.pdf"],
            ["Westpac", "Mastercard 4567", "credit_card", "2026-06-08 to 2026-07-07", 30, 55, "Westpac-mastercard-FAKE-2026-07.pdf"],
            ["Kiwibank", "38-9012-3456789-00", "everyday", "2026-06-01 to 2026-06-30", 30, 62, "Kiwibank-everyday-FAKE-2026-06.pdf"],
            ["ASB", "Visa 2211", "credit_card", "2026-05-01 to 2026-05-31", 31, 92, "ASB-visa-FAKE-2026-05.pdf"],
        ]
        if filled
        else [],
    )
    add_sheet(
        wb,
        "1.4 Income",
        ["Source", "Type", "Amount observed", "Frequency", "Monthly equivalent", "Gross/net", "Evidence"],
        [
            ["ACME NZ LTD", "salary_wages", 4820, "fortnightly", round(4820 * 26 / 12, 2), "unknown", "ANZ + Kiwibank credits"],
            ["WINZ WFF", "benefit", 180, "monthly", 180, "unknown", "Kiwibank 15 Jun"],
        ]
        if filled
        else [],
    )
    empty_part1 = [
        ["Transport", "", ""],
        ["Utilities", "", ""],
        ["Insurance (combined)", "", ""],
        ["Food / grocery / clothing / personal care", "", ""],
        ["Recreation and entertainment", "", ""],
        ["Monthly subscriptions", "", ""],
        ["Education", "", ""],
        ["KiwiSaver and savings (NOT in recommended)", "", ""],
        ["Childcare and child support", "", ""],
        ["Donations / tithings (NOT in recommended)", "", ""],
        ["Rent / board paid", "", ""],
        ["Medical", "", ""],
        ["Extracurricular", "", ""],
        ["Other", "", ""],
        ["TOTAL RECURRING LIVING", "", ""],
        ["TOTAL SAVINGS AND GIVING", "", ""],
        ["TOTAL ONE-OFF EXCLUDED", "", ""],
        ["RECOMMENDED MONTHLY LIVING", "", ""],
    ]
    filled_part1 = [
        ["Transport", 166.72, "Gull + Z; code-computed draft"],
        ["Utilities", 266.5, "Meridian 214.50 + 2degrees 52; Watercare insufficient"],
        ["Insurance (combined)", 0, "AA annual 1200 = insufficient_observations, not /12"],
        ["Food / grocery / clothing / personal care", 592.7, "Pak N Save + Countdown + Chemist"],
        ["Recreation and entertainment", 59.3, "Uber / Uber Eats / dining"],
        ["Monthly subscriptions", 86.87, "Netflix + Spotify + Apple + City Fitness"],
        ["Education", 0, ""],
        ["KiwiSaver and savings (NOT in recommended)", 180, "Listed only"],
        ["Childcare and child support", 0, ""],
        ["Donations / tithings (NOT in recommended)", 20, "Listed only"],
        ["Rent / board paid", 2400, "June + July rent"],
        ["Medical", 66.2, "Pharmacy lines"],
        ["Extracurricular", 0, ""],
        ["Other", 0, ""],
        ["TOTAL RECURRING LIVING", 3651.29, "excludes KS, donations, one-off, debt service"],
        ["TOTAL SAVINGS AND GIVING", 200, "KS + donation"],
        ["TOTAL ONE-OFF EXCLUDED", 1489, "AA 1200 + Air NZ 289"],
        ["RECOMMENDED MONTHLY LIVING", 3651.29, "servicing figure"],
    ]
    add_sheet(
        wb,
        "Part1 Summary",
        ["Category", "Monthly equivalent", "Notes"],
        filled_part1 if filled else empty_part1,
    )
    add_sheet(
        wb,
        "Part2 Line items",
        ["Date", "Description", "Amount", "Frequency", "Include", "Category"],
        [
            ["2026-07-04", "RENT A. LANDLORD 12 EX ST", 2400, "monthly", "Y", "rent_board_paid"],
            ["2026-07-05", "Pak N Save Wairau Road", 186.4, "irregular", "Y", "food_grocery_clothing_personal_care"],
            ["2026-07-07", "NETFLIX.COM", 25.99, "monthly", "Y", "monthly_subscriptions"],
            ["2026-07-14", "KIWISAVER IRD", 180, "monthly", "N", "kiwisaver_savings_investments"],
            ["2026-07-18", "AA INSURANCE MOTOR ANNUAL", 1200, "insufficient_observations", "N", "one_off"],
            ["2026-07-31", "MORTGAGE ANZ HOME 8891", 4417.47, "monthly", "N", "mortgage_repayment"],
        ]
        if filled
        else [],
    )
    add_sheet(
        wb,
        "Part3 One-off",
        ["Date", "Description", "Amount", "Reason excluded"],
        [
            ["2026-07-18", "AA INSURANCE MOTOR ANNUAL", 1200, "insufficient_observations - annual vs one-off"],
            ["2026-05-18", "AIR NZ INTL SYDNEY", 289, "international travel"],
        ]
        if filled
        else [],
    )
    add_sheet(
        wb,
        "Part4 Liabilities",
        ["Institution", "Facility type", "Credit limit", "Current balance", "Observed repayment", "Frequency"],
        [
            ["ANZ", "home loan", None, None, 4417.47, "monthly"],
            ["Westpac", "credit card", 6000, 612.18, 200, "monthly"],
            ["ASB", "credit card", 4000, 388.4, 210, "monthly"],
            ["Afterpay", "BNPL", None, None, 64, "unknown"],
            ["Gem / Q Card", "credit card", None, None, 40, "unknown"],
        ]
        if filled
        else [],
    )
    add_sheet(
        wb,
        "Part5 Commentary",
        ["Block", "Text"],
        [
            ["Top merchants (annualised from observed months)", "PAK N SAVE; COUNTDOWN; GULL; NETFLIX"],
            ["High-frequency (>=3)", "PAK N SAVE appears 3 times across stores after normalize"],
            ["Underwriter notes", "Gold file is code-filled from FAKE fixtures. Model-typed totals are not this sheet."],
        ]
        if filled
        else [],
    )

    note = wb.create_sheet("_README")
    note["A1"] = (
        "SYNTHETIC / TEMPLATE - not a real customer file. "
        "Foundry render_report should write this workbook. "
        "GPT-5 mini chat will not produce a real xlsx unless the product supports file tools."
    )
    note.column_dimensions["A"].width = 100
    note["A1"].alignment = WRAP
    wb.save(path)
    print(path)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    write(OUT / "lender-assessment-TEMPLATE.xlsx", filled=False)
    write(OUT / "lender-assessment-GOLD-from-FAKE.xlsx", filled=True)


if __name__ == "__main__":
    main()
