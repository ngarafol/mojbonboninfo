"""Cookie jar and session import tests."""

from __future__ import annotations

import time

from bonbon_under_test.cookies import CookieJar
from bonbon_under_test.session_import import (
    SessionImportError,
    parse_curl,
)

URL = "https://www.bonbon.hr/moj-bonbon"


def jar_with(*headers: str, url: str = URL) -> CookieJar:
    jar = CookieJar()
    jar.update_from_headers(url, headers)
    return jar


def test_set_cookie_is_scoped_to_host() -> None:
    jar = jar_with("portalsession=abc; Path=/; HttpOnly")
    assert jar.header_for(URL) == "portalsession=abc"
    assert jar.header_for("https://www.bonbon.hr/api/x") == "portalsession=abc"
    assert jar.header_for("https://evil.example/") is None


def test_domain_cookie_reaches_subdomains_only() -> None:
    jar = jar_with("sso=1; Domain=.bonbon.hr; Path=/")
    assert jar.header_for("https://api.bonbon.hr/") == "sso=1"
    assert jar.header_for("https://notbonbon.hr/") is None


def test_path_and_secure() -> None:
    jar = jar_with("a=1; Path=/api")
    assert jar.header_for("https://www.bonbon.hr/api/moj") == "a=1"
    assert jar.header_for("https://www.bonbon.hr/moj-bonbon") is None

    secure = jar_with("b=2; Secure")
    assert secure.header_for("https://www.bonbon.hr/") == "b=2"
    assert secure.header_for("http://www.bonbon.hr/") is None


def test_expiry_is_dropped() -> None:
    jar = jar_with("gone=1; Max-Age=0")
    assert not jar
    assert jar.header_for(URL) is None

    jar = jar_with("soon=1; Max-Age=60")
    assert jar.header_for(URL) == "soon=1"


def test_roundtrip_through_storage() -> None:
    jar = jar_with("a=1", "b=2; Max-Age=3600")
    restored = CookieJar.from_list(jar.as_list())
    header = restored.header_for(URL) or ""
    assert "a=1" in header and "b=2" in header


def test_expired_cookie_is_not_restored() -> None:
    data = [
        {
            "name": "old",
            "value": "1",
            "domain": "www.bonbon.hr",
            "path": "/",
            "expires": time.time() - 10,
        }
    ]
    assert not CookieJar.from_list(data)


def test_parse_bash_curl() -> None:
    curl = """curl 'https://www.bonbon.hr/api/moj-bonbon/account?x=1' \\
      -H 'accept: application/json' \\
      -H 'cookie: portalsession=abc; sso=xyz' \\
      -H 'user-agent: Mozilla/5.0' \\
      -H 'sec-ch-ua: "Chromium";v="131"' \\
      --compressed"""
    portal = parse_curl(curl)
    assert portal.url.startswith("https://www.bonbon.hr/api/")
    assert portal.headers["user-agent"] == "Mozilla/5.0"
    assert "sec-ch-ua" not in portal.headers
    header = portal.cookies.header_for(URL) or ""
    assert "portalsession=abc" in header
    assert "sso=xyz" in header


def test_parse_curl_keeps_authorization_header() -> None:
    curl = (
        "curl 'https://www.bonbon.hr/api/x' "
        "-H 'authorization: Bearer eyJhbGci' "
        "-H 'cookie: a=1'"
    )
    portal = parse_curl(curl)
    assert portal.headers["authorization"] == "Bearer eyJhbGci"


def test_parse_cookie_header_only() -> None:
    portal = parse_curl("Cookie: portalsession=abc; other=1")
    assert "portalsession=abc" in (portal.cookies.header_for(URL) or "")


def test_rejects_unusable_input() -> None:
    for text in (
        "",
        "curl 'https://example.com/' -H 'cookie: a=1'",
        "curl 'https://www.bonbon.hr/api' -H 'accept: json'",
        "hello world",
    ):
        try:
            parse_curl(text)
        except SessionImportError:
            continue
        raise AssertionError(f"expected SessionImportError for {text!r}")
