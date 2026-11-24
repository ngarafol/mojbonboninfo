"""Data model and portal payload parsing.

Deliberately free of Home Assistant imports: this is the part that breaks when
bonbon redeploys the portal, so it stays small and unit-testable with plain
pytest.

Payload shapes come from the portal's own bundle (prfl/main.bundle.js):

    POST /msisdn_data/list-all   -> {"status": {...}, "data": [ {number}, ... ]}
    POST /profile/status         -> {"status": {...}, "packages": [...], "spending_hrk": ...}
    POST /package/list-all2      -> {"status": {...}, "can_activate": {...}, "packages": [...]}

The per-number endpoints answer HTTP 200 with `status.success == 0` and a
Croatian explanation when the portal cannot manage a number (expired, not
registered, ...). That is not an integration failure: the number is still
listed, it just has no balance or packages to show.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

_NEVER = 2147483647  # the portal's "no expiry" epoch
_NO_VALUE = ("nije dostupno", "n/a", "-")

_UNIT_ALIASES = {
    "gb": "GB",
    "gigabajt": "GB",
    "mb": "MB",
    "min": "min",
    "minuta": "min",
    "minutes": "min",
    "sms": "SMS",
    "kom": "SMS",
}


class PayloadError(ValueError):
    """Raised when the portal answers with something we do not understand."""


@dataclass(slots=True)
class Package:
    """One active package (internet, minutes, SMS, ...)."""

    name: str
    remaining: float | None = None
    total: float | None = None
    unit: str | None = None
    expires: date | None = None
    auto_renew: bool | None = None
    percentage: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialise for entity attributes."""
        return {
            "name": self.name,
            "remaining": self.remaining,
            "total": self.total,
            "unit": self.unit,
            "expires": self.expires.isoformat() if self.expires else None,
            "auto_renew": self.auto_renew,
            "percentage": self.percentage,
        }


@dataclass(slots=True)
class PhoneNumber:
    """One phone number and its current state."""

    msisdn: str
    label: str | None = None
    balance: float | None = None
    spending: float | None = None
    currency: str = "EUR"
    valid_until: date | None = None
    packages: list[Package] = field(default_factory=list)
    postpaid: bool = False
    portal_message: str | None = None

    @property
    def slug(self) -> str:
        """Stable, readable identifier used in entity ids."""
        return re.sub(r"\D", "", self.msisdn) or self.msisdn

    @property
    def details_available(self) -> bool:
        """True when the portal returned balance/packages for this number."""
        return self.portal_message is None

    def as_dict(self) -> dict[str, Any]:
        """Serialise for entity attributes and the card."""
        return {
            "msisdn": self.msisdn,
            "label": self.label,
            "balance": self.balance,
            "spending": self.spending,
            "currency": self.currency,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "packages": [package.as_dict() for package in self.packages],
            "postpaid": self.postpaid,
            "portal_message": self.portal_message,
        }


@dataclass(slots=True)
class NumberDetails:
    """What the portal answered for one number's balance and packages."""

    profile: dict[str, Any] | None = None
    packages: dict[str, Any] | None = None
    message: str | None = None


@dataclass(slots=True)
class Account:
    """All numbers behind one login."""

    numbers: list[PhoneNumber]
    refreshed_at: datetime


def account_from_api(
    numbers_payload: Any,
    details: dict[str, NumberDetails],
    *,
    refreshed_at: datetime,
) -> Account:
    """Merge /msisdn_data/list-all with the per-number detail answers."""
    items = _items(numbers_payload)
    if not items:
        raise PayloadError("no numbers in /msisdn_data/list-all")

    account = Account(numbers=[], refreshed_at=refreshed_at)
    for item in items:
        number = _parse_number(item)
        if number is None:
            continue
        detail = details.get(number.msisdn) or details.get(number.slug)
        if detail is not None:
            _merge_details(number, detail)
        account.numbers.append(number)
    if not account.numbers:
        raise PayloadError("no parsable numbers in /msisdn_data/list-all")
    return account


