"""Protocol tests: what BonbonAPI actually sends and how it reads the answers."""

from __future__ import annotations

import json

import aiohttp
import pytest
from aiohttp import DummyCookieJar, web

from urllib.parse import urlsplit

from custom_components.bonbon.api import BonbonAPI, BonbonAuthError
from custom_components.bonbon.cookies import CookieJar
from custom_components.bonbon.session_import import PortalSession


def portal_session(base_url: str) -> PortalSession:
    """A session shaped like an imported one, pointed at the fake server."""
    host = urlsplit(base_url).hostname or "127.0.0.1"
    jar = CookieJar()
    jar.update_from_headers(
        f"http://{host}/", ["PHPSESSID=abc123; Path=/", "bonbon_user=42; Path=/"]
    )
    return PortalSession(url=base_url, cookies=jar, headers={"X-bonbon-client": "portal"})

NUMBERS = {
    "status": {"success": 1, "status_code": 0},
    "data": [
        {
            "id": "85876",
            "msisdn": "385911234567",
            "number_nickname": "b1",
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


class Recorder:
    """Collects what the integration sent."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def add(self, request: web.Request, body: str) -> None:
        self.requests.append(
            {
                "path": request.path,
                "method": request.method,
                "body": body,
                "headers": dict(request.headers),
            }
        )


@pytest.fixture
async def portal(aiohttp_client):
    """A fake api4.bonbon.hr with the endpoints the integration calls."""
    recorder = Recorder()
    app = web.Application()

    async def numbers(request: web.Request) -> web.Response:
        recorder.add(request, await request.text())
        if "PHPSESSID=abc123" not in request.headers.get("Cookie", ""):
            return web.json_response({"status": {"success": 0}}, status=401)
        return web.json_response(NUMBERS)

    async def profile(request: web.Request) -> web.Response:
        payload = json.loads(await request.text())
        recorder.add(request, json.dumps(payload))
        if payload.get("msisdn") == "385911234567":
            return web.json_response(PROFILE)
        return web.json_response(REFUSED)

    async def packages(request: web.Request) -> web.Response:
        payload = json.loads(await request.text())
        recorder.add(request, json.dumps(payload))
        return web.json_response(PACKAGES)

    app.router.add_post("/msisdn_data/list-all", numbers)
    app.router.add_post("/profile/status", profile)
    app.router.add_post("/package/list-all2", packages)
    client = await aiohttp_client(app)
    return client, recorder


async def test_fetches_numbers_then_details_per_number(portal, socket_enabled) -> None:
    """Three POSTs with the portal's own headers, one body per number."""
    client, recorder = portal
    async with aiohttp.ClientSession(cookie_jar=DummyCookieJar()) as session:
        base = str(client.make_url(""))
        api = BonbonAPI(session, portal_session(base), base_url=base)
        account = await api.async_get_account()

    assert [number.msisdn for number in account.numbers] == ["+385911234567"]
    assert account.numbers[0].balance == 9.5
    assert account.numbers[0].label == "b1"

    assert [request["path"] for request in recorder.requests] == [
        "/msisdn_data/list-all",
        "/profile/status",
        "/package/list-all2",
    ]
    assert all(request["method"] == "POST" for request in recorder.requests)
    assert recorder.requests[1]["body"] == '{"msisdn": "385911234567"}'
    assert all(
        request["headers"]["X-bonbon-client"] == "portal"
        for request in recorder.requests
    )
    assert all(
        request["headers"]["Content-Type"].startswith("application/json")
        for request in recorder.requests
    )
    assert all(
        "PHPSESSID=abc123" in request["headers"]["Cookie"]
        for request in recorder.requests
    )


async def test_missing_session_is_an_auth_error(aiohttp_client, socket_enabled) -> None:
    """A portal that answers 401 must trigger reauth, not a generic failure."""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"status": {"success": 0}}, status=401)

    app = web.Application()
    app.router.add_post("/msisdn_data/list-all", handler)
    client = await aiohttp_client(app)

    async with aiohttp.ClientSession(cookie_jar=DummyCookieJar()) as session:
        base = str(client.make_url(""))
        api = BonbonAPI(session, portal_session(base), base_url=base)
        with pytest.raises(BonbonAuthError):
            await api.async_get_account()
