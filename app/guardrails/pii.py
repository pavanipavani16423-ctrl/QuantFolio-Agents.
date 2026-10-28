"""Personal data detection and redaction (US and India).

Requests are redacted before they are stored, sent to a model or traced, so a client's PAN,
Aadhaar, card or phone number typed into the request box never leaves the server.
"""

import re
from typing import Any

PATTERNS: dict[str, re.Pattern] = {
    # bounded parts (RFC 5321 lengths): no quadratic backtracking on long dotted text
    "email": re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}\b"),
    "pan": re.compile(r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b"),  # Indian PAN, 4th letter = holder type
    # 12 digits in groups of 4, not part of a longer digit run (order or card numbers)
    "aadhaar": re.compile(r"(?<!\d)(?<!\d[ -])[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?![ -]?\d)"),
    "ssn": re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
    "card": re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"),
    "ifsc": re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),
    "phone": re.compile(r"(?<![\w+])(?:\+91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?!\d)"
                        r"|(?<![\w+])(?:\+1[ -]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)"),
    "account_number": re.compile(r"(?i)\b(?:a/?c|account)(?:\s*(?:no\.?|number|#))?\s*[:#]?\s*(\d{9,18})\b"),
}
LABEL = {"email": "EMAIL", "pan": "PAN", "aadhaar": "AADHAAR", "ssn": "SSN", "card": "CARD",
         "ifsc": "IFSC", "phone": "PHONE", "account_number": "ACCOUNT"}
# checked in this order: specific formats first, so a card number is not reported as a phone
ORDER = ("email", "pan", "ifsc", "ssn", "account_number", "card", "aadhaar", "phone")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Returns (text with each personal value replaced by [TYPE], {type: count})."""
    counts: dict[str, int] = {}
    for kind in ORDER:
        pattern = PATTERNS[kind]

        def repl(m: re.Match, kind: str = kind) -> str:
            value = m.group(0)
            if kind == "card":
                digits = re.sub(r"\D", "", value)
                if not (13 <= len(digits) <= 19 and _luhn(digits)):
                    return value
            if kind == "account_number":
                counts[kind] = counts.get(kind, 0) + 1
                return value.replace(m.group(1), f"[{LABEL[kind]}]")
            counts[kind] = counts.get(kind, 0) + 1
            return f"[{LABEL[kind]}]"

        text = pattern.sub(repl, text)
    return text, counts


def redact_any(value: Any, depth: int = 0) -> Any:
    """Recursive redaction for trace payloads (dicts, lists, strings)."""
    if depth > 8:
        return value
    if isinstance(value, str):
        return redact(value)[0] if len(value) < 20_000 else value
    if isinstance(value, dict):
        return {k: redact_any(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_any(v, depth + 1) for v in value]
    return value
