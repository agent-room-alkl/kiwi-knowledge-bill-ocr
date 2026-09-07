"""Extract + normalize NZ bank / credit-card statements into canonical rows.

Two layers, deliberately separated:

  analyze_layout()  - the only function that talks to Azure Document
                      Intelligence. Needs credentials. Not unit-tested.
  normalize()       - pure. Takes the neutral `Layout` dict produced by the
                      adapter and returns a batch validating against
                      schemas/canonical-transaction.schema.json. Fully testable
                      offline; see pipeline/test_extract_normalize.py.

Rules implemented here come from pipeline/extract-normalize.md. The important
ones, because each has already shipped as a bug at least once:

  * `amount` is always positive. The sign lives in `direction`.
  * A declined line (POSREJ etc.) is `direction="info"`, `amount=0`. The only
    number printed on such a row is the *unchanged running balance*, and
    reading it as spend is how a $3,522 grocery shop that never happened got
    into a lender report.
  * Opening / closing / brought forward rows are `direction="info"`, never
    transactions.
  * `balance` is its own field and is never merged into `amount`. Downstream
    QC compares the two to detect a misread balance column; merging them
    silently disables that check.
  * A date printed without a year (`03 Sept`) takes its year from the
    statement period, incrementing across a December -> January boundary.
  * Credit cards run opposite to a cash account: a purchase is an outflow, a
    payment or a `CR`-suffixed line is an inflow.

Nothing here invents a row. If a file cannot be read, it is reported as a
rejected account with a reason and contributes no transactions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable

# --------------------------------------------------------------------------
# Neutral layout shape (what the DI adapter produces and normalize() consumes)
#
#   {
#     "source_file": "ANZ-....pdf",
#     "lines": ["SYNTHETIC ...", "Statement period: 1 July 2026 - 31 July 2026", ...],
#     "tables": [ {"page_number": 1, "rows": [["Date","Description",...], [...]]} ],
#   }
# --------------------------------------------------------------------------

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

DECLINED_MARKERS = (
    "POSREJ", "DECLINED", "REVERSED", "REVERSAL", "NSF", "UNPAID",
    "DISHONOUR", "DISHONOURED", "INSUFFICIENT", "UNABLE TO PROCESS",
    "PAYMENT STOPPED",
)

# Matched as a substring: `Interest Brought Forward` is a balance-carrying line,
# not 23.40 of interest spent this period.
CARRIED_MARKERS = (
    "BROUGHT FORWARD", "CARRIED FORWARD", "BALANCE B/F", "BALANCE C/F",
    "BALANCE BROUGHT", "BALANCE CARRIED", "B/FWD", "C/FWD",
)

# Matched only at the start of the description, so a real merchant such as
# `TOTAL TOOLS` or `SUBWAY` is not mistaken for a summary row.
LEADING_NON_TRANSACTION = (
    "OPENING BALANCE", "CLOSING BALANCE", "TOTAL", "SUBTOTAL", "CONTINUED",
)

# Date cells that are clearly ledger chrome, not a posted day. Real NZ
# statements split `Totals at end of page` across the date/description
# columns; treating that as an unreadable posting date rejects the file.
_NON_DATE_LABELS = (
    "TOTAL", "PAGE", "BALANCE", "BROUGHT", "CARRIED", "OPENING", "CLOSING",
    "PERIOD", "DESCRIPTION",
)

# A card payment reduces debt. `PAYMENT FROM ASB ...`, `PAYMENT THANK YOU`,
# `DIRECT DEBIT PAYMENT`, a refund, or a reversal are all inflows on a card.
_CARD_PAYMENT_RE = re.compile(r"\bPAYMENT\b|\bREFUND\b|\bCREDIT VOUCHER\b|\bREBATE\b")
# ... but never the statement's own instruction lines.
_CARD_PAYMENT_EXCLUDE_RE = re.compile(r"MINIMUM PAYMENT|PAYMENT DUE|PAYMENT STOPPED")

_MONEY = re.compile(r"-?\$?\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?|-?\$?\s*\d+\.\d{2}")
_TRAILING_JUNK = re.compile(r"\s+(?:NZL|NZ)\b|\s+\d{2,}$")


class ExtractionError(RuntimeError):
    """Raised when a file cannot be read. Never swallowed into empty rows."""


# --------------------------------------------------------------------------
# Small pure helpers
# --------------------------------------------------------------------------


def parse_money(text: Any) -> float | None:
    """Return the numeric value of a money cell, or None if there is none.

    Rejects the mangled forms a broken text layer produces (`4,.00`, `$6,.00`)
    rather than silently reading them as 4 and 6 — a truncated amount is a
    wrong amount, not a small one.
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    if "(cid:" in s or re.search(r",\s*\.", s):
        raise ExtractionError(f"mangled numeric text {s!r}: digits lost in the text layer")
    negative = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("()")
    m = _MONEY.search(s)
    if not m:
        return None
    value = float(m.group(0).replace("$", "").replace(",", "").replace(" ", "").lstrip("-"))
    return -value if negative else value


_RANGE_WORDS = re.compile(
    r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{2,4})\s*[-–—to]+\s*(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{2,4})",
    re.I,
)
_RANGE_NUMERIC = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s*[-–—to]+\s*(\d{1,2})/(\d{1,2})/(\d{2,4})"
)


def _full_year(year: int) -> int:
    """`26` on a 2026 statement is 2026, not year 26."""
    if year < 100:
        return 2000 + year if year < 70 else 1900 + year
    return year


def _period_from_text(text: str) -> tuple[date | None, date | None]:
    m = _RANGE_WORDS.search(text)
    if m:
        d1, m1, y1, d2, m2, y2 = m.groups()
        start = _mk_date(int(d1), m1, _full_year(int(y1)))
        end = _mk_date(int(d2), m2, _full_year(int(y2)))
        if start and end:
            return start, end
    m = _RANGE_NUMERIC.search(text)
    if m:
        d1, mo1, y1, d2, mo2, y2 = m.groups()
        try:
            start = date(_full_year(int(y1)), int(mo1), int(d1))
            end = date(_full_year(int(y2)), int(mo2), int(d2))
        except ValueError:
            return None, None
        return start, end
    return None, None


def parse_period(lines: Iterable[str]) -> tuple[date | None, date | None]:
    """Find the printed statement window.

    Real NZ banks often split the label and the dates across two lines:

        Statement period
        20 Jun 2026 - 19 Aug 2026

    The fixture form (`Statement period: 1 July 2026 - 31 July 2026` on one
    line) still matches. The year is never taken from `assessment_date`.
    """
    rows = [str(line or "") for line in lines]
    for i, line in enumerate(rows):
        if "period" not in line.lower():
            continue
        start, end = _period_from_text(line)
        if start and end:
            return start, end
        for nxt in rows[i + 1 : i + 3]:
            start, end = _period_from_text(nxt)
            if start and end:
                return start, end
    # Masthead-only fallback: a bare `20 May 2026 to 19 August 2026` with no
    # "period" word. Do not scan the ledger — yearless txn rows would match.
    for line in rows[:80]:
        if "period" in line.lower():
            continue
        start, end = _period_from_text(line)
        if start and end:
            return start, end
    return None, None


