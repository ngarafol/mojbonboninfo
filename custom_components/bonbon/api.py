"""HTTP client for the Bonbon portal API (api4.bonbon.hr)."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

import aiohttp

from homeassistant.exceptions import HomeAssistantError

from .const import (
    API_HEADERS,
    API_NUMBERS,
    API_PACKAGES,
    API_PROFILE,
    API_URL,
    OIDC_AUTHORIZE_URL,
    OIDC_CLIENT_ID,
    PORTAL_URL,
    SSO_REDIRECT_URI,
)
from .models import (
    Account,
    NumberDetails,
    PayloadError,
    account_from_api,
)
from .session_import import PortalSession

MAX_REDIRECTS = 8
TIMEOUT = aiohttp.ClientTimeout(total=45)


class BonbonError(HomeAssistantError):
    """Base error for the Bonbon integration."""


class BonbonAuthError(BonbonError):
    """The portal session is no longer valid."""


class BonbonConnectionError(BonbonError):
    """The portal could not be reached."""


class BonbonApiError(BonbonError):
    """The portal answered with something unexpected."""


@dataclass(slots=True)
class Response:
    """A fully read HTTP response."""

    status: int
    url: str
    body: bytes

    def json(self) -> Any:
        """Decode the body as JSON."""
        try:
            return json.loads(self.body)
        except ValueError as err:
            raise BonbonApiError(
                f"Expected JSON from {urlsplit(self.url).path}, got "
                f"{self.body[:120]!r}"
            ) from err


class BonbonAPI:
    """Talks to the portal on behalf of one config entry."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        portal: PortalSession,
        base_url: str = API_URL,
    ) -> None:
        self._session = session
        self.portal = portal
        self._base_url = base_url

    async def async_get_account(self, *, now: datetime | None = None) -> Account:
        """Fetch every number, then balance and packages per number."""
        numbers = await self._post(API_NUMBERS, {})
        items = numbers.get("data")
        if not isinstance(items, list):
            raise BonbonApiError("unexpected /msisdn_data/list-all answer")

        details: dict[str, NumberDetails] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            msisdn = item.get("msisdn")
            if not isinstance(msisdn, str) or not msisdn:
                continue
            details[msisdn] = await self._async_number_details(msisdn)

        try:
            return account_from_api(
                numbers, details, refreshed_at=now or datetime.now().astimezone()
            )
        except PayloadError as err:
            raise BonbonApiError(str(err)) from err

    async def async_silent_reauth(self) -> bool:
        """Re-run the SSO handshake using the stored cookies.

        Works when the user's Hrvatski Telekom SSO session is still alive: the
        authorization endpoint answers `prompt=none` with a redirect straight
        back to the portal, which then issues a fresh portal session cookie.
        """
        if not any(
            host.endswith("hrvatskitelekom.hr") for host in self.portal.cookies.hosts()
        ):
            return False

        query = urlencode(
            {
                "client_id": OIDC_CLIENT_ID,
                "response_type": "code",
                "redirect_uri": SSO_REDIRECT_URI,
                "scope": "openid",
                "prompt": "none",
                "state": secrets.token_urlsafe(16),
                "nonce": secrets.token_urlsafe(16),
            }
        )
        response = await self._request(
            "GET", f"{OIDC_AUTHORIZE_URL}?{query}", allow_redirects=True
        )
        host = (urlsplit(response.url).hostname or "").lower()
        return response.status < 400 and host.endswith("bonbon.hr")

    async def async_touch_portal(self) -> bool:
        """Ask the portal page for a fresh session, if it is still logged in.

        The API session is server side and can lapse while the portal itself is
        still signed in; in that case loading an authenticated page re-issues
        the session cookies and the API works again.
        """
        response = await self._request(
            "GET", f"{PORTAL_URL}/profil", allow_redirects=True
        )
        if response.status >= 400:
            return False
        path = urlsplit(response.url).path
        return path.startswith("/profil")

    async def _async_number_details(self, msisdn: str) -> NumberDetails:
        """Fetch balance/packages for one number; a refusal is data, not an error."""
        profile = await self._post(API_PROFILE, {"msisdn": msisdn}, allow_failure=True)
        packages = await self._post(
            API_PACKAGES, {"msisdn": msisdn}, allow_failure=True
        )

        message = _failure(profile) or _failure(packages)
        if message is None and profile is None and packages is None:
            message = "portal nije vratio podatke za ovaj broj"
        return NumberDetails(
            profile=profile if _ok(profile) else None,
            packages=packages if _ok(packages) else None,
            message=message,
        )

    async def _post(
        self, path: str, payload: dict[str, Any], *, allow_failure: bool = False
    ) -> dict[str, Any] | None:
        """POST a JSON body to the portal and unwrap the status envelope."""
        response = await self._request(
            "POST",
            urljoin(self._base_url, path),
            data=json.dumps(payload).encode(),
            extra_headers={"Content-Type": "application/json; charset=UTF-8"},
        )
        if response.status in (401, 403):
            raise BonbonAuthError(f"portal returned HTTP {response.status}")
        if response.status >= 400:
            if allow_failure:
                return None
            raise BonbonApiError(f"portal returned HTTP {response.status}")

        body = response.json()
        if not isinstance(body, dict):
            raise BonbonApiError("portal returned a non-object answer")

        status = body.get("status") if isinstance(body.get("status"), dict) else {}
        if status.get("status_code") in (401, 403) or "login" in str(
            status.get("msg", "")
        ).lower():
            raise BonbonAuthError(str(status.get("msg") or "portal session expired"))

        if not _ok(body):
            if allow_failure:
                return body
            raise BonbonApiError(_failure(body) or "portal reported an error")
        return body

    async def _request(
        self,
        method: str,
        url: str,
        *,
        allow_redirects: bool = False,
        data: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Response:
        """Perform a request, persisting every cookie the portal sets."""
        for _ in range(MAX_REDIRECTS + 1):
            headers = {**API_HEADERS, **self.portal.headers, **(extra_headers or {})}
            cookie = self.portal.cookies.header_for(url)
            if cookie:
                headers["Cookie"] = cookie
            try:
                async with self._session.request(
                    method,
                    url,
                    headers=headers,
                    data=data,
                    allow_redirects=False,
                    timeout=TIMEOUT,
                ) as response:
                    self.portal.cookies.update_from_headers(
                        str(response.url), response.headers.getall("Set-Cookie", [])
                    )
                    body = await response.read()
                    location = response.headers.get("Location")
                    if (
                        allow_redirects
                        and response.status in (301, 302, 303, 307, 308)
                        and location
                    ):
                        url = urljoin(str(response.url), location)
                        method = "GET" if response.status == 303 else method
                        data = None
                        continue
                    return Response(
                        status=response.status, url=str(response.url), body=body
                    )
            except (aiohttp.ClientError, TimeoutError) as err:
                raise BonbonConnectionError(str(err)) from err

        raise BonbonApiError("too many redirects")


def _ok(payload: dict[str, Any] | None) -> bool:
    """Return True when the portal's status envelope reports success."""
    if not isinstance(payload, dict):
        return False
    status = payload.get("status")
    return isinstance(status, dict) and bool(status.get("success"))


def _failure(payload: dict[str, Any] | None) -> str | None:
    """Return the portal's own explanation for a failed call."""
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if isinstance(status, dict) and not status.get("success"):
        message = status.get("msg")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return None
