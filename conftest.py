"""pytest configuration: Home Assistant's custom component test harness."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components.bonbon in every test."""
    yield


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """The coordinator schedules a refresh timer on purpose."""
    return True