def _mk_date(day: int, month_text: str, year: int) -> date | None:
    month = MONTHS.get(month_text.strip().lower()[:4]) or MONTHS.get(month_text.strip().lower()[:3])
    if not month:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def resolve_date(
    cell: Any,
    period_start: date | None,
    period_end: date | None,
) -> date | None:
    """Parse a statement date cell, supplying a missing year from the period.

    `03 Sept` inside a period of 8 June 2026 - 7 July 2026 is ambiguous on its
    face; the year comes from the period, and a December -> January period
    rolls the year forward.
    """
    if cell is None:
        return None
    s = str(cell).strip()
    if not s:
        return None

    m = re.match(r"(\d{1,2})[\s/-]+([A-Za-z]{3,9})[\s/-]+(\d{4})", s)
    if m:
        return _mk_date(int(m.group(1)), m.group(2), int(m.group(3)))

    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    # Yearless: "03 Sept", "03 Sep"
    m = re.match(r"(\d{1,2})\s+([A-Za-z]{3,9})\b", s)
    if not m:
        return None
    day, month_text = int(m.group(1)), m.group(2)
    if period_start is None or period_end is None:
        return None

    month = MONTHS.get(month_text.lower()[:4]) or MONTHS.get(month_text.lower()[:3])
    if not month:
        return None

    for year in {period_start.year, period_end.year}:
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        # Allow a little slack: a card statement can post a few days either side.
        if period_start - timedelta(days=31) <= candidate <= period_end + timedelta(days=31):
            return candidate
    # Period crosses Dec -> Jan and the row is in January.
    if period_start.year != period_end.year and month <= 6:
        try:
            return date(period_end.year, month, day)
        except ValueError:
            return None
    # Outside the period in every candidate year. Do not invent a date.
    return None


# Card lines carry the bank's own furniture, not the merchant's name:
#   `FU MARKET 483561 ****** 7996 Orig date 27/06/2026`
# Left in, the masked PAN and `Orig date` become part of the merchant key, so
# `FU MARKET ****** ORIG DATE / /` is what downstream sees. That is ugly in
# Part 2 and it splits one shop into several keys - `DIDI_NZ` and
# `DIDI_NZ DIDINZ PENDING` were the same taxi company counted twice.
_CARD_PAN_RE = re.compile(r"\b\d{4,6}\s*\*{2,}\s*\d{2,4}\b")
_ORIG_DATE_RE = re.compile(r"\bORIG(?:INAL)?\s+DATE\b.*$")
# `pending` sits mid-line on Kiwibank card rows ("DIDI_NZ DidiNZ pending
# Auckland"), so anchoring this to the end would miss it.
_STATUS_WORD_RE = re.compile(r"\b(?:PENDING|APPROVED|DECLINED|COMPLETED)\b")
# A lone trailing C or D is the card-present / debit indicator, not a name.
_TRAILING_INDICATOR_RE = re.compile(r"\s+[CD]\s*$")
_BANK_PREFIX_RE = re.compile(
    r"^(?:(?:POS\s*W/?D|DIRECT\s+DEBIT|DIRECT\s+CREDIT|BILL\s+PAYMENT)(?:\s*-?\s+|\s*-)|PAY\s+)",
    re.I,
)
# After a prefix is removed, `Direct Debit -PARTNERS LIFE` must not become
# `-PARTNERS LIFE`. Only leading punct — never a hyphen mid-name.
_LEADING_PUNCT_RE = re.compile(r"^[\s\-_:./]+")
# Descriptor-drift collapse only. These keys never decide is_business —
# that judgement lives on the classification field.
_MERCHANT_ALIASES = (
    (re.compile(r"ANTHROPIC|CLAUDE\.?AI|CLAUDE SUB"), "ANTHROPIC / CLAUDE"),
    (re.compile(r"AGENT-?ROOM"), "AGENT-ROOM.COM"),
    (re.compile(r"GILMOURS"), "GILMOURS"),
    (re.compile(r"\bDIDI"), "DIDI_NZ"),
    (re.compile(r"WOOLWORTHS|COUNTDOWN"), "WOOLWORTHS"),
    (re.compile(r"CURSOR"), "CURSOR.COM"),
    (re.compile(r"GODADDY"), "GODADDY"),
    (re.compile(r"GOOGLE ADS?\b|GOOGLE ADS\d+"), "GOOGLE ADS"),
    (re.compile(r"GOOGLE ONE"), "GOOGLE ONE"),
    (re.compile(r"IWG NEW ZEALAND|\bIWG\b"), "IWG NEW ZEALAND"),
)


def descriptor_core(description: str) -> str:
    """Bank prefix/suffix stripped. Used to spot the same charge extracted twice."""
    s = str(description or "").upper().strip()
    s = _BANK_PREFIX_RE.sub("", s)
    s = _LEADING_PUNCT_RE.sub("", s)
    s = re.sub(r"\b(?:NZL|AUS|SG|NL|NZ|CAUS)\s*$", "", s).strip()
    return re.sub(r"\s+", " ", s)


def collapse_merchant(key: str, description: str = "") -> str:
    """Collapse known descriptor-drift variants onto one stream key."""
    cleaned = _BANK_PREFIX_RE.sub("", (key or "").upper().strip())
    cleaned = _LEADING_PUNCT_RE.sub("", cleaned)
    cleaned = re.sub(r"\b(?:NZL|AUS|SG|NL|NZ|CAUS)\s*$", "", cleaned).strip()
    blob = f"{cleaned} {description}".upper()
    for pat, canon in _MERCHANT_ALIASES:
        if pat.search(blob):
            return canon
    return cleaned


def normalize_merchant(description: str) -> str:
    """`Pak N Save Wairau Road Northshore NZL` -> `PAK N SAVE`."""
    s = str(description or "").upper()
    s = _BANK_PREFIX_RE.sub("", s)
    s = _LEADING_PUNCT_RE.sub("", s)
    # Bank furniture first, before the digit rules below turn a masked PAN into
    # a row of orphaned asterisks that no later rule can recognise.
    s = _CARD_PAN_RE.sub(" ", s)
    s = _ORIG_DATE_RE.sub(" ", s)
    s = _STATUS_WORD_RE.sub(" ", s)
    s = re.sub(r"\*{2,}", " ", s)                  # leftover masking runs
    s = re.sub(r"\bNZL\b|\bAUS\b|\bSG\b|\bNL\b|\bNZ\b$", " ", s)
    s = re.sub(r"[\d,]+\.\d{2}", " ", s)          # stray amounts
    s = re.sub(r"\b\d{2,}\b", " ", s)              # store / card numbers
    s = re.sub(
        r"\b(WAIRAU|GLENFIELD|NORTHSHORE|ALBANY|NEWMARKET|NEW LYNN|KARORI|"
        r"AUCKLAND|WELLINGTON|CHRISTCHURCH|THORNDON|ROAD|RD|STREET|ST)\b",
        " ",
        s,
    )
    s = re.sub(r"\s+", " ", s).strip()
    s = _TRAILING_INDICATOR_RE.sub("", s).strip()
    for pat, canon in _MERCHANT_ALIASES:
        if pat.search(s) or pat.search(str(description or "").upper()):
            return canon
    return s


def is_declined(description: str) -> bool:
    up = str(description or "").upper()
    return any(marker in up for marker in DECLINED_MARKERS)


def is_non_transaction(description: str) -> bool:
    """Balance-carrying and summary lines, which move no money."""
    up = str(description or "").upper().strip()
    if any(marker in up for marker in CARRIED_MARKERS):
        return True
    if "OF PAGE" in up or "END OF PAGE" in up:
        return True
    return any(up.startswith(m) or up == m for m in LEADING_NON_TRANSACTION)


def _is_non_date_label(text: str) -> bool:
    """True when a date column holds ledger chrome, not a calendar day."""
    up = str(text or "").upper().strip()
    if not up:
        return False
    if not any(label in up for label in _NON_DATE_LABELS):
        return False
    # `22 Jun` / `03 Sept` always have a day numeral. `Totals at end` does not.
    return not re.search(r"\d", up)


