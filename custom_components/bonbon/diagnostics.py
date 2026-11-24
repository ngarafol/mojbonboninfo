"""Diagnostics: enough to debug a broken portal, never a cookie value."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import BonbonCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry[BonbonCoordinator]
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    portal = coordinator.api.portal
    data = coordinator.data
    return {
        "entry": {
            "title": entry.title,
            "options": dict(entry.options),
            "unique_id": entry.unique_id,
        },
        "session": {
            "hosts": sorted(portal.cookies.hosts()),
            "cookie_names": sorted(
                {cookie.name for cookie in portal.cookies.live()}
            ),
            "header_names": sorted(portal.headers),
        },
        "account": {
            "refreshed_at": data.refreshed_at.isoformat(),
            "numbers": [number.as_dict() for number in data.numbers],
        },
        "last_update_success": coordinator.last_update_success,
    }