def _items(payload: Any) -> list[dict[str, Any]]:
    """Return the list of number dicts from the response envelope."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def _parse_number(item: dict[str, Any]) -> PhoneNumber | None:
    """Parse one entry of /msisdn_data/list-all."""
    msisdn = _str(item.get("msisdn")) or _str(item.get("number"))
    if not msisdn:
        return None

    postpaid = _str(item.get("postpaid_flag")) in ("1", "true")
    extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
    number = PhoneNumber(
        msisdn=_clean_msisdn(msisdn),
        label=_str(item.get("number_nickname")) or _str(item.get("display_text")),
        spending=_as_float(item.get("spending_hrk")),
        valid_until=_expiry_date(item),
        postpaid=postpaid,
    )
    if isinstance(extra.get("expirationDate"), str):
        number.valid_until = _as_date(extra["expirationDate"]) or number.valid_until
    return number


def _expiry_date(item: dict[str, Any]) -> date | None:
    """Expiry from sim_expire_timestamp, ignoring the "never" sentinel."""
    timestamp = _as_float(item.get("sim_expire_timestamp"))
    if not timestamp or timestamp >= _NEVER:
        return None
    try:
        return datetime.fromtimestamp(timestamp).date()
    except (OSError, ValueError):
        return None


def _merge_details(number: PhoneNumber, detail: NumberDetails) -> None:
    """Fold /profile/status and /package/list-all2 into the number."""
    if detail.message:
        number.portal_message = detail.message

    profile = detail.profile or {}
    packages_payload = detail.packages or {}

    currency = _str(profile.get("primary_currency")) or _str(
        packages_payload.get("primary_currency")
    )
    if currency:
        number.currency = currency.upper()

    spending = _as_float(profile.get("spending_hrk"))
    if spending is not None:
        number.spending = spending

    balance = _as_float((packages_payload.get("can_activate") or {}).get("balance"))
    if balance is None:
        balance = _as_float(profile.get("balance")) or _as_float(
            profile.get("balance_hrk")
        )
    number.balance = balance

    raw_packages = profile.get("packages") or packages_payload.get("packages") or []
    if isinstance(raw_packages, list):
        number.packages = [
            parsed
            for raw in raw_packages
            if isinstance(raw, dict) and (parsed := _parse_package(raw)) is not None
        ]


def _parse_package(raw: dict[str, Any]) -> Package | None:
    """Parse one package from either payload.

    The portal renders package quotas from a display-shaped list (name, current,
    max, percentage, labels), so both shapes are accepted key by key.
    """
    name = _str(raw.get("package_name")) or _str(raw.get("name")) or _str(
        raw.get("title")
    )
    if not name:
        name = _str(raw.get("description"))
    if not name:
        return None

    remaining = _first_float(
        raw, ("remaining", "current", "left", "available", "amount_current", "kolicina")
    )
    total = _first_float(
        raw, ("total", "max", "amount", "package_size", "quota", "ukupno")
    )
    percentage = _as_float(raw.get("percentage"))
    if percentage is None and remaining is not None and total:
        percentage = round(remaining / total * 100, 1)

    return Package(
        name=name,
        remaining=remaining,
        total=total,
        unit=_unit(raw),
        expires=_first_date(raw, ("expires", "valid_until", "date_end", "expiry")),
        auto_renew=_as_bool(raw.get("auto_renew") or raw.get("renewal_flag")),
        percentage=percentage,
    )


def _unit(raw: dict[str, Any]) -> str | None:
    """Return a short unit label for a package."""
    unit = _str(raw.get("unit")) or _str(raw.get("measure"))
    if not unit:
        labels = [
            _str(raw.get("text_left_label")),
            _str(raw.get("text_right_label")),
            _str(raw.get("package_type")),
            _str(raw.get("package_name")),
        ]
        for label in labels:
            if not label:
                continue
            token = label.strip().lower()
            if token in _UNIT_ALIASES:
                return _UNIT_ALIASES[token]
            for suffix in ("gb", "mb", "sms", "min"):
                if re.search(rf"\b{suffix}\b", token):
                    return _UNIT_ALIASES[suffix]
    return _UNIT_ALIASES.get(unit.lower(), unit)


def _clean_msisdn(value: str) -> str:
    """Normalise a phone number to +digits (the portal sends 385...)."""
    digits = re.sub(r"[^\d+]", "", value)
    if digits.startswith("00"):
        digits = f"+{digits[2:]}"
    elif digits.startswith("0"):
        digits = f"+385{digits[1:]}"
    elif not digits.startswith("+"):
        digits = f"+{digits}"
    return digits


def _str(value: Any) -> str | None:
    """Return a stripped string or None."""
    if isinstance(value, str):
        text = value.strip()
        if text and text.lower() not in _NO_VALUE:
            return text
    return None


def _first_float(raw: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    """Return the first numeric value found for any of `keys`."""
    for key in keys:
        value = _as_float(raw.get(key))
        if value is not None:
            return value
    return None


def _first_date(raw: dict[str, Any], keys: tuple[str, ...]) -> date | None:
    """Return the first date value found for any of `keys`."""
    for key in keys:
        value = _as_date(raw.get(key))
        if value is not None:
            return value
    return None


def _as_bool(value: Any) -> bool | None:
    """Coerce the portal's 0/1 flags to bool."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "da")
    return None


def _as_float(value: Any) -> float | None:
    """Coerce a JSON value to float, accepting Croatian formatting."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(" ", "").replace("€", "")
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _as_date(value: Any) -> date | None:
    """Coerce a JSON value to a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in _NO_VALUE:
            return None
        for fmt in ("%d.%m.%Y.", "%d.%m.%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None