# Only the statement masthead decides the account type. Transaction
# descriptions must never vote: an everyday account containing
# `TFR TO VISA 4567` is a cash account paying off a card, not a card.
# The masthead ends where the transaction table begins, so that is the
# boundary we use — not an arbitrary line count.
_COLUMN_HEADER_WORDS = {
    "date", "dates", "description", "descriptions", "details", "particulars",
    "withdrawal", "withdrawals", "deposit", "deposits", "debit", "debits",
    "credit", "credits", "balance", "amount", "amount $", "transaction",
    "txn date", "process date", "posting date", "narrative", "reference",
}


def masthead(lines: Iterable[str]) -> list[str]:
    """The lines above the transaction table.

    Document Intelligence emits each table header cell as its own line, so the
    first bare `Date` / `Description` / `Withdrawals` line marks where the
    statement's own text stops and the ledger starts.
    """
    head: list[str] = []
    for line in lines:
        text = str(line or "")
        flat = re.sub(r"[\s:]+", " ", text).strip().lower()
        if flat in _COLUMN_HEADER_WORDS:
            break
        # Second boundary, for statements whose header cells are not emitted as
        # their own lines: a line that opens with a posting date is a ledger row.
        if re.match(r"\s*\d{1,2}[\s/-]+(?:[A-Za-z]{3,9}|\d{1,2})\b", text):
            break
        head.append(text)
    return head


def detect_account_type(lines: Iterable[str]) -> str:
    header = " ".join(masthead(lines)).upper()
    if any(k in header for k in ("MASTERCARD", "VISA", "CREDIT CARD", "AMEX", "CREDIT LIMIT")):
        return "credit_card"
    if any(k in header for k in ("EVERYDAY", "TRANSACTION ACCOUNT", "CHEQUE")):
        return "everyday"
    if "SAVINGS" in header:
        return "savings"
    return "other"


def detect_institution(lines: Iterable[str]) -> str:
    blob = " ".join(lines).upper()
    for name in ("ANZ", "ASB", "WESTPAC", "BNZ", "KIWIBANK", "TSB", "CO-OPERATIVE", "HEARTLAND"):
        if re.search(rf"\b{re.escape(name)}\b", blob):
            return name.title() if name not in ("ANZ", "ASB", "BNZ", "TSB") else name
    return "Not provided in binder"


def _account_number(lines: Iterable[str]) -> str | None:
    for line in lines:
        m = re.search(r"\b\d{2}-\d{4}-\d{7}-\d{2}\b", line)
        if m:
            return m.group(0)
    return None


def _account_label(lines: Iterable[str], account_type: str) -> str:
    """Return a customer-facing identifier printed on the statement."""
    material = list(masthead(lines))
    number = _account_number(material)
    if number:
        return number
    for line in material:
        if account_type == "credit_card":
            match = re.search(r"\b(?:CARD|VISA|MASTERCARD)\D{0,12}(\d{4})\b", line, re.I)
            if match:
                return f"Card ending {match.group(1)}"
        match = re.search(r"\b(?:ACCOUNT|A/C)\s*(?:NO\.?\s*)?([*Xx\d -]{4,})\b", line, re.I)
        if match and re.search(r"\d", match.group(1)):
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return "Not provided in binder"


def _labelled_field(line: str, label: str) -> str | None:
    match = re.search(rf"\b{label}\s*:\s*(.+)$", line, re.I)
    if not match:
        return None
    value = match.group(1).strip().rstrip(".")
    if not value or re.search(r"not provided in binder", value, re.I):
        return None
    return value


_NAME_STOPWORDS = re.compile(
    r"STATEMENT|ACCOUNT|BANK|VISA|MASTERCARD|EVERYDAY|SAVINGS|"
    r"PROCESS|DATE|DESCRIPTION|DETAILS|PARTICULARS|OPENING|CLOSING|"
    r"BALANCE|CREDIT|LIMIT|PAYMENT|TRANSACTION|AMOUNT|WITHDRAWAL|DEPOSIT|"
    r"SYNTHETIC|FIXTURE|SAMPLE|TEST|FAKE|DEMO|SPECIMEN|WATERMARK",
    re.I,
)

# Postal and corporate words. Without these, `Laurina Road`, `Private Bag` and
# `Po Box` all satisfied "two capitalised words" and one of them was printed in
# the applicant's legal-name field on a lending assessment. A wrong name is
# worse than a missing one: `Not provided in binder` tells an underwriter to go
# and look, while `LAURINA ROAD; Private Bag` invites them to believe it.
_NOT_A_PERSON = re.compile(
    r"\b(?:ROAD|RD|STREET|ST|AVENUE|AVE|LANE|LN|DRIVE|DRV|CRESCENT|CRES|"
    r"PLACE|TERRACE|HIGHWAY|HWY|PARADE|QUAY|COURT|CLOSE|WAY|"
    r"PRIVATE|BAG|BOX|PO|POBOX|POSTAL|CENTRE|CENTER|BRANCH|CITY|SUBURB|"
    r"LIMITED|LTD|COMPANY|TRUST|HOLDINGS|GROUP|SERVICES|PTY|INC|NZ|NEW ZEALAND|"
    r"ACCESS|NUMBER|CARD|HOLDER|CUSTOMER|REFERENCE|CODE|PAGE|SUMMARY|PERIOD|"
    r"TELLER|BANKING|INTERNET|MOBILE|ONLINE|TOTAL|CONTACT|PHONE|EMAIL|WEBSITE|"
    r"ENQUIRIES|HELPLINE|FREEPHONE|INTEREST|FEES|CHARGES|"
    r"PRODUCT|NAME|TYPE|STATUS|DETAIL|OPENED|ISSUED|EXPIRY|DUE|MINIMUM|"
    r"AVAILABLE|CURRENT|PREVIOUS|CLOSING|OVERDRAFT|FACILITY)\b",
    re.I,
)


_TITLES = frozenset({"MR", "MRS", "MS", "MISS", "DR", "PROF"})

# `MR A TAYLOR` is how a bank addresses an envelope: a title, an initial, a
# surname. Requiring every word to be two letters or more rejected exactly the
# line that carries the real name, which is why the extractor went looking for
# one in the address underneath it.
_PERSON_RE = re.compile(
    r"(?:(?:MR|MRS|MS|MISS|DR|PROF)\.?\s+)?"
    r"[A-Z][A-Za-z'’-]*(?:\s+[A-Z][A-Za-z'’-]*){1,3}",
    re.I,
)


def _looks_like_person_name(piece: str) -> bool:
    piece = piece.strip()
    if not _PERSON_RE.fullmatch(piece):
        return False
    if _NAME_STOPWORDS.search(piece) or _NOT_A_PERSON.search(piece):
        return False
    # At least one word of real length. `A B` is an abbreviation, not a name.
    words = [w for w in re.split(r"\s+", piece) if w.upper().rstrip(".") not in _TITLES]
    return any(len(w) >= 2 for w in words) and len(words) >= 2


def _living_situation(line: str) -> str | None:
    if re.search(r"\brenting\b", line, re.I):
        return "Renting"
    if re.search(r"\bboarding\b", line, re.I):
        return "Boarding"
    if re.search(r"\bhomeowner\b|\bowner[- ]occupier\b", line, re.I):
        return "Homeowner"
    return None


