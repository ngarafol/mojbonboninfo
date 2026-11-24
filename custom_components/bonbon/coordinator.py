"""Coordinator: poll the portal a few times a day, keep the session alive."""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BonbonAPI,
    BonbonApiError,
    BonbonAuthError,
    BonbonConnectionError,
)
from .const import CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import Account

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1


class BonbonCoordinator(DataUpdateCoordinator[Account]):
    """Owns the portal session and the parsed account data."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: BonbonAPI
    ) -> None:
        self.api = api
        self._store: Store[dict] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._saved_session = json.dumps(api.portal.as_dict(), sort_keys=True)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=_scan_interval(entry),
            always_update=False,
        )

    async def _async_update_data(self) -> Account:
        """Fetch the account, refreshing the SSO session once if it lapsed."""
        try:
            account = await self.api.async_get_account()
        except BonbonAuthError:
            if not await self._async_refresh_session():
                raise ConfigEntryAuthFailed(
                    "Bonbon session expired; paste a fresh browser session"
                ) from None
            try:
                account = await self.api.async_get_account()
            except BonbonAuthError as err:
                raise ConfigEntryAuthFailed(
                    "Bonbon session expired; paste a fresh browser session"
                ) from err
        except BonbonConnectionError as err:
            raise UpdateFailed(f"Cannot reach bonbon.hr: {err}") from err
        except BonbonApiError as err:
            raise UpdateFailed(f"Unexpected answer from bonbon.hr: {err}") from err

        await self._async_save_session()
        return account

    async def _async_refresh_session(self) -> bool:
        """Try to renew the session without bothering the user.

        Two chances: the still-open portal page (cheap, common), then the SSO
        handshake with stored Keycloak cookies (works even after the portal
        session itself expired).
        """
        try:
            if await self.api.async_touch_portal():
                return True
            return await self.api.async_silent_reauth()
        except BonbonApiError:
            return False
        except BonbonConnectionError as err:
            raise UpdateFailed(f"Cannot reach the portal: {err}") from err

    async def _async_save_session(self) -> None:
        """Persist rotated cookies so a restart does not need a new login."""
        payload = self.api.portal.as_dict()
        serialised = json.dumps(payload, sort_keys=True)
        if serialised == self._saved_session:
            return
        await self._store.async_save(payload)
        self._saved_session = serialised


async def async_clear_session(hass: HomeAssistant, entry_id: str) -> None:
    """Forget a stored session, e.g. right after a successful reauth."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}").async_remove()


def _scan_interval(entry: ConfigEntry) -> timedelta:
    """Return the configured polling interval."""
    hours = entry.options.get(CONF_SCAN_INTERVAL_HOURS)
    if not hours:
        return DEFAULT_SCAN_INTERVAL
    return timedelta(hours=float(hours))
