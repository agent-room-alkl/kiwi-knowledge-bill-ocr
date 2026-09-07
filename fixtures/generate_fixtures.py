"""Generate labelled FAKE NZ statement PDFs. Invented person. Not bank-issued."""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "samples"
BANNER = "SYNTHETIC TEST FIXTURE — NOT A REAL BANK DOCUMENT — FAKE DATA ONLY"


def header(c, title, subtitle):
    w, h = A4
    c.setFillColorRGB(0.75, 0.1, 0.1)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(16 * mm, h - 12 * mm, BANNER)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(16 * mm, h - 22 * mm, title)
    c.setFont("Helvetica", 9)
    c.drawString(16 * mm, h - 28 * mm, subtitle)
    c.line(16 * mm, h - 30 * mm, w - 16 * mm, h - 30 * mm)


def footer(c, page="1 / 1"):
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(16 * mm, 12 * mm, BANNER)
    c.drawRightString(A4[0] - 16 * mm, 12 * mm, page)


def table(c, y, rows, col_x, fonts=None):
    for i, row in enumerate(rows):
        c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 8)
        for x, cell in zip(col_x, row):
            c.drawString(x, y, str(cell))
        y -= 12
        if y < 24 * mm:
            break
    return y


def everyday_anz():
    path = OUT / "ANZ-everyday-FAKE-2026-07.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    header(
        c,
        "ANZ (synthetic) Everyday Account Statement",
        "Account 01-0123-0456789-00   Alex Taylor   12 Example Street, Wellington 6011",
    )
    c.setFont("Helvetica", 9)
    y = A4[1] - 38 * mm
    for line in (
        "Statement period: 1 July 2026 – 31 July 2026",
        "Opening balance: $2,410.22    Closing balance: $3,186.47",
        "Applicant living situation (binder note): Renting. Age: Not provided in binder.",
    ):
        c.drawString(16 * mm, y, line)
        y -= 12
    y -= 6
    rows = [
        ("Date", "Description", "Withdrawals", "Deposits", "Balance"),
        ("01 Jul 2026", "Opening balance", "", "", "2,410.22"),
        ("02 Jul 2026", "SALARY ACME NZ LTD", "", "4,820.00", "7,230.22"),
        ("03 Jul 2026", "TFR TO VISA 4567", "500.00", "", "6,730.22"),
        ("04 Jul 2026", "RENT A. LANDLORD 12 EX ST", "2,400.00", "", "4,330.22"),
        ("05 Jul 2026", "Pak N Save Wairau Road Northshore NZL", "186.40", "", "4,143.82"),
        ("07 Jul 2026", "NETFLIX.COM", "25.99", "", "4,117.83"),
        ("08 Jul 2026", "MERIDIAN ENERGY", "214.50", "", "3,903.33"),
        ("10 Jul 2026", "Gull Albany Auckland NZL", "89.20", "", "3,814.13"),
        ("12 Jul 2026", "Pak N Save Glenfield Auckland NZL", "142.10", "", "3,672.03"),
        ("14 Jul 2026", "KIWISAVER IRD", "180.00", "", "3,492.03"),
        ("15 Jul 2026", "AFTERPAY NZ", "64.00", "", "3,428.03"),
        ("16 Jul 2026", "WATERCARE QUARTERLY", "186.00", "", "3,242.03"),
        ("18 Jul 2026", "AA INSURANCE MOTOR ANNUAL", "1,200.00", "", "2,042.03"),
        ("20 Jul 2026", "COUNTIES MEDICAL PHARMACY", "38.40", "", "2,003.63"),
        ("22 Jul 2026", "Pak N Save New Lynn Auckland NZL", "171.80", "", "1,831.83"),
        ("24 Jul 2026", "TFR FROM 01-0123-0456789-50 SAVINGS", "", "1,000.00", "2,831.83"),
        ("26 Jul 2026", "SPOTIFY", "17.99", "", "2,813.84"),
        ("28 Jul 2026", "CITY FITNESS MONTHLY", "29.90", "", "2,783.94"),
        ("30 Jul 2026", "SALARY ACME NZ LTD", "", "4,820.00", "7,603.94"),
        ("31 Jul 2026", "MORTGAGE ANZ HOME 8891", "4,417.47", "", "3,186.47"),
    ]
    cols = [16 * mm, 40 * mm, 120 * mm, 145 * mm, 170 * mm]
    table(c, y, rows, cols)
    footer(c)
    c.save()
    return path


