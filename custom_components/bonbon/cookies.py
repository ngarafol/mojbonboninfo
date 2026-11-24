"""A tiny persistent cookie jar.

aiohttp's cookie jar keeps cookies in memory only, and the Bonbon SSO handshake
touches two hosts (login.hrvatskitelekom.hr and www.bonbon.hr). Both need to
survive a Home Assistant restart without the user pasting anything again, so we
keep a small serialisable jar instead of `aiohttp.CookieJar`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from typing import Any, Iterable
from urllib.parse import urlsplit


@dataclass(slots=True)
class Cookie:
    """One cookie."""

    name: str
    value: str
    domain: str
    path: str = "/"
    secure: bool = False
    domain_cookie: bool = False
    expires: float | None = None

    def is_expired(self) -> bool:
        """Return True if the cookie has passed its expiry."""
        return self.expires is not None and self.expires <= time.time()

    def matches(self, host: str, path: str, secure: bool) -> bool:
        """Return True if the cookie applies to the request."""
        if self.secure and not secure:
            return False
        if self.domain_cookie:
            if host != self.domain and not host.endswith(f".{self.domain}"):
                return False
        elif host != self.domain:
            return False
        return path.startswith(self.path)

    def as_dict(self) -> dict[str, Any]:
        """Serialise for storage."""
        return {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "secure": self.secure,
            "domain_cookie": self.domain_cookie,
            "expires": self.expires,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Cookie:
        """Deserialise from storage."""
        return cls(
            name=data["name"],
            value=data["value"],
            domain=data["domain"],
            path=data.get("path", "/"),
            secure=data.get("secure", False),
            domain_cookie=data.get("domain_cookie", False),
            expires=data.get("expires"),
        )


@dataclass(slots=True)
class CookieJar:
    """Minimal cookie store keyed by (domain, path, name)."""

    cookies: dict[tuple[str, str, str], Cookie] = field(default_factory=dict)

    def __bool__(self) -> bool:
        """Return True if the jar holds any live cookie."""
        return any(not cookie.is_expired() for cookie in self.cookies.values())

    def live(self) -> list[Cookie]:
        """Return cookies that have not expired yet."""
        return [cookie for cookie in self.cookies.values() if not cookie.is_expired()]

    def update_from_headers(self, url: str, headers: Iterable[str]) -> None:
        """Store every Set-Cookie header received for `url`."""
        host = (urlsplit(url).hostname or "").lower()
        for raw in headers:
            self._update_one(raw, host)

    def _update_one(self, raw: str, host: str) -> None:
        parsed = SimpleCookie()
        try:
            parsed.load(raw)
        except Exception:  # noqa: BLE001 - a malformed cookie must not break polling
            return
        for name, morsel in parsed.items():
            domain = (morsel["domain"] or host).lstrip(".").lower()
            expires: float | None = None
            if morsel["max-age"]:
                try:
                    expires = time.time() + int(morsel["max-age"])
                except ValueError:
                    expires = None
            elif morsel["expires"]:
                expires = _parse_date(morsel["expires"])
            cookie = Cookie(
                name=name,
                value=morsel.value,
                domain=domain,
                path=morsel["path"] or "/",
                secure=bool(morsel["secure"]),
                domain_cookie=bool(morsel["domain"]),
                expires=expires,
            )
            self.cookies[(domain, cookie.path, name)] = cookie

    def header_for(self, url: str) -> str | None:
        """Build the Cookie header for `url`, or None."""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        path = parts.path or "/"
        secure = parts.scheme == "https"
        matching = [
            cookie for cookie in self.live() if cookie.matches(host, path, secure)
        ]
        if not matching:
            return None
        matching.sort(key=lambda cookie: len(cookie.path), reverse=True)
        return "; ".join(f"{cookie.name}={cookie.value}" for cookie in matching)

    def hosts(self) -> set[str]:
        """Return hosts that have at least one live cookie."""
        return {cookie.domain for cookie in self.live()}

    def as_list(self) -> list[dict[str, Any]]:
        """Serialise for storage."""
        return [cookie.as_dict() for cookie in self.live()]

    @classmethod
    def from_list(cls, data: list[dict[str, Any]] | None) -> CookieJar:
        """Deserialise from storage."""
        jar = cls()
        for item in data or []:
            cookie = Cookie.from_dict(item)
            if not cookie.is_expired():
                jar.cookies[(cookie.domain, cookie.path, cookie.name)] = cookie
        return jar


def _parse_date(value: str) -> float | None:
    """Parse an Expires attribute into epoch seconds."""
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None
