"""Parse a receipt text layer. Recompute cash; never invent a garbled total."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re


@dataclass
class ParsedRow:
    tax_year: str
    date: str
    vendor: str
    description: str
    schedule_c_or_form: str
    amount_usd: str
    status: str
    payment_method: str
    evidence: str
    notes: str
    order_id: str | None = None
    gap: str | None = None
    subtotal: str = ""
    shipping: str = ""
    tax: str = ""
    discount: str = ""
    printed_total: str = ""
    rewards: str = ""
    evidence_sha256: str = ""
    row_id: str = ""
    card_amount: str = ""

    def as_csv(self) -> dict[str, str]:
        return {
            "tax_year": self.tax_year,
            "date": self.date,
            "vendor": self.vendor,
            "description": self.description,
            "schedule_c_or_form": self.schedule_c_or_form,
            "amount_usd": self.amount_usd,
            "status": self.status,
            "payment_method": self.payment_method,
            "evidence": self.evidence,
            "notes": self.notes,
            "row_id": self.row_id,
            "evidence_sha256": self.evidence_sha256,
            "order_id": self.order_id or "",
            "subtotal": self.subtotal,
            "shipping": self.shipping,
            "tax": self.tax,
            "discount": self.discount or self.rewards,
            "printed_total": self.printed_total,
        }


# Well-formed money only: dollars with exactly two cents digits, no extra dots.
# Allow 4+ digit amounts without commas ($4279.99) — Amazon prints those.
_MONEY = re.compile(r"\$\s*((?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})(?!\.?\d)")
# Labeled totals on thermal storefronts often omit `$` ("TOTAL: 12.34").
# Unlabeled line prices are not totals; only this after-label form is optional-$.
_MONEY_AFTER_LABEL = re.compile(
    # Optional currency parenthetical used on invoices: "Total (USD) $5,512.65",
    # "Amount Paid (USD) $645.00". Three-letter codes only; keep the money
    # immediately after the label otherwise.
    # Storefront checkouts also print a bare ISO code before the dollar sign
    # ("Total:\nUSD $30.00"); that form requires the `$` so prose such as
    # "Total due" or other three-letter words never become a money prefix.
    r"[:\s]*(?:\([A-Za-z]{3}\)|(?:USD|CAD|EUR|GBP|AUD)(?=\s*\$))?"
    r"[:\s]*-?\s*\$?\s*"
    r"((?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})(?!\.?\d)"
)

_ORDER_PATTERNS = (
    re.compile(r"Order\s*#\s*(\d{3}-\d{7}-\d{7})", re.I),
    re.compile(r"\bORDER\s+(DG-\d+)\b", re.I),
    re.compile(r"Invoice number\s+(IN\d+|HRB[A-Z0-9]+)", re.I),
    re.compile(r"\bINVOICE\s+(\d{4,8})\b", re.I),
    re.compile(r"Receipt number\s+(\d{10,})", re.I),
    re.compile(r"Order\s*#\s*(OW[A-Z0-9]+)", re.I),
    re.compile(r"ORDER NO\s*#(\d+)", re.I),
    re.compile(r"Trans(?:action)?\s*I\.?D\.?\s*:?\s*(\d{10,})", re.I),
    re.compile(r"\border\s+(\d{2}-\d{5}-\d{5})\b", re.I),
    re.compile(r"\border\s+(\d{6,8})\b", re.I),
    # Storefront order pages (Apex Distribution "Order #1216"). Last, so the
    # vendor-specific patterns above win; never eats an Amazon 111-... id.
    re.compile(r"\bOrder\s*#\s*(\d{4,6})(?![\d-])", re.I),
)

_DATE_PATTERNS = (
    re.compile(r"Order placed\s+([A-Za-z]+ \d{1,2}, \d{4})", re.I),
    re.compile(r"\bPLACED\s+([A-Za-z]+ \d{1,2}, \d{4})", re.I),
    re.compile(r"Date of issue\s+([A-Za-z]+ \d{1,2}, \d{4})", re.I),
    re.compile(r"Date paid\s+([A-Za-z]+ \d{1,2}, \d{4})", re.I),
    re.compile(r"paid on\s+([A-Za-z]+ \d{1,2}, \d{4})", re.I),
    re.compile(r"\bDATE\s+(\d{1,2} [A-Za-z]+ \d{4})", re.I),
    # Bare "Date:" label at the start of a line, value on the same or the next
    # line ("Date:\nNovember 13, 2026" on storefront order confirmations).
    # Line-anchored so "Due Date:", "Ship Date:", or "Expiration Date:" never
    # match; month name is validated by strptime in _parse_date.
    re.compile(
        r"^[ \t]*Date:[ \t]*(?:\r?\n[ \t]*){0,2}([A-Za-z]+ \d{1,2}, \d{4})",
        re.I | re.M,
    ),
    re.compile(r"Confirmed\s+([A-Za-z]+ \d{1,2}(?:,?\s+\d{4})?)", re.I),
    # Slash (08/29/26) or hyphen (03-15-26) numeric dates. Not ISO YYYY-MM-DD
    # — the first group is 1-2 digits, so 2026-03-15 does not match.
    re.compile(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b"),
)

_SUBTOTAL = re.compile(r"Item(?:\(s\))?\s*Subtotal:|\bSubtotal\b", re.I)
_TAX = re.compile(
    r"Estimated tax to be\s*collected:|TOTAL\s+T(?:AX)?\b|(?<!before )(?<!after )\bTax\b",
    re.I,
)
_REWARDS = re.compile(r"Rewards(?: Points)?:", re.I)
# Optional carrier parenthetical: "Shipping (FedEx Ground®) $20.16".
_SHIP_CARRIER = r"(?:\s*\([^)\n]{1,40}\))?"
_SHIP = re.compile(
    r"Shipping(?:\s*&\s*Handling)?" + _SHIP_CARRIER + r":"
    r"|(?:^|\n)\s*Shipping" + _SHIP_CARRIER + r"\s+(?=\$)",
    re.I,
)
_FREE_SHIP = re.compile(r"Free Shipping:", re.I)
_GRAND = re.compile(
    r"Grand Total:|Amount due\b|Amount paid\b|Payment amount:?",
    re.I,
)
# Card/terminal AMOUNT is a diagnostic candidate, not Grand Total. Used as
# listed only when no Grand Total / TOTAL line exists (thermal POS slips).
_CARD = re.compile(
    r"(?<![Pp]ayment )(?<![Aa]mount )\bA[HNM]OUNT\b(?!\s+due\b)(?!\s+paid\b)",
    re.I,
)
# Do not treat "TOTAL TAX" / OCR "TOTAL T" / "Total before tax" as cash total.
_TOTAL = re.compile(r"\bTOTAL\b(?!\s*TAX)(?!\s+T\b)(?!\s*BEFORE)", re.I)
_PER_MONTH = re.compile(r"\s*/\s*mo", re.I)
_OCR_DASHES = str.maketrans(
    {
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2018": "'",
        "\u2019": "'",
    }
)
_SKU_ITEM = re.compile(
    r"^\s*\d{4,8}\s+(\S.*?)\s+(\d{1,3}(?:,\d{3})+|\d+)\.\d{2}\s*$"
)


def parse_receipt(text: str, *, source_name: str = "") -> ParsedRow:
    blob = (text or "").replace("\x00", "").translate(_OCR_DASHES)
    order_id = _first_group(blob, _ORDER_PATTERNS)
    date = _parse_date(blob)
    tax_year = date[:4] if date else ""
    vendor = _vendor(blob, source_name)
    product = _product(blob, source_name)
    pay = _payment(blob)

    subtotal = _labeled_money(blob, _SUBTOTAL)
    tax = _labeled_money(blob, _TAX)
    rewards = _labeled_money(blob, _REWARDS)
    shipping = _labeled_money(blob, _SHIP)
    free_ship = _labeled_money(blob, _FREE_SHIP)
    grand = _labeled_money(blob, _GRAND)
    total = _labeled_money(blob, _TOTAL)
    card = _labeled_money(blob, _CARD)
    listed = grand if grand is not None else total
    if listed is None:
        listed = card

    garbled_grand = grand is None and bool(
        re.search(r"Grand Total:", blob, re.I)
    )

    cash, notes, gap, status = _cash(
        subtotal=subtotal,
        tax=tax,
        rewards=rewards,
        shipping=shipping,
        free_ship=free_ship,
        listed=listed,
        card=card,
        garbled_grand=garbled_grand,
    )
    if vendor == "unknown" and status == "DOCUMENTED":
        status = "NEED_REVIEW"
        gap = (
            (gap + " | " if gap else "")
            + "vendor unknown — not DOCUMENTED until reviewed"
        )
        notes = (notes + " | " if notes else "") + "vendor unknown (OCR candidate)"

    desc = product or source_name or "receipt"
    if order_id:
        desc = f"{desc} (order {order_id})"

    return ParsedRow(
        tax_year=tax_year,
        date=date,
        vendor=vendor,
        description=desc[:200],
        schedule_c_or_form=_schedule(blob, desc, vendor),
        amount_usd=cash,
        status=status,
        payment_method=pay,
        evidence="",
        notes=notes,
        order_id=order_id,
        gap=gap,
        subtotal=_fmt(subtotal) if subtotal is not None else "",
        shipping=_fmt(shipping) if shipping is not None else "",
        tax=_fmt(tax) if tax is not None else "",
        discount=_fmt(rewards) if rewards is not None else "",
        printed_total=_fmt(listed) if listed is not None else "",
        rewards=_fmt(rewards) if rewards is not None else "",
        card_amount=_fmt(card) if card is not None else "",
    )


def _agree(left: Decimal | None, right: Decimal | None) -> bool:
    return (
        left is not None
        and right is not None
        and abs(left - right) <= Decimal("0.01")
    )


def _candidate_note(
    *,
    listed: Decimal | None,
    recomputed: Decimal | None,
    card: Decimal | None,
    parts: list[str],
) -> str:
    bits: list[str] = []
    if listed is not None:
        bits.append(f"printed_total {_fmt(listed)}")
    if recomputed is not None:
        formula = " + ".join(parts) if parts else _fmt(recomputed)
        bits.append(f"recompute {formula} = {_fmt(recomputed)}")
    if card is not None:
        bits.append(f"card {_fmt(card)}")
    return "ocr candidates: " + "; ".join(bits) if bits else ""


def _cash(
    *,
    subtotal: Decimal | None,
    tax: Decimal | None,
    rewards: Decimal | None,
    shipping: Decimal | None,
    free_ship: Decimal | None,
    listed: Decimal | None,
    card: Decimal | None,
    garbled_grand: bool,
) -> tuple[str, str, str | None, str]:
    parts: list[str] = []
    recomputed: Decimal | None = None
    if subtotal is not None:
        recomputed = subtotal
        parts.append(_fmt(subtotal))
        if shipping is not None:
            recomputed += shipping
            parts.append(f"shipping {_fmt(shipping)}")
        if free_ship is not None:
            recomputed -= free_ship
            parts.append(f"free shipping -{_fmt(free_ship)}")
        if tax is not None:
            recomputed += tax
            parts.append(f"tax {_fmt(tax)}")
        if rewards is not None:
            recomputed -= rewards
            parts.append(f"rewards {_fmt(rewards)}")

    diagnostics = _candidate_note(
        listed=listed, recomputed=recomputed, card=card, parts=parts
    )
    card_vs_listed = (
        card is not None
        and listed is not None
        and not _agree(card, listed)
    )
    card_vs_recompute = (
        card is not None
        and recomputed is not None
        and not _agree(card, recomputed)
    )

    if recomputed is not None and listed is not None:
        if _agree(recomputed, listed):
            note = " + ".join(parts) + f" = cash {_fmt(listed)}"
            if card_vs_listed:
                note = note + " | " + diagnostics
            return _fmt(listed), note, None, "DOCUMENTED"
        # A clean printed total ABOVE a recompute that is missing a component
        # (shipping or tax never parsed) is the cash that left the account.
        # Booking the recompute there books the product subtotal (Apex #1216:
        # Total 127.16 booked as 107.00, the $20.16 FedEx line dropped).
        missing = shipping is None or tax is None
        if listed > recomputed and missing:
            note = (
                " + ".join(parts)
                + f" + unitemized {_fmt(listed - recomputed)}"
                + " (shipping/tax/fees not parsed)"
                + f" = printed total {_fmt(listed)}"
            )
            return _fmt(listed), note, None, "DOCUMENTED"
        # Conflicting well-formed totals: keep OCR values as diagnostics.
        # Never present recompute (or the printed lie) as verified paid cash.
        gap = (
            "printed total and recompute disagree — do not book unverified cash"
        )
        return "", diagnostics, gap, "NEED_REVIEW"

    if recomputed is not None and (tax is not None or subtotal is not None):
        if card_vs_recompute and listed is None:
            gap = (
                "card amount and recompute disagree — do not book unverified cash"
            )
            return "", diagnostics, gap, "NEED_REVIEW"
        note = " + ".join(parts) + f" = cash {_fmt(recomputed)}"
        if garbled_grand:
            note = "Grand-total OCR garbled; recompute " + note
        return _fmt(recomputed), note, None, "DOCUMENTED"

    if listed is not None:
        if card_vs_listed:
            gap = (
                "printed total and card amount disagree — do not book unverified cash"
            )
            return "", diagnostics, gap, "NEED_REVIEW"
        # Lone listed/card total is uncorroborated even for a known vendor.
        # Independent subtotal+tax (or the Apex unitemized-shipping exception
        # above) is required before cash is DOCUMENTED.
        gap = (
            "listed total is uncorroborated (no matching subtotal+tax) — "
            "not DOCUMENTED until reviewed"
        )
        note = diagnostics or f"listed total {_fmt(listed)}"
        return "", note, gap, "NEED_REVIEW"

    return (
        "",
        diagnostics,
        "no well-formed cash total (subtotal+tax or Grand Total) — do not invent",
        "NEED_INVOICE",
    )


def _labeled_money(text: str, label: re.Pattern[str]) -> Decimal | None:
    """First label that is actually followed by money. Skip monthly rates.

    Gmail/confirmation bodies say "any amount owed" long before
    "Payment amount: $163.33". A single .search() would stop on the
    prose and never book the cash total.
    """
    for m in label.finditer(text):
        window = text[m.end() : m.end() + 80]
        hit = _MONEY_AFTER_LABEL.match(window)
        if not hit:
            continue
        value = _dec(hit.group(1))
        if value is None:
            continue
        tail = window[hit.end() : hit.end() + 8]
        if _PER_MONTH.match(tail):
            continue
        return value
    return None


def _dec(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def _fmt(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def _first_group(text: str, patterns: tuple[re.Pattern[str], ...]) -> str | None:
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


def _parse_date(text: str) -> str:
    raw = _first_group(text, _DATE_PATTERNS)
    if not raw:
        return ""
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    sep = "/" if "/" in raw else "-" if "-" in raw else ""
    if sep:
        parts = raw.split(sep)
        if len(parts) == 3:
            mm, dd, yy = parts
            if len(yy) == 2:
                yy = "20" + yy
            try:
                return datetime(int(yy), int(mm), int(dd)).strftime("%Y-%m-%d")
            except ValueError:
                pass
    year_hit = re.search(r"\b(20\d{2})\b", text)
    if year_hit:
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(f"{raw} {year_hit.group(1)}", fmt).strftime(
                    "%Y-%m-%d"
                )
            except ValueError:
                continue
    return ""


def _vendor(text: str, source_name: str) -> str:
    blob = f"{text}\n{source_name}".lower()
    if re.search(r"\blowe['’]?s\b", blob):
        return "Lowe's"
    if "star ridge" in blob:
        return "Star Ridge Aquatics"
    if "next insurance" in blob or "ergo next" in blob:
        return "Next Insurance"
    if "openai" in blob or "chatgpt" in blob:
        return "OpenAI"
    if "opticswave" in blob:
        return "OpticsWave"
    if "cloudflare" in blob:
        return "Cloudflare"
    if "moo.com" in blob or "moo inc" in blob:
        return "MOO"
    if "deco gear" in blob or "decobrands" in blob:
        return "Deco Gear"
    if "anthropic" in blob:
        return "Anthropic"
    if "xai" in blob or "grok" in blob:
        return "xAI / Grok"
    if "newegg" in blob:
        return "Newegg"
    if "smttr" in blob or "standard matter" in blob:
        return "SMTTR / Standard Matter"
    if "ebay" in blob:
        return "eBay"
    if "apex distribution" in blob:
        return "Apex Distribution"
    if "amazon" in blob or re.search(r"\d{3}-\d{7}-\d{7}", text):
        if "prime visa" in blob:
            return "Amazon Prime Visa 3092"
        return "Amazon"
    return "unknown"


def _payment(text: str) -> str:
    blob = text
    m = re.search(r"Prime Visa ending in\s*(\d{4})", blob, re.I)
    if m:
        return f"Prime Visa {m.group(1)}"
    m = re.search(r"\b[MH]/?C:?\s*[XK*]{4,}(\d{4})\b", blob, re.I)
    if m:
        return f"Mastercard {m.group(1)}"
    m = re.search(r"Mastercard(?: ending in)?\s*-?\s*(\d{4})", blob, re.I)
    if m:
        return f"Mastercard {m.group(1)}"
    m = re.search(r"Visa ending(?: in)?\s*(\d{4})", blob, re.I)
    if m:
        return f"Visa {m.group(1)}"
    m = re.search(r"\bVisa\s+\*{0,8}(\d{4})\b", blob, re.I)
    if m:
        return f"Visa {m.group(1)}"
    m = re.search(r"PayPal", blob, re.I)
    if m:
        return "PayPal"
    if re.search(r"\bACH\b", blob):
        m = re.search(r"Account ending in:\s*(\d{4})", blob, re.I)
        if m:
            return f"ACH {m.group(1)}"
        return "ACH"
    return ""


_PRODUCT_HINTS = (
    "general liability",
    "business insurance",
    "registrar registration fee",
    "registrar transfer fee",
    "aquascape",
    "deco gear",
    "business cards",
    "asus",
    "nvidia",
    "hiblow",
    "dewenwils",
    "gx10",
    "spark",
    "ultrawide",
    "monitor",
    "qsfp",
    "twinax",
    "chatgpt",
)


def _product(text: str, source_name: str) -> str:
    sku_items = _sku_item_names(text)
    if sku_items:
        return "; ".join(sku_items)
    skip = re.compile(
        r"order summary|ship to|payment method|grand total|item\(s\)|"
        r"sold by|supplied by|return window|back to top|conditions of use|"
        r"delivered |prime visa|view related|page \d|https://|invoice number|"
        r"date of issue|date due|bill to|pay online|description qty|subtotal|"
        r"amount due|company name|cloudflare|order placed|jon deoliveira|"
        r"gmail\.com|gmail - |fairmount|townsend|summer wind|invoice to|"
        r"customer details|congratulations|policy details|payment summary|"
        r"hi jon|next insurance <|1 message|@|"
        r"sign in to|track rewards|manage account|home centers|"
        r"pro rewards|points earned|points are awarded|settled and fulfilled|"
        r"sales#|trans#|\binvoice\b|total tax|authcd|est\.?\s*points",
        re.I,
    )
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" -")
        if len(line) < 12 or skip.search(line):
            continue
        letters = sum(c.isalpha() for c in line)
        if letters < 6 or letters < len(line) * 0.35:
            continue
        if _MONEY.search(line) and len(line) < 20:
            continue
        if re.fullmatch(r"[\d\s/$.,-]+", line):
            continue
        lines.append(line[:160])
    for line in lines:
        low = line.lower()
        if any(h in low for h in _PRODUCT_HINTS):
            return line
    if lines:
        return lines[0]
    stem = re.sub(r"[-_]+", " ", Path(source_name).stem).strip()
    return stem


def _sku_item_names(text: str) -> list[str]:
    """Storefront SKU lines: '111111 12-OZ PRO MARKING ORANGE    8.50'."""
    names: list[str] = []
    for raw in text.splitlines():
        hit = _SKU_ITEM.match(raw)
        if not hit:
            continue
        name = re.sub(r"\s+", " ", hit.group(1)).strip(" -")
        if len(name) < 4:
            continue
        letters = sum(c.isalpha() for c in name)
        if letters < 3:
            continue
        names.append(name[:80])
    return names


def _schedule(text: str, desc: str, vendor: str) -> str:
    blob = f"{text}\n{desc}\n{vendor}".lower()
    if any(
        tok in blob
        for tok in (
            "nvidia",
            "quadro",
            "rtx",
            "spark",
            "gx10",
            "epyc",
            "nemix",
            "monitor",
            "connectx",
            "network rack",
            "server rack",
            "tecmojo",
        )
    ):
        return "Form 4562 CAPEX"
    if "cloudflare" in blob or "registrar" in blob or "domain" in blob:
        return "other / advertising"
    if any(
        tok in blob
        for tok in ("next insurance", "ergo next", "general liability")
    ):
        return "insurance / overhead"
    if any(
        tok in blob
        for tok in ("aquascape", "hiblow", "pond", "uv", "bacteria", "liner")
    ):
        return "cogs / supplies"
    if any(tok in blob for tok in ("claude", "grok", "anthropic", "xai", "chatgpt", "openai")):
        return "supplies / other"
    return "supplies"