def westpac_card():
    path = OUT / "Westpac-mastercard-FAKE-2026-07.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    header(
        c,
        "Westpac (synthetic) Mastercard Statement",
        "Card •••• 4567   Alex Taylor   Credit limit $6,000.00",
    )
    c.setFont("Helvetica", 9)
    y = A4[1] - 38 * mm
    for line in (
        "Statement period: 8 June 2026 – 7 July 2026    Payment due: 1 August 2026",
        "Opening Balance $47.24 CR    Closing balance $612.18    Minimum payment $12.00",
        "Columns follow Westpac specimen: TRANSACTION DATE | PROCESS DATE | DETAILS | AMOUNT $",
    ):
        c.drawString(16 * mm, y, line)
        y -= 12
    y -= 8
    c.setFont("Helvetica-Bold", 9)
    c.drawString(16 * mm, y, "General Payments & Charges")
    y -= 16
    rows = [
        ("Txn date", "Process date", "Details", "Amount $"),
        ("03 Sept", "04 Sept", "Opening Balance", "47.24 CR"),
        ("12 June", "13 June", "Pak N Save Wairau Road Northshore NZL", "54.20"),
        ("18 June", "19 June", "The Warehouse Glenfield Auckland NZL", "89.90"),
        ("22 June", "23 June", "Gull Albany Auckland NZL", "71.40"),
        ("28 June", "29 June", "COUN COUNTDOWN NEWMARKET NZL", "63.15"),
        ("01 July", "02 July", "UBER *TRIP AUCKLAND", "24.80"),
        ("03 July", "04 July", "Interest Purchases", "6.30"),
        ("03 July", "04 July", "Interest Brought Forward", "23.40"),
        ("05 July", "06 July", "PAYMENT THANK YOU", "200.00 CR"),
        ("06 July", "07 July", "Q CARD GEM VISA NZ", "40.00"),
        ("07 July", "07 July", "Closing Balance", "612.18"),
    ]
    cols = [16 * mm, 40 * mm, 70 * mm, 165 * mm]
    table(c, y, rows, cols)
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(16 * mm, 28 * mm, "Dates without year: infer from statement period. CR = credit.")
    footer(c)
    c.save()
    return path


def kiwibank_everyday():
    path = OUT / "Kiwibank-everyday-FAKE-2026-06.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    header(
        c,
        "Kiwibank (synthetic) Everyday Statement",
        "Account 38-9012-3456789-00   Alex Taylor   Statement vault sample",
    )
    c.setFont("Helvetica", 9)
    y = A4[1] - 38 * mm
    for line in (
        "Statement period: 1 June 2026 – 30 June 2026",
        "Opening $1,102.00   Closing $1,548.10   Running balance on the right (Kiwibank field guide).",
    ):
        c.drawString(16 * mm, y, line)
        y -= 12
    y -= 8
    rows = [
        ("Date", "Details", "Withdrawals", "Deposits", "Balance"),
        ("01 Jun 2026", "Opening balance", "", "", "1,102.00"),
        ("03 Jun 2026", "SALARY ACME NZ LTD", "", "4,820.00", "5,922.00"),
        ("04 Jun 2026", "RENT A. LANDLORD 12 EX ST", "2,400.00", "", "3,522.00"),
        ("06 Jun 2026", "POSREJ COUNTDOWN KARORI", "", "", "3,522.00"),
        ("06 Jun 2026", "COUNTDOWN KARORI", "92.40", "", "3,429.60"),
        ("09 Jun 2026", "CH suc ORANGE 4G", "52.00", "", "3,377.60"),
        ("11 Jun 2026", "NETFLIX.COM", "25.99", "", "3,351.61"),
        ("15 Jun 2026", "WINZ WFF CREDIT", "", "180.00", "3,531.61"),
        ("18 Jun 2026", "UNARRANGED O/D FEE", "5.00", "", "3,526.61"),
        ("20 Jun 2026", "TFR TO 38-9012-3456789-02", "2,000.00", "", "1,526.61"),
        ("24 Jun 2026", "DONATION RED CROSS", "20.00", "", "1,506.61"),
        ("28 Jun 2026", "SALARY ACME NZ LTD", "", "4,820.00", "6,326.61"),
        ("30 Jun 2026", "RENT A. LANDLORD 12 EX ST", "2,400.00", "", "3,926.61"),
        ("30 Jun 2026", "Closing (adjusted demo)", "", "", "1,548.10"),
    ]
    cols = [16 * mm, 40 * mm, 120 * mm, 145 * mm, 170 * mm]
    table(c, y, rows, cols)
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(16 * mm, 28 * mm, "POSREJ = declined in-store; balance unchanged (Kiwibank help).")
    footer(c)
    c.save()
    return path


def asb_visa():
    path = OUT / "ASB-visa-FAKE-2026-05.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    header(
        c,
        "ASB (synthetic) Visa Statement",
        "Card •••• 2211   Alex Taylor   Limit $4,000.00",
    )
    c.setFont("Helvetica", 9)
    y = A4[1] - 38 * mm
    for line in (
        "Statement period: 1 May 2026 – 31 May 2026    Due: 25 June 2026",
        "Opening $210.00    Purchases $388.40    Payments $210.00    Interest $0.00    Closing $388.40",
    ):
        c.drawString(16 * mm, y, line)
        y -= 12
    y -= 8
    rows = [
        ("Date", "Description", "Amount"),
        ("02 May 2026", "PAYMENT FROM ASB 12-3456-7890123-00", "-210.00"),
        ("05 May 2026", "UBER EATS AUCKLAND", "34.50"),
        ("08 May 2026", "APPLE.COM/BILL", "12.99"),
        ("12 May 2026", "CHEMIST WAREHOUSE NEWMARKET", "27.80"),
        ("18 May 2026", "AIR NZ INTL SYDNEY  (one-off travel)", "289.00"),
        ("22 May 2026", "SPOTIFY", "17.99"),
        ("28 May 2026", "Z ENERGY THORNDON", "6.12"),
    ]
    cols = [16 * mm, 40 * mm, 165 * mm]
    table(c, y, rows, cols)
    footer(c)
    c.save()
    return path


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = [everyday_anz(), westpac_card(), kiwibank_everyday(), asb_visa()]
    for p in paths:
        print(p, p.stat().st_size)


if __name__ == "__main__":
    main()
