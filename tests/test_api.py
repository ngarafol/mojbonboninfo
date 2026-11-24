"""Protocol tests: what BonbonAPI sends and how it reads the answers.

The transport is stubbed instead of opening a socket: these tests are about the
request shape (method, body, headers, cookie) and the envelope handling, and a
fake session keeps them deterministic in any CI sandbox.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import pytest

from custom_components.bonbon.api import (
    BonbonAPI,
    BonbonApiError,
    BonbonAuthError,
)
from custom_components.bonbon.cookies import CookieJar
from custom_components.bonbon.session_import import PortalSession

NUMBERS = {
    "status": {"success": 1, "status_code": 0},
    "data": [
        {
            "msisdn": "385911234567",
            "number_nickname": "test1",
            "postpaid_flag": "0",
            "spending_hrk": " 35,58",
            "extra": {"expirationDate": "13.11.2026"},
        }
    ],
}

PROFILE = {"status": {"success": 1}, "primary_currency": "EUR", "packages": []}
PACKAGES = {"status": {"success": 1}, "can_activate": {"balance": 9.5}, "packages": []}
REFUSED = {
    "status": {"success": 0, "status_code": 99, "msg": "Usluga trenutno nije dostupna."}
}


class FakeHeaders(dict):
    """Just enough of a CIMultiDict for the client."""

    def getall(self, name: str, default: Any = None) -> list[str]:
        value = self.get(name)
        if value is None:
            return default if default is not None else []
        return value if isinstance(value, list) else [value]

    def get(self, name: str, default: Any = None) -> Any:  # noqa: D102
        for key, value in self.items():
            if key.lower() == name.lower():
                return value
        return default


class FakeResponse:
    """Minimal async response."""

    def __init__(self, status: int, url: str, body: dict, headers: dict | None = None):
        self.status = status
        self.url = url
        self.headers = FakeHeaders(headers or {})
        self._body = json.dumps(body).encode()

    async def read(self) -> bytes:
        """Return the encoded body."""
        return self._body

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False


class FakeSession:
    """Answers by path and remembers every call."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        """Record the call and return the mapped response."""
        self.calls.append({"method": method, "url": url, **kwargs})
        handler = self.routes[urlsplit(url).path]
        status, body = handler(json.loads(kwargs["data"] or b"{}"))
        return FakeResponse(status, url, body)


def portal_session(base: str = "https://api4.bonbon.hr") -> PortalSession:
    """A session shaped like an imported one."""
    jar = CookieJar()
    jar.update_from_headers(
        f"{base}/", ["PHPSESSID=abc123; Path=/", "bonbon_user=42; Path=/"]
    )
    return PortalSession(url=base, cookies=jar, headers={})


def routes(profile: dict, packages: dict, numbers: dict = NUMBERS) -> dict[str, Any]:
    """The three endpoints the integration calls."""

    def numbers_handler(payload: dict) -> tuple[int, dict]:
        return 200, numbers

    def profile_handler(payload: dict) -> tuple[int, dict]:
        return 200, profile

    def packages_handler(payload: dict) -> tuple[int, dict]:
        return 200, packages

    return {
        "/msisdn_data/list-all": numbers_handler,
        "/profile/status": profile_handler,
        "/package/list-all2": packages_handler,
    }


async def test_fetches_numbers_then_details_per_number() -> None:
    """Three POSTs carrying the portal's headers, one body per number."""
    session = FakeSession(routes(PROFILE, PACKAGES))
    api = BonbonAPI(session, portal_session())

    account = await api.async_get_account()

    assert [number.msisdn for number in account.numbers] == ["+385911234567"]
    assert account.numbers[0].balance == 9.5
    assert account.numbers[0].label == "test1"

    assert [call["url"].rsplit("/", 1)[-1] for call in session.calls] == [
        "list-all",
        "status",
        "list-all2",
    ]
    assert all(call["method"] == "POST" for call in session.calls)
    assert json.loads(session.calls[0]["data"]) == {}
    assert json.loads(session.calls[1]["data"]) == {"msisdn": "385911234567"}

    for call in session.calls:
        assert call["headers"]["X-bonbon-client"] == "portal"
        assert call["headers"]["Content-Type"].startswith("application/json")
        assert "PHPSESSID=abc123" in call["headers"]["Cookie"]


async def test_refused_number_keeps_the_portal_message() -> None:
    """A number the portal will not manage is still listed, with its reason."""
    session = FakeSession(routes(REFUSED, REFUSED))
    account = await BonbonAPI(session, portal_session()).async_get_account()

    number = account.numbers[0]
    assert number.details_available is False
    assert number.portal_message == "Usluga trenutno nije dostupna."
    assert number.balance is None
    assert number.label == "test1"


@pytest.mark.parametrize("status", [401, 403])
async def test_expired_session_is_an_auth_error(status: int) -> None:
    """HTTP 401/403 must trigger reauth, not a generic failure."""
    session = FakeSession({"/msisdn_data/list-all": lambda payload: (status, {})})
    with pytest.raises(BonbonAuthError):
        await BonbonAPI(session, portal_session()).async_get_account()


async def test_failed_envelope_is_an_api_error() -> None:
    """success: 0 on the numbers call is an error, not an empty account."""
    session = FakeSession({"/msisdn_data/list-all": lambda payload: (200, REFUSED)})
    with pytest.raises(BonbonApiError, match="nije dostupna"):
        await BonbonAPI(session, portal_session()).async_get_account()
