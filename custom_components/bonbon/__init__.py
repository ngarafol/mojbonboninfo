"""The Bonbon integration: phone numbers, packages, balance and validity."""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import DummyCookieJar

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration

from .api import BonbonAPI
from .const import CARD_FILENAME, CARD_URL, CONF_SESSION, DOMAIN
from .coordinator import STORAGE_VERSION, BonbonCoordinator
from .session_import import PortalSession

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

type BonbonConfigEntry = ConfigEntry[BonbonCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: BonbonConfigEntry) -> bool:
    """Set up Bonbon from a config entry."""
    portal = await _async_load_session(hass, entry)

    # auto_cleanup: Home Assistant owns the session and closes it on stop.
    session = async_create_clientsession(hass, cookie_jar=DummyCookieJar())
    coordinator = BonbonCoordinator(hass, entry, BonbonAPI(session, portal))
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    await _async_register_card(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BonbonConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: BonbonConfigEntry) -> None:
    """Reload when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_load_session(
    hass: HomeAssistant, entry: BonbonConfigEntry
) -> PortalSession:
    """Return the freshest known portal session (store beats entry data)."""
    store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
    stored = await store.async_load()
    if stored:
        return PortalSession.from_dict(stored)
    return PortalSession.from_dict(entry.data[CONF_SESSION])


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the bundled Lovelace card and load it on every dashboard."""
    if hass.data.get(f"{DOMAIN}_card"):
        return
    hass.data[f"{DOMAIN}_card"] = True
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                CARD_URL,
                str(Path(__file__).parent / "frontend" / CARD_FILENAME),
                False,
            )
        ]
    )
    integration = await async_get_integration(hass, DOMAIN)
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    _LOGGER.debug("Registered Bonbon card at %s", CARD_URL)
