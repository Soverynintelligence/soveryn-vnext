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
    tax: str = ""
    rewards: str = ""

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
        }


# Well-formed money only: dollars with exactly two cents digits, no extra dots.
# Allow 4+ digit amounts without commas ($4279.99) — Amazon prints those.
_MONEY = re.compile(r"\$\s*((?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})(?!\.?\d)")
_MONEY_AFTER_LABEL = re.compile(
    r"[:\s]*-?\s*\$\s*((?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})(?!\.?\d)"
)

_ORDER_PATTERNS = (
    re.compile(r"Order\s*#\s*(\d{3}-\d{7}-\d{7})", re.I),
    re.compile(r"\bORDER\s+(DG-\d+)\b", re.I),
    re.compile(r"Invoice number\s+(IN\d+|HRB[A-Z0-9]+)", re.I),
    re.compile(r"Receipt number\s+(\d{10,})", re.I),
    re.compile(r"Order\s*#\s*(OW[A-Z0-9]+)", re.I),
    re.compile(r"ORDER NO\s*#(\d+)", re.I),
    re.compile(r"Trans(?:action)?\s*I\.?D\.?\s*:?\s*(\d{10,})", re.I),
    re.compile(r"\border\s+(\d{2}-\d{5}-\d{5})\b", re.I),
    re.compile(r"\border\s+(\d{6,8})\b", re.I),
)

_DATE_PATTERNS = (
    re.compile(r"Order placed\s+([A-Za-z]+ \d{1,2}, \d{4})", re.I),
    re.compile(r"\bPLACED\s+([A-Za-z]+ \d{1,2}, \d{4})", re.I),
    re.compile(r"Date of issue\s+([A-Za-z]+ \d{1,2}, \d{4})", re.I),
    re.compile(r"Date paid\s+([A-Za-z]+ \d{1,2}, \d{4})", re.I),
    re.compile(r"paid on\s+([A-Za-z]+ \d{1,2}, \d{4})", re.I),
    re.compile(r"\bDATE\s+(\d{1,2} [A-Za-z]+ \d{4})", re.I),
    re.compile(r"Confirmed\s+([A-Za-z]+ \d{1,2}(?:,?\s+\d{4})?)", re.I),
    re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b"),
)

_SUBTOTAL = re.compile(r"Item(?:\(s\))?\s*Subtotal:|\bSubtotal\b", re.I)
_TAX = re.compile(r"Estimated tax to be\s*collected:|(?<!before )(?<!after )\bTax\b", re.I)
_REWARDS = re.compile(r"Rewards(?: Points)?:", re.I)
_SHIP = re.compile(
    r"Shipping(?:\s*&\s*Handling)?:|(?:^|\n)\s*Shipping\s+(?=\$)",
    re.I,
)
_FREE_SHIP = re.compile(r"Free Shipping:", re.I)
_GRAND = re.compile(
    r"Grand Total:|Amount due\b|Amount paid\b|Payment amount:?|\bAMOUNT\b",
    re.I,
)
_TOTAL = re.compile(r"\bTOTAL\b|\bTotal\b", re.I)
_PER_MONTH = re.compile(r"\s*/\s*mo", re.I)


def parse_receipt(text: str, *, source_name: str = "") -> ParsedRow:
    blob = (text or "").replace("\x00", "")
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
    total = _labeled_money(blob, _TOTAL) if grand is None else grand

    garbled_grand = grand is None and bool(
        re.search(r"Grand Total:", blob, re.I)
    )

    cash, notes, gap, status = _cash(
        subtotal=subtotal,
        tax=tax,
        rewards=rewards,
        shipping=shipping,
        free_ship=free_ship,
        listed=grand if grand is not None else total,
        garbled_grand=garbled_grand,
    )

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
        tax=_fmt(tax) if tax is not None else "",
        rewards=_fmt(rewards) if rewards is not None else "",
    )


def _cash(
    *,
    subtotal: Decimal | None,
    tax: Decimal | None,
    rewards: Decimal | None,
    shipping: Decimal | None,
    free_ship: Decimal | None,
    listed: Decimal | None,
    garbled_grand: bool,
) -> tuple[str, str, str | None, str]:
    parts: list[str] = []
    recomputed: Decimal | None = None
    if subtotal is not None:
        recomputed = subtotal
        parts.append(_fmt(subtotal))
        if shipping is not None:
            recomputed += shipping
        if free_ship is not None:
            recomputed -= free_ship
        if tax is not None:
            recomputed += tax
            parts.append(f"tax {_fmt(tax)}")
        if rewards is not None:
            recomputed -= rewards
            parts.append(f"rewards {_fmt(rewards)}")

    if recomputed is not None and listed is not None:
        if abs(recomputed - listed) <= Decimal("0.01"):
            note = " + ".join(parts) + f" = cash {_fmt(listed)}"
            return _fmt(listed), note, None, "DOCUMENTED"
        # Prefer the recompute when the printed total disagrees — OCR lies.
        note = (
            "printed total "
            + _fmt(listed)
            + " != recompute "
            + _fmt(recomputed)
            + "; booking recompute from subtotal+tax-rewards"
        )
        return _fmt(recomputed), note, None, "DOCUMENTED"

    if recomputed is not None and (tax is not None or subtotal is not None):
        note = " + ".join(parts) + f" = cash {_fmt(recomputed)}"
        if garbled_grand:
            note = "Grand-total OCR garbled; recompute " + note
        return _fmt(recomputed), note, None, "DOCUMENTED"

    if listed is not None:
        return _fmt(listed), f"listed total {_fmt(listed)}", None, "DOCUMENTED"

    return (
        "",
        "",
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
    if "/" in raw:
        parts = raw.split("/")
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
    skip = re.compile(
        r"order summary|ship to|payment method|grand total|item\(s\)|"
        r"sold by|supplied by|return window|back to top|conditions of use|"
        r"delivered |prime visa|view related|page \d|https://|invoice number|"
        r"date of issue|date due|bill to|pay online|description qty|subtotal|"
        r"amount due|company name|cloudflare|order placed|jon deoliveira|"
        r"gmail\.com|gmail - |fairmount|townsend|summer wind|invoice to|"
        r"customer details|congratulations|policy details|payment summary|"
        r"hi jon|next insurance <|1 message|@",
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