def _applicant_evidence(lines: Iterable[str]) -> dict[str, str]:
    """Extract only high-confidence holder/address text printed on the statement.

    Never infer age from a date of birth, or dependants from spending. A field
    that is not printed stays `Not provided in binder`.
    """
    material = [str(x) for x in lines]
    # Do not use masthead() here: a `Process Date` column header would cut the
    # window off before the printed holder name. Stop only at a ledger date row.
    header_lines: list[str] = []
    for line in material:
        if re.match(r"\s*\d{1,2}[\s/-]+(?:[A-Za-z]{3,9}|\d{1,2})\b", line):
            break
        header_lines.append(line)
    full_name = "Not provided in binder"
    address = "Not provided in binder"
    age = "Not provided in binder"
    dependants = "Not provided in binder"
    living = "Not provided in binder"
    street_re = re.compile(
        r"\b\d{1,5}\s+[A-Za-z][A-Za-z .'-]*?\b(?:STREET|ST|ROAD|RD|AVENUE|AVE|LANE|LN|DRIVE|DR|CRESCENT|CRES)\b"
        r"(?:,\s*[A-Za-z][A-Za-z ]+\s+\d{4})?",
        re.I,
    )
    # The addressee block is the most reliable place a holder name appears: a
    # bank prints it directly above the postal address. Prefer it over anything
    # mined from elsewhere in the masthead, where form labels live and where
    # "Access Number" once got printed as the applicant's legal name.
    for i, line in enumerate(header_lines):
        if not street_re.search(line) and not re.search(r"\bPRIVATE BAG\b|\bPO BOX\b", line, re.I):
            continue
        for back in (1, 2):
            if i - back < 0:
                break
            candidate = header_lines[i - back].strip()
            if _looks_like_person_name(candidate):
                full_name = candidate
                break
        if full_name != "Not provided in binder":
            break

    for line in header_lines:
        pieces = [p.strip() for p in re.split(r"\s{2,}|\s+\|\s+", line) if p.strip()]
        if len(pieces) == 1:
            pieces = [line.strip(), *pieces]
        for piece in pieces:
            street = street_re.search(piece)
            if street:
                address = street.group(0)
            # Cut the address out of the piece before looking for a name.
            # Skipping the whole piece is wrong: DI often emits account, holder
            # and address as one unsplit line, and dropping it loses the name.
            # Leaving the address in is also wrong - that is how `12 Laurina
            # Road` produced "Laurina Road" as the account holder.
            if street:
                piece = piece.replace(street.group(0), " ").strip()
            if full_name == "Not provided in binder":
                if _looks_like_person_name(piece):
                    full_name = piece
                else:
                    for match in re.finditer(
                        r"\b([A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){1,3})\b",
                        piece,
                    ):
                        if _looks_like_person_name(match.group(1)):
                            full_name = match.group(1)
                            break
    for line in material:
        labelled_age = _labelled_field(line, "Age(?:s)?")
        if labelled_age:
            age = labelled_age
        labelled_dependants = _labelled_field(line, "Dependants?")
        if labelled_dependants:
            dependants = labelled_dependants
        if re.search(r"living situation|renting|boarding|homeowner", line, re.I):
            found = _living_situation(line)
            if found:
                living = found
    address_out = address
    if living != "Not provided in binder":
        address_out = f"{address} ({living})" if address != "Not provided in binder" else living
    return {
        "Full Name(s)": full_name,
        "Age(s)": age,
        "Dependants": dependants,
        "Address and living situation": address_out,
    }


def _conduct_assessment(
    lines: Iterable[str], transactions: list[dict[str, Any]], account_type: str,
    credit_limit: float | None,
) -> dict[str, Any]:
    """Produce explicit, evidence-based conduct checks for one statement."""
    material = " ".join(str(x) for x in lines).upper()
    posted = [t for t in transactions if t.get("direction") != "info"]
    negative_balances = [t for t in posted if isinstance(t.get("balance"), (int, float)) and t["balance"] < 0]
    fee_markers = (
        "LATE PAYMENT", "DISHONOUR", "DISHONOURED", "UNARRANGED OVERDRAFT",
        "OVERDRAFT FEE", "UNPAID FEE",
    )
    fee_rows = [t for t in posted if any(m in str(t.get("description", "")).upper() for m in fee_markers)]
    declined_rows = [t for t in transactions if is_declined(str(t.get("description", "")))]
    balance_values = [abs(float(t["balance"])) for t in posted if isinstance(t.get("balance"), (int, float))]
    limit_excess = bool(account_type == "credit_card" and credit_limit and balance_values and max(balance_values) > credit_limit)
    arrears_text = bool(re.search(r"\b(?:ARREARS|PAST DUE|OVERDUE)\b", material))
    return {
        "arrears_or_overdrawn": {
            "identified": bool(arrears_text or negative_balances),
            "count": len(negative_balances) + int(arrears_text),
            "evidence": [t.get("raw_anchor") for t in negative_balances][:10],
        },
        "late_dishonour_unarranged_fees": {
            "identified": bool(fee_rows),
            "count": len(fee_rows),
            "evidence": [t.get("raw_anchor") for t in fee_rows][:10],
        },
        "limit_excess": {
            "identified": limit_excess,
            "count": int(limit_excess),
            "evidence": [f"observed balance exceeds credit limit {credit_limit:.2f}"] if limit_excess else [],
        },
        "irregular_activity": {
            "identified": bool(declined_rows),
            "count": len(declined_rows),
            "evidence": [t.get("raw_anchor") for t in declined_rows][:10],
        },
    }


# --------------------------------------------------------------------------
# Column mapping
# --------------------------------------------------------------------------

_HEADER_ALIASES = {
    "date": ("date", "transaction date", "txn date"),
    "process_date": ("process date", "processed", "posting date", "posted"),
    "description": ("description", "details", "particulars", "transaction", "narrative"),
    "withdrawal": ("withdrawal", "withdrawals", "debit", "debits", "payments", "money out"),
    "deposit": ("deposit", "deposits", "credit", "credits", "money in"),
    "amount": ("amount", "value"),
    "balance": ("balance", "running balance"),
}


def map_columns(header_row: list[Any]) -> dict[str, int]:
    """Map a table's header cells onto canonical column roles."""
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        text = re.sub(r"\s+", " ", str(cell or "")).strip().lower()
        if not text:
            continue
        for role, aliases in _HEADER_ALIASES.items():
            if role in mapping:
                continue
            if text in aliases or any(text.startswith(a) for a in aliases):
                mapping[role] = idx
                break
    return mapping


def _looks_like_header(row: list[Any]) -> bool:
    mapping = map_columns(row)
    return "description" in mapping and ("date" in mapping or "amount" in mapping)


# --------------------------------------------------------------------------
# Normalize
# --------------------------------------------------------------------------


def _txn_id(source_file: str, page: int, index: int, description: str) -> str:
    raw = f"{source_file}|{page}|{index}|{description}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def normalize(layout: dict[str, Any], assessment_date: str) -> dict[str, Any]:
    """Turn one file's layout into `{account, transactions}`.

    Raises ExtractionError when the file yields no usable transaction table;
    the caller records a rejected account rather than inventing rows.
    """
    source_file = layout["source_file"]
    lines = list(layout.get("lines") or [])
    tables = list(layout.get("tables") or [])

    period_start, period_end = parse_period(lines)
    account_type = detect_account_type(lines)
    institution = detect_institution(lines)
    account_number = _account_number(lines)
    account_id = hashlib.sha1(
        f"{institution}|{account_number or source_file}".encode("utf-8")
    ).hexdigest()[:12]

    assessed = datetime.strptime(assessment_date, "%Y-%m-%d").date()

    transactions: list[dict[str, Any]] = []
    for table in tables:
        page = int(table.get("page_number") or 1)
        rows = [r for r in (table.get("rows") or []) if any(str(c or "").strip() for c in r)]
        if not rows:
            continue
        header_idx = next((i for i, r in enumerate(rows) if _looks_like_header(r)), None)
        if header_idx is None:
            continue
        cols = map_columns(rows[header_idx])

        for offset, row in enumerate(rows[header_idx + 1:], start=1):
            txn = _row_to_transaction(
                row, cols, page, offset, source_file, account_id,
                account_type, period_start, period_end,
            )
            if txn is not None:
                transactions.append(txn)

    if not transactions:
        raise ExtractionError(
            f"{source_file}: no transaction table could be read from the layout result"
        )

    dates = [datetime.strptime(t["date"], "%Y-%m-%d").date() for t in transactions]
    start = period_start or min(dates)
    end = period_end or max(dates)

    account = {
        "account_id": account_id,
        "account_label": _account_label(lines, account_type),
        "institution": institution,
        "account_type": account_type,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "days_covered": (end - start).days + 1,
        "days_old": (assessed - end).days,
        "source_file": source_file,
        "is_statement": True,
        "reject_reason": None,
    }
    opening = _labelled_balance(lines, "opening")
    closing = _labelled_balance(lines, "closing")
    if opening is not None:
        account["opening_balance"] = opening
    if closing is not None:
        account["closing_balance"] = closing
    limit = _labelled_balance(lines, "credit limit")
    if limit is not None:
        account["credit_limit"] = limit

    account["applicant"] = _applicant_evidence(lines)
    account["conduct"] = _conduct_assessment(lines, transactions, account_type, limit)

    return {"account": account, "transactions": transactions}


