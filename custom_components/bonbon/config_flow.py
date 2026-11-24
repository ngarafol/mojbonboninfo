"""Config flow for Bonbon."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from aiohttp import DummyCookieJar

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    BonbonAPI,
    BonbonApiError,
    BonbonAuthError,
    BonbonConnectionError,
)
from .const import (
    CONF_CURL,
    CONF_EXCLUDED_NUMBERS,
    CONF_SCAN_INTERVAL_HOURS,
    CONF_SESSION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL_HOURS,
    MIN_SCAN_INTERVAL_HOURS,
    PORTAL_URL,
)
from .coordinator import async_clear_session
from .models import Account
from .session_import import PortalSession, SessionImportError, parse_curl

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CURL): selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        )
    }
)


class BonbonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Bonbon setup, reauth and options."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a browser session captured from DevTools."""
        errors: dict[str, str] = {}
        if user_input is not None:
            portal, account, error = await _async_check(
                self.hass, user_input[CONF_CURL]
            )
            if error:
                errors["base"] = error
            else:
                assert portal is not None and account is not None
                await self.async_set_unique_id(_unique_id(account))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=_title(account),
                    data={CONF_SESSION: portal.as_dict()},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"portal_url": PORTAL_URL},
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start the reauth flow."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh browser session."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            portal, account, error = await _async_check(
                self.hass, user_input[CONF_CURL]
            )
            if error:
                errors["base"] = error
            else:
                assert portal is not None and account is not None
                # the rotated session from the store is dead; drop it before
                # the reload, otherwise setup would read it back
                await async_clear_session(self.hass, entry.entry_id)
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_SESSION: portal.as_dict()}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"portal_url": PORTAL_URL},
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> BonbonOptionsFlow:
        """Return the options flow."""
        return BonbonOptionsFlow()


class BonbonOptionsFlow(OptionsFlow):
    """Polling interval and number visibility."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        data = getattr(self.config_entry.runtime_data, "data", None)
        numbers = {
            number.msisdn: number.label or number.msisdn
            for number in (data.numbers if data else [])
        }
        schema: dict[Any, Any] = {
            vol.Optional(
                CONF_SCAN_INTERVAL_HOURS,
                default=self.config_entry.options.get(
                    CONF_SCAN_INTERVAL_HOURS,
                    DEFAULT_SCAN_INTERVAL.total_seconds() / 3600,
                ),
            ): vol.All(
                vol.Coerce(float),
                vol.Range(min=MIN_SCAN_INTERVAL_HOURS, max=MAX_SCAN_INTERVAL_HOURS),
            )
        }
        if numbers:
            schema[
                vol.Optional(
                    CONF_EXCLUDED_NUMBERS,
                    default=self.config_entry.options.get(CONF_EXCLUDED_NUMBERS, []),
                )
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(numbers),
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))


async def _async_check(
    hass: Any, curl: str
) -> tuple[PortalSession | None, Account | None, str | None]:
    """Parse and prove a pasted session; returns (portal, account, error_key)."""
    try:
        portal = parse_curl(curl)
    except SessionImportError:
        return None, None, "invalid_session"
    try:
        return portal, await _async_validate(hass, portal), None
    except BonbonAuthError:
        return None, None, "invalid_auth"
    except BonbonConnectionError:
        return None, None, "cannot_connect"
    except BonbonApiError as err:
        _LOGGER.warning("Unexpected portal answer: %s", err)
        return None, None, "unknown"


async def _async_validate(hass: Any, portal: PortalSession) -> Account:
    """Prove the pasted session actually reads the account."""
    # auto_cleanup: Home Assistant closes the session; we never own it.
    session = async_create_clientsession(hass, cookie_jar=DummyCookieJar())
    return await BonbonAPI(session, portal).async_get_account()


def _unique_id(account: Account) -> str:
    """Stable id for one bonbon login."""
    return "|".join(sorted(number.slug for number in account.numbers))


def _title(account: Account) -> str:
    """User friendly entry title."""
    numbers = ", ".join(number.msisdn for number in account.numbers[:2])
    if len(account.numbers) > 2:
        numbers = f"{numbers} (+{len(account.numbers) - 2})"
    return numbers or "Bonbon"
