"""Parsing tests for the portal payloads (shapes taken from the portal's HAR)."""

from __future__ import annotations

from datetime import date, datetime

from bonbon_under_test.models import (
    NumberDetails,
    PayloadError,
    account_from_api,
    _as_float,
    _clean_msisdn,
)

NOW = datetime(2026, 11, 24, 9, 0)

NUMBERS = {
    "status": {"success": 1, "status_code": 0},
    "data": [
        {
            "id": "85876",
            "msisdn": "385911234567",
            "number_nickname": "b1",
            "display_text": "b1",
            "postpaid_flag": "0",
            "sim_type": "prp",
            "spending_hrk": " 35,58",
            "sim_expire_timestamp": "1794524400",
            "extra": {"expirationDate": "13.11.2026"},
        },
        {
            "id": "34303",
            "msisdn": "385929876543",
            "number_nickname": "test2",
            "postpaid_flag": "1",
            "sim_type": "pop",
            "spending_hrk": " 0,00",
            "sim_expire_timestamp": "2147483647",
            "extra": {"expirationDate": "nije dostupno", "puk1": "nije dostupno"},
        },
    ],
}

PROFILE_OK = {
    "status": {"success": 1},
    "primary_currency": "eur",
    "spending_hrk": " 12,34",
    "packages": [
        {
            "name": "Internet 30 GB",
            "current": 21.4,
            "max": 30,
            "percentage": 71.3,
            "text_left_label": "GB",
            "active_flag": 1,
            "info": "vrijedi do 01.12.2026.",
        },
        {
            "package_name": "Minute prema svima",
            "remaining": 240,
            "total": 300,
            "unit": "min",
            "auto_renew": 1,
        },
    ],
}

PACKAGES_OK = {
    "status": {"success": 1},
    "primary_currency": "EUR",
    "can_activate": {"balance": 12.34, "checkBalance": True, "permutations": []},
    "packages": [],
}

PROFILE_FAIL = {
    "status": {
        "success": 0,
        "status_code": 99,
        "msg": "Uuuups! Očito su nam se zapetljale neke žice... [34658]",
    },
    "extra_data": {"status": "disabled", "status_code": "service_not_available"},
}


def test_numbers_are_parsed_without_any_details() -> None:
    account = account_from_api(NUMBERS, {}, refreshed_at=NOW)
    assert len(account.numbers) == 2

    first, second = account.numbers
    assert first.msisdn == "+385911234567"
    assert first.label == "b1"
    assert first.spending == 35.58
    assert first.valid_until == date(2026, 11, 13)
    assert first.postpaid is False
    assert first.portal_message is None
    assert first.packages == []

    # 2147483647 is the portal's "never expires" sentinel
    assert second.valid_until is None
    assert second.postpaid is True


def test_details_are_merged_into_the_number() -> None:
    details = {"385911234567": NumberDetails(profile=PROFILE_OK, packages=PACKAGES_OK)}
    number = account_from_api(NUMBERS, details, refreshed_at=NOW).numbers[0]

    assert number.balance == 12.34
    assert number.currency == "EUR"
    assert number.spending == 12.34
    assert number.details_available is True

    assert [package.name for package in number.packages] == [
        "Internet 30 GB",
        "Minute prema svima",
    ]
    internet = number.packages[0]
    assert internet.remaining == 21.4
    assert internet.total == 30
    assert internet.unit == "GB"
    assert internet.percentage == 71.3

    minutes = number.packages[1]
    assert minutes.unit == "min"
    assert minutes.total == 300
    assert minutes.auto_renew is True


def test_portal_refusal_is_data_not_an_error() -> None:
    details = {
        "385911234567": NumberDetails(profile=PROFILE_FAIL, message="usluga nije dostupna")
    }
    number = account_from_api(NUMBERS, details, refreshed_at=NOW).numbers[0]

    assert number.details_available is False
    assert number.portal_message == "usluga nije dostupna"
    assert number.balance is None
    assert number.label == "b1"


def test_number_without_name_uses_display_text() -> None:
    payload = {
        "data": [
            {
                "msisdn": "385951112233",
                "number_nickname": "",
                "display_text": "testni broj",
            }
        ]
    }
    number = account_from_api(payload, {}, refreshed_at=NOW).numbers[0]
    assert number.label == "testni broj"


def test_unusable_payload_raises() -> None:
    for bad in ({"error": "nope"}, {"data": []}, {"data": [{"foo": 1}]}):
        try:
            account_from_api(bad, {}, refreshed_at=NOW)
        except PayloadError:
            continue
        raise AssertionError(f"expected PayloadError for {bad!r}")


def test_croatian_numbers_and_currency_strings() -> None:
    assert _as_float(" 35,58") == 35.58
    assert _as_float("1.234,56") == 1234.56
    assert _as_float("0,00") == 0.0
    assert _as_float("nije dostupno") is None
    assert _as_float(None) is None

    assert _clean_msisdn("385911234567") == "+385911234567"
    assert _clean_msisdn("091 123 4567") == "+385911234567"
    assert _clean_msisdn("00385911234567") == "+385911234567"