def _labelled_balance(lines: Iterable[str], label: str) -> float | None:
    for line in lines:
        low = line.lower()
        if label in low:
            tail = line[low.index(label) + len(label):]
            try:
                return parse_money(tail)
            except ExtractionError:
                return None
    return None


def _row_to_transaction(
    row: list[Any],
    cols: dict[str, int],
    page: int,
    offset: int,
    source_file: str,
    account_id: str,
    account_type: str,
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any] | None:
    def cell(role: str) -> Any:
        idx = cols.get(role)
        return row[idx] if idx is not None and idx < len(row) else None

    description = re.sub(r"\s+", " ", str(cell("description") or "")).strip()
    if not description:
        return None

    raw_anchor = f"{source_file} p{page} :: " + " | ".join(
        str(c or "").strip() for c in row if str(c or "").strip()
    )[:300]

    balance = parse_money(cell("balance"))
    txn_date = resolve_date(cell("date"), period_start, period_end)
    process_date = resolve_date(cell("process_date"), period_start, period_end)
    # extract-normalize.md: prefer the transaction date over the process date.
    if txn_date is None:
        txn_date = process_date
        process_date = None
    if txn_date is None:
        raw_date = str(cell("date") or "")
        # Page footers (`Totals at end` / `of page`) are not postings.
        if _is_non_date_label(raw_date) or "OF PAGE" in description.upper():
            return None
        # A balance-carrying line may legitimately carry an out-of-period date
        # (the Westpac specimen dates its opening balance `03 Sept`). Anchor it
        # to the period rather than inventing a year.
        if is_non_transaction(description) and period_start is not None:
            txn_date = period_start
        elif is_non_transaction(description) or is_non_transaction(raw_date):
            return None
        else:
            # Never drop a money row silently: an unreadable date on a real
            # posting means the file was misread, and the caller must hear it.
            if parse_money(cell("withdrawal")) or parse_money(cell("deposit")) or parse_money(cell("amount")):
                raise ExtractionError(
                    f"{source_file} p{page}: posted row {description!r} has an unreadable date "
                    f"{cell('date')!r}; refusing to guess"
                )
            return None

    base = {
        "transaction_id": _txn_id(source_file, page, offset, description),
        "account_id": account_id,
        "date": txn_date.isoformat(),
        "description": description,
        "merchant_normalized": normalize_merchant(description),
        "balance": balance,
        "raw_anchor": raw_anchor,
        "source_file": source_file,
    }
    if process_date is not None:
        base["process_date"] = process_date.isoformat()

    # Balance-only and summary rows are not transactions.
    if is_non_transaction(description):
        return {**base, "amount": 0.0, "direction": "info", "raw_amount_text": ""}

    # A declined line moves no money. The only figure printed on it is the
    # unchanged running balance, which must never become an amount.
    if is_declined(description):
        return {**base, "amount": 0.0, "direction": "info", "raw_amount_text": str(cell("amount") or "")}

    withdrawal = parse_money(cell("withdrawal"))
    deposit = parse_money(cell("deposit"))
    amount_cell = cell("amount")
    amount = parse_money(amount_cell)

    if withdrawal:
        value, direction = withdrawal, "outflow"
        raw_text = str(cell("withdrawal"))
    elif deposit:
        value, direction = deposit, "inflow"
        raw_text = str(cell("deposit"))
    elif amount is not None:
        raw_text = str(amount_cell or "")
        value = abs(amount)
        direction = _direction_from_amount(amount, raw_text, description, account_type)
    else:
        # No money column resolved: a balance-carrying line with no posting.
        return {**base, "amount": 0.0, "direction": "info", "raw_amount_text": ""}

    if value == 0:
        return {**base, "amount": 0.0, "direction": "info", "raw_amount_text": raw_text}

    return {**base, "amount": abs(value), "direction": direction, "raw_amount_text": raw_text}


def _direction_from_amount(
    amount: float, raw_text: str, description: str, account_type: str
) -> str:
    """Single signed/unsigned amount column -> direction.

    Credit cards invert the household convention: a purchase increases debt and
    is an outflow for servicing, while a payment or a `CR`-marked line reduces
    it and is an inflow.
    """
    up = f"{raw_text} {description}".upper()
    marked_credit = bool(re.search(r"\bCR\b", up))
    reads_as_payment = bool(
        _CARD_PAYMENT_RE.search(up) and not _CARD_PAYMENT_EXCLUDE_RE.search(up)
    )

    if account_type == "credit_card":
        # A negative amount on a card is money coming off the balance.
        if amount < 0 or marked_credit or reads_as_payment:
            return "inflow"
        return "outflow"

    if marked_credit:
        return "inflow"
    if amount < 0:
        return "outflow"
    return "inflow" if amount > 0 and "DEPOSIT" in up else "outflow"


# --------------------------------------------------------------------------
# Azure Document Intelligence adapter (the only part needing credentials)
# --------------------------------------------------------------------------


def _client():
    endpoint = os.environ.get("DOCUMENTINTELLIGENCE_ENDPOINT")
    key = os.environ.get("DOCUMENTINTELLIGENCE_KEY")
    if not endpoint or not key:
        raise ExtractionError(
            "DOCUMENTINTELLIGENCE_ENDPOINT / DOCUMENTINTELLIGENCE_KEY are not set on "
            "this Function App. Extraction cannot run; no rows are returned."
        )
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    return DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(key))


