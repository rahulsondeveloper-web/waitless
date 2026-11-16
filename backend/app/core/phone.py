"""Phone normalisation to E.164. India-first (decision D7): 10-digit numbers get the default country code."""

import re

from app.core.config import get_settings

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"[\s\-().]", "", raw or "")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if not digits.startswith("+"):
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10:
            digits = get_settings().default_country_code + digits
        else:
            digits = "+" + digits
    if not _E164.match(digits):
        raise ValueError("Enter a valid mobile number.")
    if digits.startswith("+91") and (len(digits) != 13 or digits[3] not in "6789"):
        raise ValueError("Enter a valid 10-digit Indian mobile number.")
    return digits
