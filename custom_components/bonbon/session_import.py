"""Import an authenticated portal session from browser "Copy as cURL".

Bonbon signs users in through Hrvatski Telekom SSO (Google, Apple, ...), so
there is no password the integration could replay and no public OAuth client it
could use to exchange an authorization code: the `bonbon` Keycloak client is
confidential and the token endpoint rejects callers without its secret.

The honest way in is therefore the session the browser already holds. The user
copies one authenticated request from DevTools and the integration replays it.
A user can do that in about fifteen seconds and it keeps working until the
portal session dies - at which point the user already has a reauth prompt.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .cookies import CookieJar

# Headers worth replaying. Everything else Chrome adds (accept-encoding,
# sec-*, priority, ...) either breaks aiohttp or triggers bot heuristics.
REPLAY_HEADERS = frozenset(
    {
        "accept",
        "accept-language",
        "authorization",
        "origin",
        "referer",
        "user-agent",
    }
)

ALLOWED_HOSTS = ("bonbon.hr", "hrvatskitelekom.hr")


class SessionImportError(ValueError):
    """Raised when the pasted text is not a usable portal session."""


@dataclass(slots=True)
class PortalSession:
    """Everything needed to talk to the portal on the user's behalf."""

    url: str
    cookies: CookieJar = field(default_factory=CookieJar)
    headers: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serialise for the config entry / storage."""
        return {
            "url": self.url,
            "cookies": self.cookies.as_list(),
            "headers": self.headers,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortalSession:
        """Deserialise from the config entry / storage."""
        return cls(
            url=data.get("url", ""),
            cookies=CookieJar.from_list(data.get("cookies")),
            headers=dict(data.get("headers") or {}),
        )


def parse_curl(text: str) -> PortalSession:
    """Build a PortalSession from a "Copy as cURL" blob or a raw Cookie header."""
    cleaned = text.strip().replace("\\\n", " ").replace("^\n", " ")
    if not cleaned:
        raise SessionImportError("empty")

    if "curl" not in cleaned.lower():
        return _parse_cookie_header(cleaned)

    try:
        parts = shlex.split(cleaned)
    except ValueError as err:
        raise SessionImportError("unparsable") from err

    url: str | None = None
    headers: dict[str, str] = {}
    cookies: list[str] = []

    index = 0
    while index < len(parts):
        part = parts[index]
        if part in ("-H", "--header") and index + 1 < len(parts):
            name, _, value = parts[index + 1].partition(":")
            headers[name.strip().lower()] = value.strip()
            index += 2
            continue
        if part in ("-b", "--cookie") and index + 1 < len(parts):
            cookies.append(parts[index + 1])
            index += 2
            continue
        if part in ("-A", "--user-agent") and index + 1 < len(parts):
            headers["user-agent"] = parts[index + 1]
            index += 2
            continue
        if part in ("--data", "--data-raw", "--data-binary", "-d") and index + 1 < len(
            parts
        ):
            index += 2
            continue
        if part.startswith("-"):
            index += 1
            continue
        if part.startswith("http") and url is None:
            url = part
        index += 1

    cookie_header = headers.pop("cookie", None)
    if cookie_header:
        cookies.append(cookie_header)

    if url is None:
        raise SessionImportError("no_url")

    return _build(url, cookies, headers)


def _parse_cookie_header(text: str) -> PortalSession:
    """Fallback: the user pasted only a Cookie header."""
    value = text[len("cookie:") :].strip() if text.lower().startswith("cookie:") else text
    if "=" not in value:
        raise SessionImportError("no_cookie")
    return _build("https://www.bonbon.hr/", [value], {})


def _build(url: str, cookies: list[str], headers: dict[str, str]) -> PortalSession:
    """Validate the request and turn it into a PortalSession."""
    host = (urlsplit(url).hostname or "").lower()
    if not any(host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_HOSTS):
        raise SessionImportError("wrong_host")

    jar = CookieJar()
    for raw in cookies:
        jar.update_from_headers(url, [raw])
    if not jar:
        raise SessionImportError("no_cookie")

    replayed = {
        name: value
        for name, value in headers.items()
        if name in REPLAY_HEADERS and value
    }
    replayed.setdefault("accept", "application/json, text/plain, */*")
    return PortalSession(url=url, cookies=jar, headers=replayed)
