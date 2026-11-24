"""Constants for the Bonbon integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "bonbon"
MANUFACTURER: Final = "bonbon"
VERSION: Final = "0.1.0"

# Polling. The portal data changes slowly and bonbon's own app refreshes on
# demand, so a few hours is plenty and keeps the SSO session alive.
DEFAULT_SCAN_INTERVAL: Final = timedelta(hours=3)
MIN_SCAN_INTERVAL_HOURS: Final = 1
MAX_SCAN_INTERVAL_HOURS: Final = 24

CONF_SCAN_INTERVAL_HOURS: Final = "scan_interval_hours"
CONF_CURL: Final = "curl"
CONF_SESSION: Final = "session"
CONF_EXCLUDED_NUMBERS: Final = "excluded_numbers"

# Portal / SSO endpoints.
PORTAL_URL: Final = "https://www.bonbon.hr"
SSO_REDIRECT_URI: Final = f"{PORTAL_URL}/sso"
API_URL: Final = "https://api4.bonbon.hr"
OIDC_AUTHORIZE_URL: Final = (
    "https://login.hrvatskitelekom.hr/realms/Bonbon/protocol/openid-connect/auth"
)
OIDC_CLIENT_ID: Final = "bonbon"

# Portal endpoints, from the portal's own bundle (prfl/main.bundle.js).
# Everything is a POST with a JSON body; per-number calls send {"msisdn": ...}.
API_NUMBERS: Final = "/msisdn_data/list-all"
API_PROFILE: Final = "/profile/status"
API_PACKAGES: Final = "/package/list-all2"

# The portal's API only answers requests that look like its own frontend.
API_HEADERS: Final = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json; charset=UTF-8",
    "Origin": PORTAL_URL,
    "Referer": f"{PORTAL_URL}/",
    "X-bonbon-client": "portal",
}

# Card.
CARD_FILENAME: Final = "bonbon-card.js"
CARD_URL: Final = f"/{DOMAIN}_static/{CARD_FILENAME}"

ATTR_BONBON: Final = "bonbon"
ATTR_BONBON_NUMBER: Final = "bonbon_number"
ATTR_BONBON_ENTRY_ID: Final = "bonbon_entry_id"
