"""Setup and entity tests against the real Home Assistant test harness."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bonbon.api import BonbonAuthError
from custom_components.bonbon.const import CONF_CURL, CONF_SESSION, DOMAIN
from custom_components.bonbon.models import Account, Package, PhoneNumber

ACCOUNT = Account(
    numbers=[
        PhoneNumber(
            msisdn="+385911111111",
            balance=12.34,
            currency="EUR",
            valid_until=date(2026, 12, 1),
            packages=[
                Package(
                    name="Internet 30 GB",
                    remaining=21.4,
                    total=30,
                    unit="GB",
                    expires=date(2026, 12, 1),
                    auto_renew=True,
                ),
                Package(name="Minute", remaining=240, total=300, unit="min"),
            ],
        )
    ],
    refreshed_at=datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc),
)

CURL = "curl 'https://www.bonbon.hr/api/moj-bonbon/account' -H 'cookie: sid=1'"


def entry() -> MockConfigEntry:
    """Return a config entry shaped like one the config flow creates."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="385911111111",
        data={
            CONF_SESSION: {
                "url": "https://www.bonbon.hr/api/moj-bonbon/account",
                "cookies": [
                    {
                        "name": "sid",
                        "value": "1",
                        "domain": "www.bonbon.hr",
                        "path": "/",
                    }
                ],
                "headers": {"user-agent": "test"},
            }
        },
    )


def states_with(hass: HomeAssistant, attribute: str) -> list:
    """Return states carrying the given attribute."""
    return [state for state in hass.states.async_all() if attribute in state.attributes]


async def test_setup_creates_one_device_with_all_sensors(hass: HomeAssistant) -> None:
    """A configured entry loads and exposes balance, validity, packages and quotas."""
    config_entry = entry()
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.bonbon.api.BonbonAPI.async_get_account",
        new=AsyncMock(return_value=ACCOUNT),
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert any(
        "bonbon-card.js" in url
        for url in hass.data[DATA_EXTRA_MODULE_URL].urls
    ), "the card must be registered as a frontend resource"

    numbers = states_with(hass, "bonbon")
    assert len(numbers) == 1
    payload = numbers[0].attributes["bonbon"]
    assert payload["msisdn"] == "+385911111111"
    assert payload["balance"] == 12.34
    assert payload["valid_until"] == "2026-12-01"
    assert [package["name"] for package in payload["packages"]] == [
        "Internet 30 GB",
        "Minute",
    ]

    sensors = states_with(hass, "bonbon_number")
    assert sensors, "expected the sensors to expose bonbon_number"
    ids = {state.entity_id for state in sensors}
    assert "sensor.bonbon_385911111111_account_balance" in ids
    assert "sensor.bonbon_385911111111_phone_number" in ids

    def pick(unit: str):
        return next(
            state
            for state in sensors
            if state.attributes.get("unit_of_measurement") == unit
        )

    assert float(pick("EUR").state) == pytest.approx(12.34)
    assert float(pick("GB").state) == pytest.approx(21.4)
    assert float(pick("min").state) == pytest.approx(240)

    validity = next(state for state in sensors if "days_left" in state.attributes)
    assert validity.state == "2026-12-01"


async def test_silent_reauth_keeps_entry_loaded(hass: HomeAssistant) -> None:
    """An expired API session is renewed from the still-open portal page."""
    config_entry = entry()
    config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.bonbon.api.BonbonAPI.async_get_account",
            new=AsyncMock(side_effect=[BonbonAuthError("expired"), ACCOUNT]),
        ),
        patch(
            "custom_components.bonbon.api.BonbonAPI.async_touch_portal",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.bonbon.api.BonbonAPI.async_silent_reauth",
            new=AsyncMock(return_value=False),
        ),
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert states_with(hass, "bonbon")


async def test_dead_session_starts_reauth(hass: HomeAssistant) -> None:
    """When nothing can refresh the session, Home Assistant asks the user."""
    config_entry = entry()
    config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.bonbon.api.BonbonAPI.async_get_account",
            new=AsyncMock(side_effect=BonbonAuthError("expired")),
        ),
        patch(
            "custom_components.bonbon.api.BonbonAPI.async_touch_portal",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "custom_components.bonbon.api.BonbonAPI.async_silent_reauth",
            new=AsyncMock(return_value=False),
        ),
    ):
        assert not await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"].get("source") == "reauth" for flow in flows)


async def test_config_flow_accepts_a_browser_session(hass: HomeAssistant) -> None:
    """Pasting a cURL creates the entry with a stable unique id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    with patch(
        "custom_components.bonbon.config_flow._async_validate",
        new=AsyncMock(return_value=ACCOUNT),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CURL: CURL}
        )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_SESSION]["cookies"]
    assert result["result"].unique_id == "385911111111"


async def test_config_flow_rejects_garbage(hass: HomeAssistant) -> None:
    """A random string is a form error, not a crash."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CURL: "nije curl"}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_session"}