def pdf_page_count(content: bytes) -> int | None:
    """Page count straight from the PDF bytes, with no extra dependency.

    Used only to compare against how many pages the extractor actually
    analyzed. A tier or size limit that quietly truncates a binder is the one
    failure the downstream QC gates cannot see: every row that survives is
    correct, so all the reconciliations pass while half a month of spending is
    simply absent.
    """
    if not content.startswith(b"%PDF"):
        return None
    m = re.search(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", content)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    hits = len(re.findall(rb"/Type\s*/Page[^s]", content))
    return hits or None


def di_result_to_layout(result: Any, source_file: str) -> dict[str, Any]:
    """Adapt a prebuilt-layout result into the neutral layout dict."""
    lines: list[str] = []
    for page in getattr(result, "pages", None) or []:
        for line in getattr(page, "lines", None) or []:
            content = getattr(line, "content", None)
            if content:
                lines.append(content)

    tables: list[dict[str, Any]] = []
    for table in getattr(result, "tables", None) or []:
        row_count = getattr(table, "row_count", 0) or 0
        col_count = getattr(table, "column_count", 0) or 0
        grid = [["" for _ in range(col_count)] for _ in range(row_count)]
        page_number = 1
        for cellv in getattr(table, "cells", None) or []:
            r = getattr(cellv, "row_index", 0) or 0
            c = getattr(cellv, "column_index", 0) or 0
            if r < row_count and c < col_count:
                grid[r][c] = getattr(cellv, "content", "") or ""
            regions = getattr(cellv, "bounding_regions", None) or []
            if regions:
                page_number = getattr(regions[0], "page_number", page_number) or page_number
        tables.append({"page_number": page_number, "rows": grid})

    pages = getattr(result, "pages", None) or []
    return {
        "source_file": source_file,
        "lines": lines,
        "tables": tables,
        "analyzed_page_count": len(pages),
    }


def check_page_coverage(layout: dict[str, Any], content: bytes) -> None:
    """Fail loudly if the extractor read fewer pages than the file contains.

    A service tier that caps pages per document truncates silently: the rows it
    did return are all correct, so every reconciliation downstream agrees with
    itself. Only a page count catches it.
    """
    analyzed = layout.get("analyzed_page_count")
    total = pdf_page_count(content)
    if not analyzed or not total:
        return
    if analyzed < total:
        raise ExtractionError(
            f"{layout['source_file']}: extractor analyzed {analyzed} of {total} pages. "
            "Transactions on the unread pages would be missing without any other "
            "check noticing. Refusing to return a partial binder — check the "
            "Document Intelligence pricing tier's per-document page limit."
        )


def analyze_layout(content: bytes, source_file: str) -> dict[str, Any]:
    """Run prebuilt-layout over one file and return the neutral layout dict."""
    client = _client()
    poller = client.begin_analyze_document("prebuilt-layout", body=content)
    layout = di_result_to_layout(poller.result(), source_file)
    check_page_coverage(layout, content)
    return layout


MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024

# Statement URLs arrive from a model, which in turn takes them from a user
# message. That is an untrusted path into a function that makes outbound
# requests from inside Azure, so `fetch_url` is a classic SSRF sink: without a
# host allowlist, `http://169.254.169.254/metadata/identity/oauth2/token` would
# hand this app's managed-identity token to whoever asked. Three defences, all
# required: an explicit host allowlist, no redirects, and a check that the
# resolved address is publicly routable.
DEFAULT_ALLOWED_HOST_SUFFIXES = (".blob.core.windows.net",)


def allowed_host_suffixes() -> tuple[str, ...]:
    configured = os.environ.get("EXTRACT_URL_ALLOWED_HOSTS", "").strip()
    if not configured:
        return DEFAULT_ALLOWED_HOST_SUFFIXES
    return tuple(h.strip().lower() for h in configured.split(",") if h.strip())


class _NoRedirects(__import__("urllib.request", fromlist=["x"]).HTTPRedirectHandler):
    """A redirect is an allowlist bypass: the first hop passes, the second is
    wherever the redirect points. Refuse instead of following."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise ExtractionError(
            f"refusing to follow a redirect to {newurl!r}; supply the final URL directly"
        )


def _assert_public_address(host: str) -> None:
    import ipaddress
    import socket

    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise ExtractionError(f"{host}: DNS lookup failed ({exc})") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if (
            addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_reserved or addr.is_multicast or addr.is_unspecified
        ):
            raise ExtractionError(
                f"{host} resolves to the non-public address {addr}; refusing to fetch it. "
                "Statement files must come from the configured storage host."
            )


def fetch_url(url: str, timeout: int = 120) -> tuple[str, bytes]:
    """Download one statement file. Returns (filename, bytes).

    A calling agent cannot base64-encode a PDF - it has no access to the bytes,
    and a single encoded statement would not fit in its context anyway. So the
    agent-facing path is a URL it can simply repeat, and the download happens
    here - behind the allowlist described above.
    """
    import urllib.parse
    import urllib.request

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ExtractionError(
            f"{url.split('?')[0]!r}: only https URLs are accepted"
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise ExtractionError(f"{url.split('?')[0]!r}: no host in URL")

    suffixes = allowed_host_suffixes()
    if not any(host == suf.lstrip(".") or host.endswith(suf) for suf in suffixes):
        raise ExtractionError(
            f"host {host!r} is not in the allowlist {suffixes}. "
            "Upload the statement to the configured storage account and pass that URL."
        )
    _assert_public_address(host)

    name = os.path.basename(urllib.parse.unquote(parsed.path)) or "unnamed.pdf"
    opener = urllib.request.build_opener(_NoRedirects)

    try:
        with opener.open(url, timeout=timeout) as resp:
            declared = resp.headers.get("Content-Length")
            if declared and int(declared) > MAX_DOWNLOAD_BYTES:
                raise ExtractionError(f"{name}: {declared} bytes exceeds the {MAX_DOWNLOAD_BYTES} byte limit")
            content = resp.read(MAX_DOWNLOAD_BYTES + 1)
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - reported per file, never swallowed
        raise ExtractionError(f"{name}: download failed ({type(exc).__name__}: {exc})") from exc

    if len(content) > MAX_DOWNLOAD_BYTES:
        raise ExtractionError(f"{name}: larger than the {MAX_DOWNLOAD_BYTES} byte limit")
    if not content:
        raise ExtractionError(f"{name}: downloaded 0 bytes")
    if not content.startswith(b"%PDF") and not content.startswith(b"\xff\xd8") and not content.startswith(b"\x89PNG"):
        raise ExtractionError(
            f"{name}: content is not a PDF or image (starts with {content[:8]!r}). "
            "A SAS URL that has expired returns an XML error document, which looks like this."
        )
    return name, content


# --------------------------------------------------------------------------
# Binder path: the server reads the container itself.
#
# Pasting a SAS URL into a chat box failed twice in practice - the query string
# was truncated on the way in, and while it worked the access token would have
# lived in the conversation history forever. With a binder name, the caller
# says only *which* container; the URL and the credential never leave this
# process. That also means this path makes no outbound request at all, so the
# SSRF surface that `file_urls` needs guarding for simply does not exist here.
# --------------------------------------------------------------------------

# Azure container naming rules, which also happen to exclude path traversal:
# lowercase letters, digits and single hyphens, 3-63 chars.
_BINDER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?![-]))*[a-z0-9]$")
STATEMENT_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff")


def allowed_binders() -> tuple[str, ...]:
    """The container names this app will read, from EXTRACT_ALLOWED_BINDERS.

    Fail-closed on purpose. An earlier version treated "unset" as "any valid
    container name", which meant a fresh environment that forgot this setting
    would happily read `azure-webjobs-secrets` on the same storage account and
    hand back the Function App's own keys. A missing allowlist is a
    misconfiguration, not permission.
    """
    configured = os.environ.get("EXTRACT_ALLOWED_BINDERS", "").strip()
    if not configured:
        raise ExtractionError(
            "EXTRACT_ALLOWED_BINDERS is not set on this Function App, so no binder "
            "may be read. Set it to the container(s) holding statements, e.g. "
            "EXTRACT_ALLOWED_BINDERS=vikas-samples."
        )
    return tuple(b.strip().lower() for b in configured.split(",") if b.strip())


def validate_binder(name: Any) -> str:
    binder = str(name or "").strip().lower()
    if not (3 <= len(binder) <= 63) or not _BINDER_RE.match(binder):
        raise ExtractionError(
            f"binder {name!r} is not a valid container name: 3-63 chars, lowercase "
            "letters, digits and single hyphens only"
        )
    allowed = allowed_binders()
    if binder not in allowed:
        raise ExtractionError(f"binder {binder!r} is not in the allowed set {allowed}")
    return binder


def _storage_connection_string() -> str:
    # Deliberately one named setting, not a fallback chain. Falling back to
    # AzureWebJobsStorage would point statement reads at the account that also
    # holds this app's own secrets container.
    value = os.environ.get("STATEMENTS_STORAGE_CONNECTION_STRING")
    if value and "AccountKey" in value:
        return value
    raise ExtractionError(
        "STATEMENTS_STORAGE_CONNECTION_STRING is not configured on this Function "
        "App; binder reads are disabled until it is set."
    )


def read_binder(binder: str, prefix: str | None = None) -> list[tuple[str, bytes]]:
    """List and download every statement file in one container.

    Returns [(filename, content)]. Raises rather than returning an empty list,
    because an empty binder and an unreadable binder must not look the same to
    the caller.
    """
    from azure.storage.blob import ContainerClient

    binder = validate_binder(binder)
    clean_prefix = (prefix or "").lstrip("/")
    if ".." in clean_prefix:
        raise ExtractionError(f"prefix {prefix!r} may not contain '..'")

    client = ContainerClient.from_connection_string(_storage_connection_string(), binder)
    try:
        names = [b.name for b in client.list_blobs(name_starts_with=clean_prefix or None)]
    except Exception as exc:  # noqa: BLE001 - surfaced with the binder name
        raise ExtractionError(f"binder {binder!r} could not be listed ({type(exc).__name__}: {exc})") from exc

    statements = [n for n in sorted(names) if n.lower().endswith(STATEMENT_SUFFIXES)]
    if not statements:
        raise ExtractionError(
            f"binder {binder!r}{' prefix ' + clean_prefix if clean_prefix else ''} "
            f"holds no statement files (saw {len(names)} blobs, none ending in "
            f"{', '.join(STATEMENT_SUFFIXES)})"
        )

    out: list[tuple[str, bytes]] = []
    for name in statements:
        try:
            content = client.download_blob(name).readall()
        except Exception as exc:  # noqa: BLE001
            raise ExtractionError(f"{name}: download from binder {binder!r} failed ({exc})") from exc
        if len(content) > MAX_DOWNLOAD_BYTES:
            raise ExtractionError(f"{name}: larger than the {MAX_DOWNLOAD_BYTES} byte limit")
        if not content.startswith(b"%PDF") and not content.startswith(b"\xff\xd8") and not content.startswith(b"\x89PNG"):
            raise ExtractionError(
                f"{name}: content is not a PDF or image (starts with {content[:8]!r})"
            )
        out.append((os.path.basename(name), content))
    return out


def _normalise_url_entry(entry: Any) -> tuple[str | None, str]:
    """Accept either a bare URL string or {filename, url}."""
    if isinstance(entry, str):
        return None, entry
    if isinstance(entry, dict):
        url = entry.get("url") or entry.get("content_url") or entry.get("href")
        if not url:
            raise ExtractionError(f"file_urls entry {entry!r} has no url")
        return entry.get("filename"), url
    raise ExtractionError(f"file_urls entry {entry!r} must be a URL string or an object with a url")


def extract_and_normalize(
    files: list[dict[str, Any]] | None,
    assessment_date: str,
    file_urls: list[Any] | None = None,
    binder: str | None = None,
    prefix: str | None = None,
) -> dict[str, Any]:
    """Full pass over a binder. One rejected file never blocks the others.

    Three input shapes, in order of preference:
      binder     "vikas-samples"                - the server reads the container
      file_urls  ["https://...", ...]           - caller supplies links
      files      [{filename, content_base64}]   - caller already holds the bytes

    `binder` is the one to reach for. Nothing about the files - not the URL,
    not the credential - has to travel through the caller, so nothing can be
    truncated in transit or left behind in a conversation log.
    """
    import base64

    accounts: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []
    errors: list[str] = []

    sources: list[tuple[str, Any]] = []
    if binder:
        # A failure here is fatal for the whole request: an unreadable binder
        # must not be reported as "no transactions found".
        sources += [("bytes", pair) for pair in read_binder(binder, prefix)]
    sources += [("url", e) for e in (file_urls or [])]
    sources += [("b64", e) for e in (files or [])]
    if not sources:
        raise ExtractionError(
            "none of `binder`, `file_urls` or `files` was supplied; "
            "extraction has nothing to read"
        )

    for kind, entry in sources:
        name = "unnamed"
        try:
            if kind == "bytes":
                name, content = entry
            elif kind == "url":
                given_name, url = _normalise_url_entry(entry)
                name, content = fetch_url(url)
                name = given_name or name
            else:
                name = entry.get("filename") or "unnamed"
                content = base64.b64decode(entry["content_base64"])
            layout = analyze_layout(content, name)
            batch = normalize(layout, assessment_date)
        except ExtractionError as exc:
            errors.append(str(exc))
            accounts.append(
                {
                    "account_id": hashlib.sha1(name.encode()).hexdigest()[:12],
                    "institution": "Not provided in binder",
                    "account_type": "other",
                    "period_start": assessment_date,
                    "period_end": assessment_date,
                    "source_file": name,
                    "is_statement": False,
                    "reject_reason": str(exc),
                }
            )
            continue
        except Exception as exc:  # noqa: BLE001 - surfaced, never silently dropped
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        accounts.append(batch["account"])
        transactions.extend(batch["transactions"])

    return {
        "assessment_date": assessment_date,
        "applicant": _merge_applicant_evidence(accounts),
        "accounts": accounts,
        "document_index": _document_index(accounts),
        "transactions": transactions,
        "errors": errors,
    }


def _merge_applicant_evidence(accounts: list[dict[str, Any]]) -> dict[str, str]:
    fields = ("Full Name(s)", "Age(s)", "Dependants", "Address and living situation")
    merged: dict[str, str] = {}
    for field in fields:
        values = []
        for account in accounts:
            value = (account.get("applicant") or {}).get(field)
            if value and value != "Not provided in binder" and value not in values:
                values.append(value)
        merged[field] = "; ".join(values) if values else "Not provided in binder"
    return merged


def _document_index(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted = [a for a in accounts if a.get("is_statement")]
    accepted.sort(key=lambda a: (a.get("account_label") or "", a.get("period_start") or "", a.get("source_file") or ""))
    return [
        {
            "institution": a.get("institution"),
            "account_id": a.get("account_id"),
            "account_label": a.get("account_label") or "Not provided in binder",
            "account_type": a.get("account_type"),
            "period_start": a.get("period_start"),
            "period_end": a.get("period_end"),
            "days_covered": a.get("days_covered"),
            "days_old": a.get("days_old"),
            "source_file": a.get("source_file"),
            "conduct": a.get("conduct"),
        }
        for a in accepted
    ]


# --------------------------------------------------------------------------
# Report delivery
# --------------------------------------------------------------------------

REPORTS_CONTAINER = os.environ.get("REPORTS_CONTAINER", "vikas-reports")


def publish_report(content: bytes, filename: str, hours_valid: int = 24) -> dict[str, Any]:
    """Put the rendered workbook somewhere the user can click, and return a link.

    Handing the caller a base64 blob does not deliver a file. An agent has no
    way to write bytes to disk, so it reports "Attached: lender-assessment.xlsx"
    and attaches nothing - the mirror image of the input problem, where base64
    could not get in either. A URL is the thing a chat reply can actually carry.

    Writes to its own container, never the statements binder: reports are
    generated output and should not land where input files are read from.
    """
    from datetime import datetime, timedelta, timezone

    from azure.storage.blob import (
        BlobSasPermissions,
        BlobServiceClient,
        ContentSettings,
        generate_blob_sas,
    )

    service = BlobServiceClient.from_connection_string(_storage_connection_string())
    container = service.get_container_client(REPORTS_CONTAINER)
    try:
        container.create_container()
    except Exception:  # noqa: BLE001 - already exists is the normal case
        pass

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    blob_name = f"{stamp}-{filename}"
    container.upload_blob(
        name=blob_name,
        data=content,
        overwrite=True,
        content_settings=ContentSettings(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )

    expiry = datetime.now(timezone.utc) + timedelta(hours=hours_valid)
    sas = generate_blob_sas(
        account_name=service.account_name,
        container_name=REPORTS_CONTAINER,
        blob_name=blob_name,
        account_key=service.credential.account_key,
        permission=BlobSasPermissions(read=True),
        expiry=expiry,
    )
    url = f"{service.url.rstrip('/')}/{REPORTS_CONTAINER}/{blob_name}?{sas}"
    return {
        "filename": filename,
        "download_url": url,
        "expires_at": expiry.replace(microsecond=0).isoformat(),
        "size_bytes": len(content),
    }


# ---------------------------------------------------------------------------
# Canonical batch store
#
# `compute_summary` used to require the caller to hand back the entire canonical
# batch. For the four fixtures that was 52 rows and nobody noticed. On a real
# binder it is 611 rows and 290 KB, and an agent cannot carry 290 KB through a
# tool call: Foundry truncated the body mid-array, so `transactions` arrived
# with seven rows and a trailing `null` and compute answered 400.
#
# This is the same mistake as base64-in (an agent cannot read file bytes) and
# base64-out (an agent cannot write them), for the third time: routing bulk data
# through the model, which is a judge with a bounded context and not a pipe.
# The batch stays on the server and the model carries an id.

BATCHES_CONTAINER = os.environ.get("BATCHES_CONTAINER", "vikas-batches")

# A batch id names a blob, so it must not be able to name a different one.
# Traversal, slashes and leading dots are all excluded by construction.
_BATCH_ID_RE = re.compile(r"^[0-9a-f]{8}T[0-9a-f]{6}-[0-9a-f]{16}$")


class BatchNotFound(ExtractionError):
    """The id is well formed but no such batch is stored."""


def validate_batch_id(batch_id: str) -> str:
    text = str(batch_id or "").strip()
    if not _BATCH_ID_RE.match(text):
        raise ExtractionError(
            f"batch_id {text!r} is not a valid id; expected the value returned by "
            "extract_and_normalize, e.g. '68b6a1f0T0c3d5e-9f2c4a7b1d8e0f36'"
        )
    return text


def _batches_container():
    from azure.storage.blob import BlobServiceClient

    service = BlobServiceClient.from_connection_string(_storage_connection_string())
    container = service.get_container_client(BATCHES_CONTAINER)
    try:
        container.create_container()
    except Exception:  # noqa: BLE001 - already exists is the normal case
        pass
    return container


def store_batch(batch: dict[str, Any]) -> str:
    """Persist a canonical batch server-side and return its id.

    Its own container, never the statements binder and never the reports
    container: input, working state and deliverables each stay where they
    belong, and `EXTRACT_ALLOWED_BINDERS` is not widened to reach any of them.
    """
    from datetime import datetime, timezone

    stamp = f"{int(datetime.now(timezone.utc).timestamp()):08x}"
    batch_id = f"{stamp}T{os.urandom(3).hex()}-{os.urandom(8).hex()}"
    payload = json.dumps(batch, ensure_ascii=False).encode("utf-8")
    _batches_container().upload_blob(name=f"{batch_id}.json", data=payload, overwrite=False)
    return batch_id


CLASSIFICATION_SUFFIX = ".classifications.json"


def _classification_key(row: dict[str, Any]) -> tuple[str, str]:
    """What makes two classifications the same decision.

    A transaction_id classification is about one row; a merchant one is about
    every row of that merchant. They are different keys on purpose, so a
    per-row correction can sit alongside the merchant rule it overrides.
    """
    txn_id = str(row.get("transaction_id") or "").strip()
    if txn_id:
        return ("txn", txn_id)
    return ("merchant", str(row.get("merchant") or "").strip().upper())


def merge_classifications(
    batch_id: str, rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Accumulate a batch's classifications across calls.

    A binder of 238 merchants cannot be reclassified in one pass, and asking
    the agent to resend everything it already decided is what exhausted its
    context window. The server keeps what it has been told; a repair pass
    sends only the merchants it just worked out.

    Last write wins, so a correction is a resend of that one entry. Order is
    stable - previously stored entries keep their position, new ones append -
    so the same calls always produce the same list.
    """
    batch_id = validate_batch_id(batch_id)
    blob = f"{batch_id}{CLASSIFICATION_SUFFIX}"
    from azure.core.exceptions import ResourceNotFoundError

    try:
        stored = json.loads(_batches_container().download_blob(blob).readall())
    except ResourceNotFoundError:
        stored = []
    if not isinstance(stored, list):
        stored = []

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in stored:
        if isinstance(row, dict):
            merged[_classification_key(row)] = row
    known_before = len(merged)

    added = replaced = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = _classification_key(row)
        if key == ("merchant", ""):
            continue
        if key in merged:
            replaced += 1
        else:
            added += 1
        merged[key] = row

    out = list(merged.values())
    payload = json.dumps(out, ensure_ascii=False).encode("utf-8")
    _batches_container().upload_blob(name=blob, data=payload, overwrite=True)
    return out, {
        "known_before": known_before,
        "sent_this_call": len([r for r in (rows or []) if isinstance(r, dict)]),
        "added": added,
        "replaced": replaced,
        "total": len(out),
    }


def load_batch(batch_id: str) -> dict[str, Any]:
    """Read a stored canonical batch back.

    A missing batch is reported as missing. Returning an empty batch instead
    would let the whole chain proceed and produce a workbook of zeroes, which is
    exactly the failure this project started with.
    """
    batch_id = validate_batch_id(batch_id)
    from azure.core.exceptions import ResourceNotFoundError

    try:
        raw = _batches_container().download_blob(f"{batch_id}.json").readall()
    except ResourceNotFoundError:
        raise BatchNotFound(
            f"no stored batch {batch_id!r}. Batches expire; call extract_and_normalize "
            "again and use the batch_id it returns."
        ) from None
    return json.loads(raw)


def classification_worklist(batch: dict[str, Any], sample_chars: int = 60) -> list[dict[str, Any]]:
    """One entry per merchant that actually needs a human-level judgement.

    The model's job is to say what kind of spending something is. It does not
    need to see 611 rows to do that: `info` rows carry no money and are already
    settled by extraction, and the remaining rows are the same 238 merchants
    over and over. Sixteen visits to Fu Market are one question, not sixteen.

    Each entry is small on purpose - a merchant, how often, how much, a sample
    line to judge it by. That is the whole context needed to pick a category,
    and it is roughly a quarter of the tokens of an equivalent per-row batch.
    """
    from statistics import median

    groups: dict[str, list[dict[str, Any]]] = {}
    for txn in batch.get("transactions") or []:
        if (txn.get("direction") or "info") == "info":
            continue  # no money moved; extraction has already settled it
        key = str(txn.get("merchant_normalized") or "").upper().strip()
        if not key:
            key = str(txn.get("description") or "").upper().strip()[:sample_chars]
        groups.setdefault(key, []).append(txn)

    worklist = []
    for merchant, rows in groups.items():
        amounts = [abs(float(r.get("amount") or 0)) for r in rows]
        dates = sorted(str(r.get("date") or "") for r in rows)
        directions = sorted({r.get("direction") or "" for r in rows})
        worklist.append(
            {
                "merchant": merchant,
                "occurrences": len(rows),
                "total_amount": round(sum(amounts), 2),
                "median_amount": round(median(amounts), 2) if amounts else 0.0,
                "first_date": dates[0] if dates else None,
                "last_date": dates[-1] if dates else None,
                "direction": directions[0] if len(directions) == 1 else "mixed",
                "sample_description": str(rows[0].get("description") or "")[:sample_chars],
            }
        )
    # Biggest spend first: if the caller ever has to stop early, the money that
    # matters most to a servicing decision is already classified.
    worklist.sort(key=lambda e: -e["total_amount"])
    return worklist
